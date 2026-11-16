"""The code a run executes, recorded by name and version.

A run used to hold a copy of every stage script. The copy made a run look self-contained, and it meant an old run
re-executed the code of its own day -- but the same helper also lived in the repository, so there were two copies to
fix and two answers to "what ran".

This module records the repository file instead: `{name, version}` per stage, from the registry below, written into
the manifest at prepare time. The executor runs the repository file with the stage directory as the working directory,
and checks the recorded name still resolves and still carries the recorded version before the stage starts. A changed
version refuses the stage by name, which is the honest answer: the run can no longer claim to be running the code it
recorded. A manifest written before this record carries a `{path, sha256}` pair instead, and that one is still
verified by digest -- an old run keeps its own claim.
"""
from __future__ import annotations

import importlib
from pathlib import Path

from .. import files, paths

#: A run records the code it executes by repository path, spelled `dashboard/<rest>` since before the package moved
#: to `packages/core/src/dashboard`. The spelling stays the record's -- an installed distribution has no checkout to
#: name -- and the path is resolved against the package here, once, instead of in every adapter.
_DECLARED_PREFIX = 'dashboard/'

#: `(recorded prefix, distribution, prefix inside that package)` for code a feature took over. A prepared run records
#: the spelling of its day; the file is looked for where its distribution keeps it now. Nothing rewrites a manifest --
#: the recorded name is what resolves, wherever the file moved.
_FEATURE_PREFIXES: list[tuple[str, str, str]] = []

#: One entry per file a stage executes or imports, by the name the record carries. A version changes when the file's
#: behaviour changes, and that is what refuses a not-yet-run stage: there is no digest to re-measure. The name is
#: human-readable and unique; `path` is the declared repository spelling the resolver already understands.
CODE_VERSIONS: dict[str, dict] = {
    'aa_reference': {'path': 'dashboard/execution/scripts/aa_reference.sh', 'version': 1},
    'map_trajectory': {'path': 'dashboard/execution/scripts/map_trajectory.sh', 'version': 1},
    'fit_topology': {'path': 'dashboard/execution/scripts/fit_topology.sh', 'version': 1},
    'cg_simulation': {'path': 'dashboard/execution/scripts/cg_simulation.sh', 'version': 1},
    'use_parameterization': {'path': 'dashboard/execution/scripts/use_parameterization.sh', 'version': 1},
    'stage_coordinates': {'path': 'dashboard/execution/scripts/stage_coordinates.sh', 'version': 1},
    'assess': {'path': 'dashboard/execution/scripts/assess.sh', 'version': 1},
    'sasa': {'path': 'dashboard/execution/scripts/sasa.sh', 'version': 1},
    'composition_assessment': {'path': 'dashboard/execution/scripts/composition_assessment.sh', 'version': 1},
    'sugar_cg_simulation': {'path': 'dashboard/execution/scripts/sugar_cg_simulation.sh', 'version': 1},
    'osmotic_simulation': {'path': 'dashboard/execution/scripts/osmotic_simulation.sh', 'version': 1},
    'pdc_prepare': {'path': 'dashboard/execution/scripts/pdc_prepare.sh', 'version': 1},
    'pdc_system': {'path': 'dashboard/execution/scripts/pdc_system.sh', 'version': 1},
    'pdc_leg': {'path': 'dashboard/execution/scripts/pdc_leg.sh', 'version': 1},
    'pdc_assessment': {'path': 'dashboard/execution/scripts/pdc_assessment.sh', 'version': 1},
    'pdc_assess': {'path': 'dashboard/execution/scripts/pdc_assess.sh', 'version': 1},
    'pdc_extension': {'path': 'dashboard/execution/scripts/pdc_extension.sh', 'version': 1},
    'pdc_backmap': {'path': 'dashboard/execution/scripts/pdc_backmap.sh', 'version': 1},
    'references': {'path': 'dashboard/analysis/runs/references.py', 'version': 1},
    'molecules_aa': {'path': 'dashboard/models/molecules/aa.py', 'version': 1},
    'files': {'path': 'dashboard/files.py', 'version': 1},
    'sugar_mapping': {'path': 'dashboard/execution/scripts/sugar_mapping.py', 'version': 1},
    'refine_bonded': {'path': 'dashboard/execution/scripts/refine_bonded.py', 'version': 1},
    'prepare_ring_constraints': {'path': 'dashboard/execution/scripts/prepare_ring_constraints.py', 'version': 1},
    'use_parameterization_module': {'path': 'dashboard/execution/scripts/use_parameterization.py', 'version': 1},
    'validate_run': {'path': 'dashboard/execution/scripts/validate_run.py', 'version': 1},
    'distance_diagnostics': {'path': 'dashboard/execution/scripts/distance_diagnostics.py', 'version': 1},
    'bonded_models': {'path': 'dashboard/models/bonded/__init__.py', 'version': 1},
    'osmotic_adapter': {'path': 'dashboard/execution/adapters/osmotic.py', 'version': 1},
    'osmotic_mdp': {'path': 'dashboard/execution/adapters/osmotic_mdp.py', 'version': 1},
    'execution_tools': {'path': 'dashboard/execution/tools.py', 'version': 1},
}


def register_prefixes(entries) -> None:
    """Let a feature answer for recorded paths whose files now live in its distribution."""
    for recorded, distribution, inside in entries:
        _FEATURE_PREFIXES.append((recorded, distribution, inside))


def _feature_file(text):
    """The file a moved recorded path names, or None when no registered feature holds it."""
    from .. import features
    features.ensure()
    for recorded, distribution, inside in _FEATURE_PREFIXES:
        if not text.startswith(recorded):
            continue
        package = importlib.import_module(distribution)
        candidate = Path(package.__file__).resolve().parent / inside / text[len(recorded):]
        if candidate.is_file():
            return candidate
    return None


def code_path(declared, *, root):
    """The file a recorded code path names: in this package, in a feature that moved it, or under the data root."""
    text = str(declared)
    moved = _feature_file(text)
    if moved is not None:
        return moved
    if text.startswith(_DECLARED_PREFIX):
        return paths.PACKAGE_ROOT / text[len(_DECLARED_PREFIX):]
    source = Path(text)
    return source if source.is_absolute() else Path(root) / source


def registry_entry(name):
    """The registry entry a recorded name resolves to, or a refusal naming the name."""
    entry = CODE_VERSIONS.get(name)
    if not isinstance(name, str) or entry is None:
        raise ValueError(f'no code version is registered for {name!r}')
    return entry


def _name_for_path(path):
    """The registry name of a declared repository path, refusing code nobody registered."""
    for name, entry in CODE_VERSIONS.items():
        if entry['path'] == path:
            return name
    raise ValueError(f'no code version is registered for {path}')


def record(scripts, *, root):
    """`{stage name: repository path}` -> the manifest's `stage_scripts` record, as `{name, version}`."""
    records = {}
    for name, path in scripts.items():
        source = code_path(path, root=root)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'stage script for {name} is not a regular file: {source}')
        text = str(path)
        if text.startswith(_DECLARED_PREFIX):
            # The declaration is the record's spelling; it names a file in this package, not in the checkout. Runs
            # prepared before the package moved recorded the same spelling, so their names still resolve.
            relative = text
        else:
            try:
                relative = source.resolve().relative_to(Path(root).resolve()).as_posix()
            except ValueError as exc:
                raise ValueError(f'stage script for {name} is outside the repository: {source}') from exc
        code = _name_for_path(relative)
        records[name] = {'name': code, 'version': int(CODE_VERSIONS[code]['version'])}
    return records


def recorded_path(declared, *, root):
    """The file a `{name, version}` record names. A legacy `{path, sha256}` record resolves its own path."""
    if 'sha256' in declared:
        return code_path(declared['path'], root=root)
    return code_path(registry_entry(declared.get('name'))['path'], root=root)


def verify_one(name, declared, *, root):
    """Check one recorded script or module, naming the stage and the file when it changed.

    A legacy record carries `path` and `sha256` and is re-hashed, exactly as before. A named record must resolve
    in the registry and the code must still be the version it recorded.
    """
    if 'sha256' in declared:
        path = code_path(declared['path'], root=root)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'the stage script for {name} is missing: {path}')
        measured = files.sha256(path)
        if measured != declared['sha256']:
            raise ValueError(f'the stage script for {name} changed since this run was prepared: {path} '
                             f'(recorded {declared["sha256"]}, found {measured})')
        return path
    entry = registry_entry(declared.get('name'))
    path = code_path(entry['path'], root=root)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'the stage script for {name} is missing: {path}')
    if int(entry['version']) != declared.get('version'):
        raise ValueError(f'the stage script for {name} changed since this run was prepared: {path} '
                         f'(recorded version {declared.get("version")}, code version {entry["version"]})')
    return path


def script_for(manifest, name, fallback, *, root):
    """The script a stage runs: the recorded repository file, or its own copy in a legacy run."""
    declared = (manifest.get('stage_scripts') or {}).get(name)
    if declared is None:
        return Path(fallback)
    return verify_one(name, declared, root=root)
