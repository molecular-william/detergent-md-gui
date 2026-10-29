"""The installed Martini 3 force field: one copy that every run reads.

`references/` is the vendored upstream -- the published lipidome, the sugar reference and their licences. This module
installs that set once under the workspace (`workspace/dashboard/martini3/`) and is the one place that answers where a
Martini file is, so no run copies one and no two readers can disagree about which bytes a run simulated with.

Three properties are deliberate:

* **Installed, not read in place.** A run must not read the repository: the checkout is code, the workspace is data,
  and the workspace can sit anywhere (`config/dashboard-paths.json`, `DASHBOARD_WORKSPACE`, a test's `tmp_path`). The
  install is what makes the shared directory reachable by a relative path from every stage directory.
* **Never silently different.** `martini3.json` records the upstream commit and every file's digest. An installed file
  whose bytes disagree with it, or an upstream set that no longer matches the install, refuses and names the file.
  `refresh=True` is the deliberate reinstall -- a run never takes new bytes because somebody edited `references/`.
* **Cheap after the first check.** Verifying 18 MB on every `prepare` would cost a run nothing and a test suite a lot,
  so the upstream listing and the installed digests are cached per process against their own stamp. A run's own
  guarantee does not depend on that cache: `inputs.json` re-hashes the files the run declared before every stage.

The relative include is the reason this module exists at all: GROMACS resolves `#include` from the working directory,
so a topology names the shared file by a path computed from where the topology will be read (`include`).
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

from . import files, paths

#: The directory under the workspace that every run reads the force field from.
DIRECTORY = 'martini3'
#: The install's own record: upstream identity and one digest per installed file.
MANIFEST_NAME = 'martini3.json'
#: Points the install somewhere else than the workspace. Symmetric with `DASHBOARD_WORKSPACE`; the test suite uses it
#: to install once per session instead of once per temporary workspace.
ENVIRONMENT_VARIABLE = 'DASHBOARD_MARTINI3'

#: Where the vendored upstream lives, relative to the project root.
UPSTREAM_ITPS = 'references/M3-Lipid-Parameters/ITPs'
#: The files that are not in the lipidome's `ITPs/` directory but are still part of the official set.
UPSTREAM_EXTRA = {
    'martini_v3.0.0_sugars_v2.itp': 'references/martini_v3.0.0_sugars_v2.itp',
    'martini_v3.0.0_sugars_v2.source.json': 'references/martini_v3.0.0_sugars_v2.source.json',
    'LICENSE.txt': 'references/M3-Lipid-Parameters/LICENSE.txt',
    'README.md': f'{UPSTREAM_ITPS}/README.md',
}

#: The files a CG system needs: the bead types, the water molecule type and the ion molecule types. Named here, and by
#: every adapter, so the topology writer and the input record cannot drift apart.
REQUIRED = ('martini_v3.0.0.itp', 'martini_v3.0.0_solvents_v1.itp', 'martini_v3.0.0_ions_v1.itp')
#: The published sugar reference and the sidecar that says where it came from.
SUGARS = ('martini_v3.0.0_sugars_v2.itp', 'martini_v3.0.0_sugars_v2.source.json')

#: Where the set came from. Recorded in `martini3.json` and in every run that simulated with it.
SOURCE = {
    'repository': 'https://github.com/Martini-Force-Field-Initiative/M3-Lipid-Parameters.git',
    'commit': '2121527',
    'doi': '10.1021/acscentsci.5c00755',
    'citation': 'Pedersen et al., The Martini 3 Lipidome, ACS Central Science (2025)',
    'license': 'Apache-2.0',
}

#: Installed digest checks done in this process, keyed by (install directory, manifest signature).
_verified: set[tuple[str, str]] = set()
#: The upstream listing, keyed by (project root, stamp). `_expected` hashes 18 MB; that is worth doing once.
_expected_cache: dict[tuple[str, tuple], dict] = {}


def root() -> Path:
    """Where the set is installed: the workspace's `martini3/`, unless a caller points it elsewhere."""
    override = os.environ.get(ENVIRONMENT_VARIABLE)
    return Path(override).expanduser() if override else paths.current().martini3


def relative(name: str) -> str:
    """The installed file's workspace-relative spelling, for an input record."""
    return f'{DIRECTORY}/{name}'


def names(project_root=None) -> tuple[str, ...]:
    """Every file of the official set, from the upstream tree: the lipidome's ITPs and the sugar reference."""
    itps = Path(project_root or paths.current().project_root) / UPSTREAM_ITPS
    if not itps.is_dir():
        raise ValueError(f'the Martini 3 upstream is missing: {itps}')
    found = tuple(sorted(path.name for path in itps.glob('*.itp') if path.is_file() and not path.is_symlink()))
    if not found:
        raise ValueError(f'the Martini 3 upstream holds no topology: {itps}')
    return found + tuple(sorted(UPSTREAM_EXTRA))


def path(name: str, *, installation=None, project_root=None) -> Path:
    """One installed file, installing the set first when this workspace has none."""
    return ensure(installation=installation, project_root=project_root) / _checked(name, project_root)


def include(name: str, start, *, installation=None, project_root=None) -> str:
    """How a topology written in `start` names one installed file: relative, so the run stays relocatable."""
    target = path(name, installation=installation, project_root=project_root)
    return Path(os.path.relpath(target, Path(start))).as_posix()


def ensure(*, installation=None, project_root=None, refresh: bool = False) -> Path:
    """Install the set if this workspace has none, and prove the one it has; return its directory.

    A digest that disagrees with `martini3.json`, or an upstream set that no longer matches what was installed,
    refuses -- it never replaces a run's bytes. `refresh` reinstalls from upstream, which is the explicit act of
    accepting new ones.
    """
    target = Path(installation) if installation is not None else root()
    expected = _expected(project_root)
    signature = files.json_sha256({'source': SOURCE, 'files': expected})
    cached = (str(target), signature)
    if cached in _verified:
        # The digests were checked once in this process; a file that has gone missing since still has to be noticed,
        # because a reader would otherwise open nothing. Editing an installed file is caught by the run's own
        # `inputs.json` verification before every stage, and by `ensure` in any process that has not verified yet.
        _verify_present(target, expected)
        return target
    target.mkdir(parents=True, exist_ok=True)
    with _locked(target):
        manifest_path = target / MANIFEST_NAME
        recorded = json.loads(manifest_path.read_text()) if manifest_path.is_file() else None
        if recorded is None or refresh:
            _install(target, expected, project_root)
            files.atomic_json(manifest_path, {'source': SOURCE, 'files': expected,
                                              'installed_at': files.now_iso()})
        elif recorded.get('files') != expected:
            _refuse_divergence(target, recorded.get('files') or {}, expected)
        else:
            _verify_installed(target, expected)
    _verified.add(cached)
    return target


def _checked(name: str, project_root=None) -> str:
    name = str(name)
    if name not in names(project_root):
        raise ValueError(f'{name!r} is not a file of the installed Martini 3 set')
    return name


def _upstream_file(name: str, project_root=None) -> Path:
    base = Path(project_root or paths.current().project_root)
    source = base / UPSTREAM_EXTRA[name] if name in UPSTREAM_EXTRA else base / UPSTREAM_ITPS / name
    if not source.is_file():
        raise ValueError(f'the Martini 3 upstream file is missing: {source}')
    return source


def _expected(project_root=None) -> dict:
    """Upstream identity of every file of the set: `{name: {sha256, bytes, source}}`, hashed once per stamp."""
    base = Path(project_root or paths.current().project_root)
    stamp = tuple((name, *_stat(_upstream_file(name, project_root)))
                  for name in names(project_root))
    key = (str(base), stamp)
    cached = _expected_cache.get(key)
    if cached is None:
        cached = {}
        for name in names(project_root):
            source = _upstream_file(name, project_root)
            cached[name] = {'sha256': files.sha256(source), 'bytes': source.stat().st_size,
                            'source': _relative(source, base)}
        _expected_cache.clear()
        _expected_cache[key] = cached
    return cached


def _stat(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


@contextmanager
def _locked(target: Path):
    with (target / '.install.lock').open('w') as handle:
        fcntl.lockf(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.lockf(handle, fcntl.LOCK_UN)


def _install(target: Path, expected: dict, project_root=None) -> None:
    for name in expected:
        destination = target / name
        temporary = destination.with_name(f'.{name}.{os.getpid()}.tmp')
        shutil.copyfile(_upstream_file(name, project_root), temporary)
        os.replace(temporary, destination)


def _verify_installed(target: Path, expected: dict) -> None:
    _verify_present(target, expected)
    for name, record in expected.items():
        destination = target / name
        if files.sha256(destination) != record['sha256']:
            raise ValueError(f'the installed Martini 3 file changed since it was installed: {destination}')


def _verify_present(target: Path, expected: dict) -> None:
    for name in expected:
        if not (target / name).is_file():
            raise ValueError(f'the installed Martini 3 set is missing {target / name}')


def _refuse_divergence(target: Path, recorded: dict, expected: dict) -> None:
    changed = sorted(name for name in set(recorded) | set(expected)
                     if (recorded.get(name) or {}).get('sha256') != (expected.get(name) or {}).get('sha256'))
    raise ValueError(
        f'the Martini 3 upstream no longer matches the set installed at {target} '
        f'({", ".join(changed) or "unknown difference"}); reinstall deliberately with '
        f'martini3.ensure(refresh=True) or by removing {target}')
