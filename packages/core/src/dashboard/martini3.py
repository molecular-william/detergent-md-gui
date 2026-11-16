"""The installed Martini 3 force field: one copy that every run reads, by version.

`references/` is the vendored upstream -- the published lipidome, the sugar reference and their licences. This module
installs that set once under the workspace (`workspace/dashboard/martini3/<version>/`) and is the one place that
answers where a Martini file is, so no run copies one and no two readers can disagree about which bytes a run simulated
with.

Three properties are deliberate:

* **Installed, not read in place.** A run must not read the repository: the checkout is code, the workspace is data,
  and the workspace can sit anywhere (`config/dashboard-paths.json`, `DASHBOARD_WORKSPACE`, a test's `tmp_path`). The
  install is what makes the shared directory reachable by a relative path from every stage directory.
* **Append-only, and never silently different.** The set is installed at `martini3/<version>/` and `martini3.json` records
  its version, its upstream commit/doi and when it was installed. A version is never rewritten: a new publish is a
  new version directory. The version is the witness that replaced a per-file digest check -- a reader names the
  set it read, and `ensure` refuses a version that is missing or whose witness disagrees rather than answering
  with another one. A flat install from before versions (the files directly under `martini3/` with a digest
  manifest) is read as version `legacy` and keeps its own claim: each file is still measured against the digests it
  recorded.
* **Cheap after the first check.** The legacy digest pass costs 18 MB; it is cached per process against its own
  stamp. A versioned install is proved by its witness and the presence of the files it names, so a run costs a
  JSON read, not a hash of every ITP.

The relative include is the reason this module exists at all: GROMACS resolves `#include` from the working directory,
so a topology names the shared file by a path computed from where the topology will be read (`include`).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from . import files, paths

#: The directory under the workspace that every run reads the force field from.
DIRECTORY = 'martini3'
#: The install's own record, inside its version directory.
MANIFEST_NAME = 'martini3.json'
#: Points the install somewhere else than the workspace. Symmetric with `DASHBOARD_WORKSPACE`; the test suite uses it
#: to install once per session instead of once per temporary workspace.
ENVIRONMENT_VARIABLE = 'DASHBOARD_MARTINI3'

#: The version a flat install from before version directories is read as.
LEGACY_VERSION = 'legacy'

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

#: The version this code installs: the published set above, named so a newer upstream is a new directory rather than a
#: silent rewrite of the bytes a run already simulated with.
VERSION = f'v3.0.0-{SOURCE["commit"]}'

#: Legacy digest checks done in this process, keyed by (install directory, manifest signature).
_verified: set[tuple[str, str]] = set()
#: The upstream listing, keyed by (project root, stamp). `_expected` hashes 18 MB; that is worth doing once.
_expected_cache: dict[tuple[str, tuple], dict] = {}


def root() -> Path:
    """Where the set is installed: the workspace's `martini3/`, unless a caller points it elsewhere."""
    override = os.environ.get(ENVIRONMENT_VARIABLE)
    return Path(override).expanduser() if override else paths.current().martini3


def _version_key(version: str):
    if version == LEGACY_VERSION:
        return ()
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r'(\d+)', str(version)) if part)


def _witness(path: Path):
    """The manifest inside one directory, or None when it holds none or an unreadable one."""
    try:
        record = json.loads((Path(path) / MANIFEST_NAME).read_text())
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _installed(base: Path) -> dict[str, Path]:
    """The versions installed under a base: versioned directories by their witness, and a flat install as `legacy`."""
    base = Path(base)
    found: dict[str, Path] = {}
    if base.is_dir():
        for path in sorted(base.iterdir()):
            if path.is_symlink() or not path.is_dir():
                continue
            record = _witness(path)
            version = (record or {}).get('version')
            if not isinstance(version, str):
                continue
            if version != path.name:
                raise ValueError(f'the Martini 3 install at {path} states version {version!r}, not its directory name')
            found[version] = path
    if (base / MANIFEST_NAME).is_file():
        found.setdefault(LEGACY_VERSION, base)
    return found


def versions(*, installation=None) -> tuple[str, ...]:
    """The versions installed under the base, oldest first."""
    base = Path(installation) if installation is not None else root()
    return tuple(sorted(_installed(base), key=_version_key))


def resolve(*, installation=None, version=None) -> Path:
    """The installed version a reader should use: the one named, or the newest; nothing is installed here."""
    base = Path(installation) if installation is not None else root()
    installed = _installed(base)
    if version is not None:
        target = installed.get(str(version))
        if target is None:
            known = ', '.join(sorted(installed, key=_version_key)) or 'none'
            raise ValueError(f'the Martini 3 set installed at {base} has no version {version!r} '
                             f'(installed: {known})')
        _prove(target, str(version))
        return target
    if not installed:
        raise ValueError(f'the Martini 3 set is not installed at {base}')
    newest = max(installed, key=_version_key)
    _prove(installed[newest], newest)
    return installed[newest]


def relative(name: str, *, installation=None, project_root=None, version=None) -> str:
    """The installed file's workspace-relative spelling, for an input record."""
    target = path(name, installation=installation, project_root=project_root, version=version)
    base = Path(installation) if installation is not None else root()
    try:
        return f'{DIRECTORY}/{target.relative_to(base).as_posix()}'
    except ValueError:
        return target.as_posix()


def names(project_root=None) -> tuple[str, ...]:
    """Every file of the official set, from the upstream tree: the lipidome's ITPs and the sugar reference."""
    itps = Path(project_root or paths.current().project_root) / UPSTREAM_ITPS
    if not itps.is_dir():
        raise ValueError(f'the Martini 3 upstream is missing: {itps}')
    found = tuple(sorted(path.name for path in itps.glob('*.itp') if path.is_file() and not path.is_symlink()))
    if not found:
        raise ValueError(f'the Martini 3 upstream holds no topology: {itps}')
    return found + tuple(sorted(UPSTREAM_EXTRA))


def path(name: str, *, installation=None, project_root=None, version=None) -> Path:
    """One installed file, installing the set first when this workspace has none."""
    return ensure(installation=installation, project_root=project_root, version=version) / _checked(name, project_root)


def include(name: str, start, *, installation=None, project_root=None, version=None) -> str:
    """How a topology written in `start` names one installed file: relative, so the run stays relocatable."""
    target = path(name, installation=installation, project_root=project_root, version=version)
    return Path(os.path.relpath(target, Path(start))).as_posix()


def system_topology(directory, itp, residue, title, *, force_field, solvents) -> str:
    """The system_EMPTY.top a CG run writes: the two installed Martini ITPs, the model, and one molecule."""
    return (f'#include "{include(force_field, directory)}"\n'
            f'#include "{include(solvents, directory)}"\n'
            f'#include "{itp}"\n'
            f'[ system ]\n{title}\n'
            f'[ molecules ]\n{residue} 1\n')


def ensure(*, installation=None, project_root=None, refresh: bool = False, version=None) -> Path:
    """Install the set if this workspace has none, prove the one it has, and return its directory.

    A version is append-only: an installed one is never rewritten, so `refresh` installs the version this code
    names when it is absent and cannot adopt new upstream bytes under an old name. A named version that is not
    installed, or whose witness disagrees, is refused; another version is never served in its place.
    """
    base = Path(installation) if installation is not None else root()
    if version is not None:
        return resolve(installation=base, version=version)
    installed = _installed(base)
    if VERSION in installed:
        _prove(installed[VERSION], VERSION)
        return installed[VERSION]
    if LEGACY_VERSION in installed and installed == {LEGACY_VERSION: base}:
        # The flat install is the set this workspace has: it keeps its own digest claim and is never replaced by
        # another version behind the caller's back.
        return _legacy_ensure(base, project_root, refresh)
    if installed:
        known = ', '.join(sorted(installed, key=_version_key))
        raise ValueError(f'the Martini 3 set installed at {base} has no version {VERSION!r} (installed: {known}); '
                         'install it deliberately')
    return _install_version(base, VERSION, project_root)


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
def _locked(base: Path):
    with (Path(base) / '.install.lock').open('w') as handle:
        fcntl.lockf(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.lockf(handle, fcntl.LOCK_UN)


def _install(base: Path, expected: dict, project_root=None) -> None:
    for name in expected:
        destination = Path(base) / name
        temporary = destination.with_name(f'.{name}.{os.getpid()}.tmp')
        shutil.copyfile(_upstream_file(name, project_root), temporary)
        os.replace(temporary, destination)


def _install_version(base: Path, version: str, project_root=None) -> Path:
    """Install one version directory from upstream; its witness is written last, so a crash leaves no version."""
    base = Path(base)
    files_of_set = names(project_root)
    target = base / version
    if target.is_symlink():
        raise ValueError(f'the Martini 3 install at {target} is a symlink')
    base.mkdir(parents=True, exist_ok=True)
    with _locked(base):
        if _witness(target) is not None:
            _prove(target, version)
            return target
        target.mkdir(exist_ok=True)
        for name in files_of_set:
            destination = target / name
            temporary = destination.with_name(f'.{name}.{os.getpid()}.tmp')
            shutil.copyfile(_upstream_file(name, project_root), temporary)
            os.replace(temporary, destination)
        files.atomic_json(target / MANIFEST_NAME, {'version': version, 'source': SOURCE,
                                                   'files': list(files_of_set),
                                                   'installed_at': files.now_iso()})
    return target


def _legacy_ensure(base: Path, project_root=None, refresh: bool = False) -> Path:
    """The flat install, verified exactly as it was: its own digest manifest against the upstream set."""
    base = Path(base)
    expected = _expected(project_root)
    signature = files.json_sha256({'source': SOURCE, 'files': expected})
    cached = (str(base), signature)
    if cached in _verified:
        # The digests were checked once in this process; a file that has gone missing since still has to be noticed,
        # because a reader would otherwise open nothing.
        _verify_present(base, expected)
        return base
    with _locked(base):
        recorded = json.loads((base / MANIFEST_NAME).read_text())
        if refresh:
            _install(base, expected, project_root)
            files.atomic_json(base / MANIFEST_NAME, {'source': SOURCE, 'files': expected,
                                                     'installed_at': files.now_iso()})
        elif recorded.get('files') != expected:
            _refuse_divergence(base, recorded.get('files') or {}, expected)
        else:
            _verify_installed(base, expected)
    _verified.add(cached)
    return base


def _prove(target: Path, version: str) -> None:
    """Refuse an install whose witness is missing or names another version/upstream, or whose files are gone."""
    target = Path(target)
    record = _witness(target)
    if record is None:
        raise ValueError(f'the Martini 3 install at {target} has no {MANIFEST_NAME} witness')
    if version == LEGACY_VERSION:
        recorded = record.get('files')
        if not isinstance(recorded, dict) or not recorded:
            raise ValueError(f'the Martini 3 install at {target} records no files to verify')
        for name, entry in recorded.items():
            installed = target / str(name)
            if not installed.is_file():
                raise ValueError(f'the installed Martini 3 set is missing {installed}')
            if files.sha256(installed) != (entry or {}).get('sha256'):
                raise ValueError(f'the installed Martini 3 file changed since it was installed: {installed}')
        return
    if record.get('version') != version:
        raise ValueError(f'the Martini 3 install at {target} states version {record.get("version")!r}, '
                         f'not {version!r}')
    if record.get('source') != SOURCE:
        raise ValueError(f'the Martini 3 install at {target} was installed from a different upstream')
    recorded = record.get('files')
    if not isinstance(recorded, list) or not recorded:
        raise ValueError(f'the Martini 3 install at {target} names no files in its witness')
    missing = [str(name) for name in recorded if not (target / str(name)).is_file()]
    if missing:
        raise ValueError(f'the installed Martini 3 set is missing {", ".join(missing)} at {target}')


def _verify_installed(target: Path, expected: dict) -> None:
    _verify_present(target, expected)
    for name, record in expected.items():
        destination = Path(target) / name
        if files.sha256(destination) != record['sha256']:
            raise ValueError(f'the installed Martini 3 file changed since it was installed: {destination}')


def _verify_present(target: Path, expected: dict) -> None:
    for name in expected:
        if not (Path(target) / name).is_file():
            raise ValueError(f'the installed Martini 3 set is missing {Path(target) / name}')


def _refuse_divergence(target: Path, recorded: dict, expected: dict) -> None:
    changed = sorted(name for name in set(recorded) | set(expected)
                     if (recorded.get(name) or {}).get('sha256') != (expected.get(name) or {}).get('sha256'))
    raise ValueError(
        f'the Martini 3 upstream no longer matches the set installed at {target} '
        f'({", ".join(changed) or "unknown difference"}); reinstall deliberately with '
        f'martini3.ensure(refresh=True) or by removing {target}')
