"""The protein-detergent complex pipeline. `micelle/` owns the science; this adapter owns the stages.

Only the catalogue and the stage contract live here so far: the placement, sampling, assessment and back-mapping
stages arrive with the phases that implement them, and every one of them belongs to this module rather than to the
route layer.
"""
import json
import sys
from pathlib import Path

from ... import files
from .. import protocol, tools
from ..stages import Stage

# The two files the system-preparation stage reads and writes. The adapter owns their names because the stage
# script, the entry point and the tests all have to agree on them.
SETTINGS_NAME = 'pdc-settings.json'
REPORT_NAME = 'prepare_report.json'

DEFAULTS = {'salt_molar': 0.15, 'aggregation_number': 12, 'assessment_ns': 100, 'extension_ns': 900,
            'selection_threshold_fraction': 0.10, 'attempts_max': 3, 'box_margin_nm': 2.0,
            'initial_z_nm': 6.0, 'contact_nm': 0.6}
_PROTEIN_LIMIT = 50

# One shape across every run type: (label, lo, hi). Numbers only; a choice would need the registry, so it is
# validated in validate_payload where the templates are actually known.
SETTING_SPECS = {
    'pdc_assessment_ns': ('CG assessment duration (ns)', 1, 100000),
    'pdc_extension_ns': ('CG extension duration (ns)', 1, 1000000),
    'pdc_seed': ('Random seed', 1, 2147483646),
    'aggregation_number': ('Detergent aggregation number', 1, 1000),
    'salt_molar': ('Salt concentration (M)', 0.0, 5.0),
    'box_margin_nm': ('Box margin (nm)', 0.5, 10.0),
    'initial_z_nm': ('Initial z box (nm)', 1.0, 50.0),
    'contact_nm': ('Micelle contact distance (nm)', 0.1, 2.0),
    'selection_threshold_fraction': ('Removal threshold (fraction)', 0.0, 1.0),
}

# The protocol's own steps, named as stages so the executor, the manifest and the panel all speak the same words.
STAGES = (
    Stage('System preparation', '1_system/prepare_system.sh',
          ('protein.pdb', 'system_EMPTY.top', 'detergent.itp'),
          ('system.gro', 'system.top', 'prepare_report.json')),
    Stage('CG assessment MD', '2_assessment/assessment.sh',
          ('../1_system/system.gro', '../1_system/system.top', 'assessment.mdp'),
          ('prod/run.gro', 'prod/run.tpr', 'prod/run.xtc', 'prod/run.cpt')),
    Stage('Micelle assessment', '3_assessment/assess.sh',
          ('../2_assessment/prod/run.gro', '../2_assessment/prod/run.xtc', 'system.top'),
          ('assessment.json', 'kept.gro', 'removed.json')),
    Stage('CG extension MD', '4_extension/extension.sh',
          ('../2_assessment/prod/run.tpr', '../2_assessment/prod/run.cpt', 'extension.mdp'),
          ('prod/run.gro', 'prod/run.xtc')),
    Stage('Final assessment', '5_assessment/assess.sh',
          ('../4_extension/prod/run.gro', '../4_extension/prod/run.xtc', 'system.top'),
          ('assessment.json',)),
    Stage('Back-mapping (CG2AT2)', '6_backmap/backmap.sh',
          ('../4_extension/prod/run.gro', 'protein.pdb', 'cg2at_input.pdb'),
          ('FINAL/final_cg2at_aligned.pdb', 'backmap.log')),
)


def validate_payload(payload):
    """The choices a build must carry, checked where the protocol can see them.

    Numbers that also appear in SETTING_SPECS are range-checked there; this validates what they mean: a seed that
    is a positive integer rather than a float, and an aggregation number that is a count rather than a size.
    """
    if not isinstance(payload, dict):
        raise ValueError('pdc payload must be an object')
    # The builder's own policy: every build requires an integer seed, so a missing one is an error rather than a
    # default that would make two builds look comparable when they are not.
    seed = payload.get('seed')
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 1:
        raise ValueError('pdc seed must be a positive integer')
    aggregation = payload.get('aggregation_number', DEFAULTS['aggregation_number'])
    if not isinstance(aggregation, int) or isinstance(aggregation, bool) or aggregation < 1:
        raise ValueError('pdc aggregation number must be a positive integer')
    try:
        salt = float(payload.get('salt_molar', DEFAULTS['salt_molar']))
    except (TypeError, ValueError) as exc:
        raise ValueError('pdc salt concentration must be a number') from exc
    if salt < 0:
        raise ValueError('pdc salt concentration cannot be negative')
    return {'seed': seed, 'aggregation_number': aggregation, 'salt_molar': salt,
            'template': payload.get('template'), 'protein': payload.get('protein') or None}


def catalog(project_root):
    """What this workflow can build, from the files on disk.

    A template is listed with the state of the files it names, because the shipped DDM template is a skeleton --
    its bead type is `registered-template` and its headgroup is zeroed -- and a panel that offered it without
    saying so would be promising a fitted detergent model that does not exist yet.
    """
    root = Path(project_root)
    return {'templates': _templates(root), 'proteins': _proteins(root), 'defaults': dict(DEFAULTS)}


def _templates(root):
    templates = []
    for path in sorted(root.glob('molecules/*/micelle_template.json')):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        molecule = path.parent.name
        missing = [name for name in ('coordinates', 'topology')
                   if not (path.parent / str(record.get(name, ''))).is_file()]
        beads = record.get('beads') or [{}]
        templates.append({'id': f'{molecule}:{record.get("residue") or molecule}',
                          'name': record.get('name') or molecule,
                          'residue': record.get('residue') or molecule,
                          'molecule': molecule,
                          'template': str(path.relative_to(root)),
                          'registered_type': str(beads[0].get('type') or ''),
                          'files_present': not missing,
                          'missing_files': missing,
                          'limitations': (['the template names files that are missing: ' + ', '.join(missing)]
                                          if missing else
                                          ['skeleton placeholder template, not a fitted detergent model'])})
    return templates


def _proteins(root):
    """Protein inputs the repository actually holds, so a build can name one rather than guess a path.

    Scoped to the packaged molecule directories and capped: the references tree is large, and an endpoint that
    walks it would be slow for a list nobody asked to see in full.
    """
    proteins = []
    for path in sorted(root.glob('molecules/*/*.pdb')):
        if len(proteins) >= _PROTEIN_LIMIT:
            break
        proteins.append({'id': str(path.relative_to(root)), 'name': path.stem,
                         'path': str(path.relative_to(root))})
    return proteins


# The panel sends its own field names (`pdc_seed`), the adapter's settings use the builders' (`seed`); one small
# map keeps that translation out of the dispatch.
_ALIASES = {'pdc_seed': 'seed', 'pdc_assessment_ns': 'assessment_ns', 'pdc_extension_ns': 'extension_ns'}

_STAGE_SCRIPT = """#!/bin/sh
# {label} for a protein-detergent complex run.
#
# Generated by the pdc adapter, which owns the numbers below; the work is the entry point's, and it applies the
# tested builders (pdc_box, pdc_placement, pdc_protein) rather than a private copy of their rules.
#
# Exit 0 built. Exit 2 a gate refused and {report} says which. Exit 3 a step whose rules do not exist yet.
set -eu

cd "$(dirname "$0")"
PYTHONPATH={root}${{PYTHONPATH:+:$PYTHONPATH}} {python} -m dashboard.execution.scripts.pdc_build --stage .
"""

_UNWRITTEN_SCRIPT = """#!/bin/sh
# {label}: the stage script is not written yet.
#
# The adapter already declares this stage and the inputs and outputs it must produce; the script that produces
# them is task B7b in docs/superpowers/plans/2026-09-28-protein-detergent-complex-panel.md. Exiting 3 here stops a
# run at this stage with this reason instead of failing somewhere further downstream.
set -eu
echo "{label}: the stage script is not written yet (task B7b)" >&2
exit 3
"""


def settings_from(payload: dict) -> dict:
    """A build's numbers: the adapter's defaults, then whatever the caller supplied under either spelling."""
    numbers = dict(DEFAULTS)
    for key, value in (payload or {}).items():
        if key in SETTING_SPECS or key in _ALIASES or key in numbers:
            numbers[_ALIASES.get(key) or key] = value
    return numbers


def _empty_topology() -> str:
    """The pre-detergent topology the stage starts from.

    The includes and the `[ molecules ]` names belong to the two `.itp` files, and the protein's own only exists
    after martinize2 has run and named it, so they are written by the stage rather than guessed here.
    """
    return ('; the system before the detergent arrives, written by the pdc adapter\n'
            '; the includes and the [ molecules ] names are written by the system-preparation stage, which is the\n'
            '; first thing that can read them (see pdc_build.py)\n\n'
            '[ system ]\n'
            'protein-detergent complex, CG protein\n\n'
            '[ molecules ]\n')


def prepare(run_dir, *, protein=None, template=None, settings=None, project_root=None, **kwargs):
    """Write the six stage directories and everything the system-preparation stage needs to start.

    `protein` and `template` are paths relative to `project_root` -- the spelling `catalog` reports, so the panel's
    own choice can be handed straight in. The template is loaded through its own reader, which is the one place
    that says whether it can build a system at all; the answer is recorded and the stage refuses with it, rather
    than being resolved by a second opinion here.
    """
    if not protein or not template:
        raise ValueError('a pdc build needs a protein and a detergent template')
    # The panel's spelling is translated before validation, because `validate_payload` reads the builders' names
    # and would otherwise see a missing seed where the caller sent one.
    supplied = {_ALIASES.get(key) or key: value
                for key, value in {**(settings or {}), **kwargs}.items()}
    choices = validate_payload({'protein': protein, 'template': template, **supplied})
    numbers = settings_from(supplied)
    from .pdc_placement import DEFAULT_RADIUS_NM
    numbers.update({'seed': choices['seed'], 'aggregation_number': choices['aggregation_number'],
                    'salt_molar': choices['salt_molar'],
                    'radius_nm': numbers.get('radius_nm') or round(float(DEFAULT_RADIUS_NM), 6)})

    run_dir = Path(run_dir)
    root = Path(project_root or Path.cwd()).resolve()
    protein_path, template_path = root / str(protein), root / str(template)
    for label, path in (('protein', protein_path), ('template', template_path)):
        if not path.is_file():
            raise ValueError(f'the pdc {label} is not a file: {path}')

    from micelle import registry
    record = registry.load_template(template_path)
    template_issues = list(registry.validate_template(record))

    # Every stage directory the contract names, so the run's plan and the executor's expectations agree before
    # anything runs; only the first stage's script is written, and the others say so instead of failing obscurely.
    for stage in STAGES:
        directory = run_dir / Path(stage.relative).parent
        directory.mkdir(parents=True, exist_ok=True)
        if stage is not STAGES[0]:
            (directory / Path(stage.relative).name).write_text(
                _UNWRITTEN_SCRIPT.format(label=stage.name))

    system = run_dir / Path(STAGES[0].relative).parent
    (system / 'protein.pdb').write_bytes(protein_path.read_bytes())
    (system / Path(STAGES[0].inputs[2]).name).write_bytes((template_path.parent / record.topology).read_bytes())
    (system / Path(STAGES[0].inputs[1]).name).write_text(_empty_topology())
    (system / SETTINGS_NAME).write_text(json.dumps(
        {'project_root': str(root), 'protein': str(protein), 'template': str(template), **numbers},
        indent=2, sort_keys=True))
    (system / Path(STAGES[0].relative).name).write_text(_STAGE_SCRIPT.format(
        label=STAGES[0].name, report=REPORT_NAME, root=str(root), python=sys.executable))
    # One record, and it is the one the pipeline reads: `workflow.prepare_run` takes this manifest, adds the run's
    # snapshots and tools, and moves it to the run root. A tool that is not resolvable is recorded as unresolved
    # rather than raising here, because readiness is the layer that blocks a run for it.
    recorded_tools = {}
    for name in ('gmx', 'martinize2'):
        found = tools.tool_path(name)
        recorded_tools[name] = ({'path': found, 'sha256': files.sha256(found)} if found
                                else {'path': name, 'ready': False,
                                      'detail': 'not declared or not executable'})
    (run_dir / 'manifest.json').write_text(json.dumps(
        {'run_type': 'pdc', 'stage_plan': _plan(), 'settings': numbers,
         'protein': str(protein), 'template': str(template), 'template_issues': template_issues,
         'tools': recorded_tools,
         'limitations': ['the detergent is one centre per molecule: the shipped templates carry no bead shape',
                         'the assessment, removal, extension and back-mapping stage scripts are task B7b']},
        indent=2, sort_keys=True))


def _plan():
    """The six stages as `(name, relative)` pairs, the spelling a run's manifest records."""
    return [[stage.name, stage.relative] for stage in STAGES]


def stage_contract(metadata=None):
    """The contract in the shape the other run types publish: `(plan, inputs, outputs)`.

    The pdc stages are the same six for every payload -- nothing here is per molecule yet -- so the metadata is
    accepted and unused, rather than the caller having to know which run types need it.
    """
    return (_plan(),
            {stage.name: list(stage.inputs) for stage in STAGES},
            {stage.name: list(stage.outputs) for stage in STAGES})


def stages(metadata=None):
    """The stage records themselves, for a caller that wants more than the plan."""
    return tuple(STAGES)


def stage_defaults():
    return dict(DEFAULTS)


def normalize_settings(settings=None, profile='standard'):
    """The panel's payload in the builders' spelling. The profile has no pdc meaning yet and is not recorded."""
    return settings_from(settings or {})


def readiness(protein=None, template=None, project_root=None):
    """What a protein-detergent build needs, in the shape every run type answers with.

    The template is checked by its own reader and validator, because those are the two things that decide whether
    it can build a system at all; the executables are resolved through the declared tools, so a build that names a
    tool the machine does not have is blocked here rather than in the middle of a stage.
    """
    from micelle import registry

    from ..environment import probe_tool

    checks, blockers = [], []
    root = Path(project_root or Path.cwd())
    paths_named = {}
    for label, value in (('Protein', protein), ('Detergent template', template)):
        if not value:
            blockers.append(f'{label}: none selected')
            continue
        path = Path(value) if Path(value).is_absolute() else root / str(value)
        paths_named[label] = path
        found = path.is_file()
        checks.append({'label': label, 'path': str(value), 'ready': found,
                       'detail': 'found' if found else f'not a file: {path}'})
        if not found:
            blockers.append(f'{label}: not a file: {path}')

    template_path = paths_named.get('Detergent template')
    if template_path is not None and template_path.is_file():
        try:
            record = registry.load_template(template_path)
            issues = list(registry.validate_template(record))
            detail = '; '.join(issues) or 'coordinates and topology present'
        except (ValueError, OSError) as exc:
            issues, detail = [str(exc)], str(exc)
        checks.append({'label': 'Template files',
                       'path': f'{template_path.name}', 'ready': not issues, 'detail': detail})
        blockers.extend(issues)

    for name in ('gmx', 'martinize2'):
        executable = tools.tool_path(name)
        ok, detail = probe_tool(executable) if executable else (False, 'Executable not found')
        checks.append({'label': name, 'path': executable or name, 'ready': ok, 'detail': detail})
        if not ok:
            blockers.append(f'{name}: {detail}')
    return {'ready': not blockers, 'checks': checks, 'blockers': blockers}


def tool_metadata():
    """The tools a pdc run resolves and records: the executables its stages call."""
    result = {}
    for name in ('gmx', 'martinize2'):
        executable = tools.tool_path(name)
        if not executable:
            raise FileNotFoundError(f'Missing tool: {name}')
        result[name] = {'path': executable, 'sha256': files.sha256(executable)}
    return result


def _protocol_readiness(metadata):
    return readiness(protein=metadata.get('protein'), template=metadata.get('template'),
                     project_root=metadata.get('project_root'))


def _protocol_prepare(run_dir, metadata):
    keys = ('protein', 'template', 'settings', 'project_root')
    prepare(run_dir, **{key: metadata[key] for key in keys if key in metadata})


PROTOCOL = protocol.Protocol(
    name='pdc',
    stage_contract=stage_contract,
    stages=stages,
    settings_specs=lambda: SETTING_SPECS,
    stage_defaults=stage_defaults,
    normalize_settings=normalize_settings,
    readiness=_protocol_readiness,
    prepare=_protocol_prepare,
    tool_report=tool_metadata,
)
