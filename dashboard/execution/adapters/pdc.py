"""The protein-detergent complex pipeline. `micelle/` owns the science; this adapter owns the stages.

Only the catalogue and the stage contract live here so far: the placement, sampling, assessment and back-mapping
stages arrive with the phases that implement them, and every one of them belongs to this module rather than to the
route layer.
"""
import json
import re
import shutil
import sys
from pathlib import Path

from ... import files
from .. import protocol, tools
from ..environment import ROOT, TUTORIAL_TEMPLATE
from ..stages import Stage

SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'
# The coarse-grained parameters a pdc topology has to carry, from the published Martini 3 lipid set: the bead types
# (which the detergent's own beads need defined), the solvents file that defines water as `W`, and the ions file that
# defines `NA` and `CL`. Without them `grompp` refuses a solvated system with an undefined molecule type -- which is
# exactly how the first run that reached solvation failed. The set is recorded by commit and DOI in every manifest.
FORCEFIELD_ROOT = ROOT / 'references' / 'M3-Lipid-Parameters' / 'ITPs'
FORCEFIELD_FILES = ('martini_v3.0.0.itp', 'martini_v3.0.0_solvents_v1.itp', 'martini_v3.0.0_ions_v1.itp')
FORCEFIELD_SOURCE = {
    'repository': 'https://github.com/Martini-Force-Field-Initiative/M3-Lipid-Parameters.git',
    'commit': '2121527',
    'doi': '10.1021/acscentsci.5c00755',
    'citation': 'Pedersen et al., The Martini 3 Lipidome, ACS Central Science (2025)',
    'license': 'Apache-2.0',
}

# The two files the system-preparation stage reads and writes. The adapter owns their names because the stage
# script, the entry point and the tests all have to agree on them.
SETTINGS_NAME = 'pdc-settings.json'
REPORT_NAME = 'prepare_report.json'
# The detergent's derived coarse-grained model: the topology the system includes, and the bead geometry together
# with the provenance of its bonded terms.
DETERGENT_TOPOLOGY = 'detergent_CG.itp'
DETERGENT_GEOMETRY = 'detergent_CG.json'

DEFAULTS = {'salt_molar': 0.15, 'aggregation_number': 150, 'assessment_ns': 100, 'extension_ns': 900,
            'selection_threshold_fraction': 0.10, 'attempts_max': 3, 'box_margin_nm': 2.0,
            'initial_z_nm': 6.0, 'contact_nm': 0.6, 'snapshot_interval_ns': 20.0, 'snapshot_cap': 20}
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
    'snapshot_interval_ns': ('Snapshot interval (ns)', 0.1, 1000.0),
    'snapshot_cap': ('Snapshots per stage (cap)', 1, 200),
}

# The protocol's own steps, named as stages so the executor, the manifest and the panel all speak the same words.
STAGES = (
    Stage('System preparation', '1_system/prepare_system.sh',
          ('protein.pdb', 'system_EMPTY.top', 'detergent.itp', *FORCEFIELD_FILES),
          ('system.gro', 'system.top', 'prepare_report.json')),
    Stage('CG assessment MD', '2_assessment/assessment.sh',
          ('../1_system/system.gro', '../1_system/system.top', '../1_system/' + DETERGENT_TOPOLOGY,
           *('../1_system/' + name for name in FORCEFIELD_FILES), 'assessment.mdp'),
          ('prod/run.gro', 'prod/run.tpr', 'prod/run.xtc', 'prod/run.cpt')),
    Stage('Micelle assessment', '3_assessment/assess.sh',
          ('../2_assessment/prod/run.gro', '../2_assessment/prod/run.xtc'),
          ('assessment.json', 'kept.gro', 'removed.json')),
    Stage('CG extension MD', '4_extension/extension.sh',
          ('../2_assessment/prod/run.tpr', '../2_assessment/prod/run.cpt', '../2_assessment/system.top',
           '../1_system/' + DETERGENT_TOPOLOGY, *('../1_system/' + name for name in FORCEFIELD_FILES),
           'extension.mdp'),
          ('prod/run.gro', 'prod/run.xtc')),
    Stage('Final assessment', '5_assessment/assess.sh',
          ('../4_extension/prod/run.gro', '../4_extension/prod/run.xtc'),
          ('assessment.json',)),
    Stage('Back-mapping (CG2AT2)', '6_backmap/backmap.sh',
          ('../4_extension/prod/run.gro', '../1_system/protein.pdb'),
          ('cg2at_input.pdb', 'FINAL/final_cg2at_aligned.pdb', 'backmap.log')),
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

# `genion` fits ions to a topology and needs a tpr, not a trajectory: this is the shortest MDP that makes one, and
# it is written beside the stage so the solvation step cannot depend on a template that moved.
IONS_MDP = """\
; A topology fix-up run for genion: no dynamics, no output, just a tpr the ions can be fitted to.
integrator              = steep
nsteps                  = 0
cutoff-scheme           = Verlet
rlist                   = 1.1
coulombtype             = reaction-field
epsilon_r               = 15
"""


def _mdp_number(path, key: str) -> float:
    """A number from an MDP, so a requested duration can be turned into steps in the template's own units."""
    for raw in Path(path).read_text().splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line or '=' not in line:
            continue
        name, value = (part.strip() for part in line.split('=', 1))
        if name.lower().replace('_', '-') == key:
            try:
                return float(value.split()[0])
            except (ValueError, IndexError) as exc:
                raise ValueError(f'{path}: {key} is not a number: {value!r}') from exc
    raise ValueError(f'{path} does not set {key}')


def _extension_stage(run_dir: Path, settings: dict):
    """The extension phase's inputs: the same MDP as the assessment phase, continuing instead of starting.

    Velocities are not regenerated -- this phase continues the trajectory it was given -- and the duration is
    passed to the stage as picoseconds, which is what `convert-tpr -extend` takes.
    """
    from ..environment import update_mdp

    stage = run_dir / Path(STAGES[3].relative).parent
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_dir / Path(STAGES[1].relative).parent / 'assessment.mdp', stage / 'extension.mdp')
    update_mdp(stage / 'extension.mdp', {'gen-vel': 'no'})
    shutil.copy2(SCRIPTS / Path(STAGES[3].relative).name, stage / Path(STAGES[3].relative).name)
    # The removal path rebuilds the system from the kept coordinates, so this stage needs the same mdps and water the
    # assessment phase was prepared with, plus the two helpers that do it.
    for target, source in (('minimization.mdp', 'minimization.mdp'), ('equilibration.mdp', 'eq.mdp'),
                           ('inputs/water.gro', 'water.gro')):
        (stage / target).parent.mkdir(exist_ok=True)
        shutil.copy2(TUTORIAL_TEMPLATE / '4_CG_sim' / 'inputs' / source, stage / target)
    shutil.copy2(SCRIPTS / 'pdc_extension.py', stage / 'pdc_extension.py')
    shutil.copy2(SCRIPTS / 'pdc_solvate.py', stage / 'pdc_solvate.py')
    extension_ps = round(float(settings['extension_ns']) * 1000)
    (stage / 'extension.ps').write_text(f'{extension_ps}\n')
    return extension_ps


def _assessment_stage(run_dir: Path, settings: dict):
    """The assessment phase's inputs: the MDPs for the requested duration, the water, and the two helpers.

    The duration is converted into steps with the *template's* own `dt`, and the integration settings come from
    `cg.mdp_integration`, so the coarse-grained half of a solved CG run and this stage cannot disagree about the
    timestep. Its `aa_dir` argument cannot equal this stage -- a pdc run has no atomistic half -- so the
    coarse-grained branch is the one that applies.
    """
    from ..environment import update_mdp
    from . import cg as cg_adapter

    stage = run_dir / Path(STAGES[1].relative).parent
    stage.mkdir(parents=True, exist_ok=True)
    source_inputs = TUTORIAL_TEMPLATE / '4_CG_sim' / 'inputs'
    for target, source in (('minimization.mdp', 'minimization.mdp'), ('equilibration.mdp', 'eq.mdp'),
                           ('assessment.mdp', 'md.mdp'), ('inputs/water.gro', 'water.gro')):
        (stage / target).parent.mkdir(exist_ok=True)
        shutil.copy2(source_inputs / source, stage / target)
    steps = round(float(settings['assessment_ns']) * 1000 / _mdp_number(stage / 'assessment.mdp', 'dt'))
    update_mdp(stage / 'assessment.mdp', cg_adapter.mdp_integration(stage, stage / '1_AA-reference', steps))
    (stage / 'ions.mdp').write_text(IONS_MDP)
    shutil.copy2(SCRIPTS / Path(STAGES[1].relative).name, stage / Path(STAGES[1].relative).name)
    shutil.copy2(SCRIPTS / 'pdc_solvate.py', stage / 'pdc_solvate.py')
    return steps

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

# Which file in `scripts/` each stage's script comes from. Stage 1's is generated at prepare time, because it has
# to carry the interpreter and the project root the run was prepared with.
_STAGE_SOURCES = {
    '2_assessment/assessment.sh': 'assessment.sh',
    '3_assessment/assess.sh': 'pdc_assess.sh',
    '4_extension/extension.sh': 'extension.sh',
    '5_assessment/assess.sh': 'pdc_assess.sh',
    '6_backmap/backmap.sh': 'backmap.sh',
}


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


def _stage_declared_inputs(script, stage):
    """Copy the stage's declared inputs from the phase before it into its own directory.

    A stage's artefacts are immutable and the scripts are written against that: solvation edits the topology in place
    and an assessment reads the phase's trajectory, so both need a local copy. The copy is emitted from the stage's
    own declaration, which is the one place the contract is stated -- the alternative is what the first run did,
    where the script named `system.top` and nothing had ever put one there.
    """
    lines = []
    for entry in stage.inputs:
        source = str(entry)
        if not source.startswith('../'):
            continue
        target = re.sub(r'^(?:\.\./[^/]+/)+', '', source)
        parent = str(Path(target).parent)
        prefix = f'mkdir -p {parent} && ' if parent != '.' else ''
        lines.append(f'{prefix}cp -f {source} {target}')
    if not lines:
        return
    text = script.read_text()
    if lines[0] in text:
        return
    prelude = ('# The phase before this one stays immutable, so its declared inputs are copied in rather than\n'
               '# edited where they lie. Emitted from the stage declaration itself.\n' + '\n'.join(lines) + '\n')
    marker = '\nset -'
    if marker in text:
        head, _, tail = text.partition(marker)
        script.write_text(f'{head}\n{prelude}{marker}{tail}')
    else:
        script.write_text(prelude + text)


def _stamp_interpreter(script, root):
    """Point a copied stage script at the interpreter this application runs under, and at this repository.

    Two things the generated stage-1 script does and the scripts written by hand did not. `python` on PATH is a
    different interpreter, and the one carrying this repository is this one. And a stage script runs from its own
    directory, so the repository is not on the import path: stage 1 sets PYTHONPATH, and without it the first import
    of `dashboard` fails after the tools have been resolved and before anything is built.
    """
    text = script.read_text()
    if not text.startswith('#!'):
        return
    rewritten = re.sub(r'(?m)^(\s*)python(?=\s|$)', lambda match: f'{match.group(1)}{sys.executable}', text)
    if 'PYTHONPATH=' not in rewritten:
        rewritten = rewritten.replace('\nset -', f'\nexport PYTHONPATH={root}${{PYTHONPATH:+:$PYTHONPATH}}\nset -', 1)
    if rewritten != text:
        script.write_text(rewritten)


def prepare(run_dir, *, protein=None, template=None, settings=None, project_root=None, mapping=None, **kwargs):
    """Write the six stage directories and everything the system-preparation stage needs to start.

    `protein` and `template` are paths relative to `project_root` -- the spelling `catalog` reports, so the panel's
    own choice can be handed straight in. `mapping` is a saved CG mapping for the detergent: with it, the run's
    detergent is a real coarse-grained molecule (its topology derived from the mapping, its beads' centres computed
    from the atomistic structure); without it, the build records that it is centres-only and the stage stops where it
    always did, rather than pretending a dot is a molecule.

    A build with a template and no protein is the design spec's empty micelle: the protein stages are skipped, so an
    absence that is a choice is told apart from one that is an oversight -- an oversight has no template at all.
    """
    if not template:
        raise ValueError('a pdc build needs a detergent template')
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
    protein_path = (root / str(protein)) if protein else None
    template_path = root / str(template)
    if protein_path is not None and not protein_path.is_file():
        raise ValueError(f'the pdc protein is not a file: {protein_path}')
    if not template_path.is_file():
        raise ValueError(f'the pdc template is not a file: {template_path}')

    from micelle import registry
    record = registry.load_template(template_path)
    template_issues = list(registry.validate_template(record))
    # Which beads form the hydrophobic core is the template's to say (a bead role of "tail"), because only the
    # assignment knows it. A template that does not say is not refused here -- the criterion refuses when it has
    # nothing to judge, which is the stage that actually needs the answer.
    numbers['tail_beads'] = [str(bead.get('name')) for bead in record.beads
                             if str(bead.get('role') or '').lower() == 'tail']
    numbers['tail_beads_source'] = 'the template, from its bead roles'

    # Every stage directory the contract names, and every one gets its script. The map is explicit because two
    # stage file names are not the name of a file in `scripts/`: stage 1's script is generated below, and both
    # assessment stages run `pdc_assess.sh` (the legacy `assess.sh` belongs to the AA and CG run types).
    for stage in STAGES:
        directory = run_dir / Path(stage.relative).parent
        directory.mkdir(parents=True, exist_ok=True)
        source = _STAGE_SOURCES.get(stage.relative)
        if source:
            shutil.copy2(SCRIPTS / source, directory / Path(stage.relative).name)
    for stage in (STAGES[2], STAGES[4]):
        shutil.copy2(SCRIPTS / 'pdc_assess.py', run_dir / Path(stage.relative).parent / 'pdc_assess.py')
    # The frame sampler is copied beside every stage that has a trajectory to read.
    for stage in (STAGES[1], STAGES[2], STAGES[3], STAGES[4]):
        shutil.copy2(SCRIPTS / 'pdc_snapshot.py', run_dir / Path(stage.relative).parent / 'pdc_snapshot.py')

    system = run_dir / Path(STAGES[0].relative).parent
    forced = {}
    for name in FORCEFIELD_FILES:
        source = FORCEFIELD_ROOT / name
        if not source.is_file():
            continue
        shutil.copy2(source, system / name)
        forced[name] = {'sha256': files.sha256(source), 'bytes': source.stat().st_size}
    numbers['force_field'] = {**FORCEFIELD_SOURCE, 'files': forced, 'root': str(FORCEFIELD_ROOT)}
    if protein_path is not None:
        (system / 'protein.pdb').write_bytes(protein_path.read_bytes())
    else:
        (system / 'protein.pdb').write_text('; no protein: this is an empty-micelle build\n')
    (system / Path(STAGES[0].inputs[2]).name).write_bytes((template_path.parent / record.topology).read_bytes())
    (system / Path(STAGES[0].inputs[1]).name).write_text(_empty_topology())
    # The detergent's coarse-grained model, derived from the run's own mapping: the topology the system will include
    # and the bead geometry the placement stamps. A build without a mapping is recorded as centres-only.
    model = {'mapping': None, 'terms': 0, 'reference_terms': 0, 'fallback_terms': 0}
    mapping_tail_beads = []
    if mapping is not None:
        from ...models.mappings import store
        from ...models.molecules import detergent_cg
        # A saved candidate arrives by name, not by path: the panel offers the names the store lists, and the run's
        # own record keeps that name, so it is resolved here rather than demanded as a path.
        source = Path(str(mapping))
        if not source.is_file():
            candidate = store.candidate_paths().get(source.name)
            source = Path(candidate) if candidate else (root / str(mapping))
        if not source.is_file():
            raise ValueError(f'the detergent mapping is not a file: {mapping}')
        draft = detergent_cg.derive(source, root / 'molecules', root)
        (system / DETERGENT_TOPOLOGY).write_text(draft['topology'])
        (system / DETERGENT_GEOMETRY).write_text(json.dumps(draft, indent=2, sort_keys=True))
        model = {'mapping': str(source), 'residue': draft['residue'], 'beads': len(draft['beads']),
                 'terms': draft['terms'], 'reference_terms': draft['reference_terms'],
                 'fallback_terms': draft['fallback_terms']}
        # The mapping answers for itself when the template cannot: a bead of the aliphatic carbon series is a tail
        # bead, and the sugar and polar series are not. This is what lets the criterion judge a run whose template is
        # still the skeleton -- one bead, no roles -- instead of refusing it.
        mapping_tail_beads = [str(bead['name']) for bead in draft.get('beads', [])
                              if re.fullmatch(r'C[1-5][a-z]?', str(bead.get('type') or ''))]
    numbers['detergent_model'] = model
    if not numbers['tail_beads'] and mapping_tail_beads:
        # The template is the long-term home for this, but the skeleton names no roles: the run's own mapping answers
        # instead, and the settings record which source was used so a reader knows what the criterion was told.
        numbers['tail_beads'] = mapping_tail_beads
        numbers['tail_beads_source'] = ("the run's own mapping: beads of the aliphatic carbon series, because the "
                                        'template names no tail roles')
    (system / SETTINGS_NAME).write_text(json.dumps(
        {'project_root': str(root), 'protein': str(protein) if protein else '', 'template': str(template),
         **numbers},
        indent=2, sort_keys=True))
    (system / Path(STAGES[0].relative).name).write_text(_STAGE_SCRIPT.format(
        label=STAGES[0].name, report=REPORT_NAME, root=str(root), python=sys.executable))
    assessment_steps = _assessment_stage(run_dir, numbers)
    extension_ps = _extension_stage(run_dir, numbers)
    # One record, and it is the one the pipeline reads: `workflow.prepare_run` takes this manifest, adds the run's
    # snapshots and tools, and moves it to the run root. A tool that is not resolvable is recorded as unresolved
    # rather than raising here, because readiness is the layer that blocks a run for it.
    recorded_tools = {}
    for name in ('gmx', 'martinize2'):
        found = tools.tool_path(name)
        recorded_tools[name] = ({'path': found, 'sha256': files.sha256(found)} if found
                                else {'path': name, 'ready': False,
                                      'detail': 'not declared or not executable'})
    for stage in STAGES:
        script = run_dir / Path(stage.relative)
        if not script.is_file():
            continue
        _stamp_interpreter(script, root)
        _stage_declared_inputs(script, stage)
    # The record is merged into whatever the coordinator already wrote rather than replacing it: a run's manifest
    # carries the executor's own keys -- the stage ledger above all -- and replacing the file left the worker reading
    # a manifest with no `stages`, which failed the run with a KeyError instead of a build.
    manifest = {}
    if (run_dir / 'manifest.json').is_file():
        try:
            manifest = json.loads((run_dir / 'manifest.json').read_text())
        except ValueError:
            manifest = {}
    manifest.update(
        {'run_type': 'pdc', 'stage_plan': _plan(), 'settings': numbers,
         'protein': str(protein) if protein else '', 'template': str(template),
         'template_issues': template_issues,
         'assessment_steps': assessment_steps, 'extension_ps': extension_ps, 'tools': recorded_tools,
         'limitations': ['the detergent is one centre per molecule: the shipped templates carry no bead shape',
                         'the assessment, removal, extension and back-mapping stage scripts are task B7b']})
    manifest.setdefault('stages', [])
    (run_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True))


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


def readiness(protein=None, template=None, project_root=None, **kwargs):
    """What a protein-detergent build needs, in the shape every run type answers with.

    The template is checked by its own reader and validator, because those are the two things that decide whether
    it can build a system at all; the executables are resolved through the declared tools, so a build that names a
    tool the machine does not have is blocked here rather than in the middle of a stage. An empty micelle is a
    choice the caller states, so a missing protein is reported as an absence rather than a blocker when it is one.
    """
    from micelle import registry

    from ..environment import probe_tool

    checks, blockers = [], []
    root = Path(project_root or Path.cwd())
    paths_named = {}
    for label, value in (('Protein', protein), ('Detergent template', template)):
        if not value:
            if label == 'Protein' and template:
                checks.append({'label': label, 'path': 'none (empty micelle)', 'ready': True,
                               'detail': 'no protein by choice: the protein stages are skipped'})
            else:
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
    """The run's own inputs, in the spellings the builders take: a saved mapping arrives as the job's candidate."""
    values = {'protein': metadata.get('protein'), 'template': metadata.get('template'),
              'settings': metadata.get('settings'), 'project_root': metadata.get('project_root'),
              'mapping': metadata.get('mapping_candidate') or metadata.get('mapping')}
    prepare(run_dir, **{key: value for key, value in values.items() if value})


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
