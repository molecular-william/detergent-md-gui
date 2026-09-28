"""The protein-detergent complex pipeline. `micelle/` owns the science; this adapter owns the stages.

Only the catalogue and the stage contract live here so far: the placement, sampling, assessment and back-mapping
stages arrive with the phases that implement them, and every one of them belongs to this module rather than to the
route layer.
"""
import json
from pathlib import Path

from ..stages import Stage

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
