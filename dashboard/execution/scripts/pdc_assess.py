"""Judge the micelle at the end of a phase, and say what would survive if the rest were removed.

Run by `3_assessment/pdc_assess.sh` and `5_assessment/pdc_assess.sh`. The verdict comes from `pdc_assessment`, which is the
one implementation of the design spec's criterion; this module's job is to read the system the stage produced,
select each detergent's tail beads, and write the three declared outputs.

    python pdc_assess.py --settings ../1_system/pdc-settings.json --structure prod/run.gro

Reads the stage's structure rather than the trajectory, because the verdict is about the state the phase ended in
and a reader can check it against one file. The series of frames is the snapshot work, not this.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from dashboard.execution.adapters import pdc_assessment, pdc_view
from micelle import output as micelle_output

ASSESSMENT_NAME = 'assessment.json'
KEPT_NAME = 'kept.gro'
REMOVED_NAME = 'removed.json'


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def system_structure(structure: Path, detergent_residue: str):
    """Split a CG structure into protein beads and one group per detergent molecule.

    The protein comes back as beads rather than positions so a structure written from this one keeps the protein's
    own residue numbers: what is kept has to still be the system it was.
    """
    atoms = pdc_view.read_gro(structure)
    protein = [atom for atom in atoms if atom['residue'] != detergent_residue]
    molecules: dict[int, list[dict]] = {}
    for atom in atoms:
        if atom['residue'] == detergent_residue:
            molecules.setdefault(atom['residue_id'], []).append(atom)
    ordered = [molecules[key] for key in sorted(molecules)]
    return protein, ordered


def tail_positions(beads, tail_beads) -> list[list[float]]:
    return [bead['position'] for bead in beads if bead['name'] in tail_beads]


def read_settings(path) -> dict:
    return json.loads(Path(path).read_text())


def resolved(settings: dict):
    """The template's own facts about the system: which residue is detergent, and which beads are its core."""
    tail_beads = {str(name) for name in settings.get('tail_beads') or []}
    if not tail_beads:
        raise SystemExit('the run records no tail beads, so the criterion cannot tell a micelle from a crowd: '
                         'name them on the detergent template (a bead role of "tail") and re-prepare the run')
    template = json.loads((Path(settings['project_root']) / settings['template']).read_text())
    return str(template.get('residue') or template.get('name')), tail_beads


def judge(structure: Path, settings: dict) -> dict:
    """The criterion applied to one structure, with the pieces a caller needs to write it out.

    One function, called per frame and per phase, so every picture, every index entry and the report's verdict are
    the same measurement rather than three implementations of it.
    """
    detergent_residue, tail_beads = resolved(settings)
    protein, molecules = system_structure(structure, detergent_residue)
    if not molecules:
        raise SystemExit(f'{structure} holds no {detergent_residue} beads: the criterion has nothing to judge')
    detergents = [{'name': f'{detergent_residue}{index + 1}', 'tail': tail_positions(beads, tail_beads)}
                  for index, beads in enumerate(molecules)]
    verdict = pdc_assessment.assess_micelle(detergents, [atom['position'] for atom in protein] or None,
                                           contact_nm=float(settings.get('contact_nm', pdc_assessment.CONTACT_NM)),
                                           aggregation_number=int(settings['aggregation_number']))
    return {'verdict': verdict, 'protein': protein, 'molecules': molecules, 'detergents': detergents,
            'detergent_residue': detergent_residue, 'tail_beads': tail_beads}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Assess the micelle in a protein-detergent system.')
    parser.add_argument('--settings', default='../1_system/pdc-settings.json')
    parser.add_argument('--structure', default='prod/run.gro')
    parser.add_argument('--stage', default='.')
    args = parser.parse_args(argv)
    stage = Path(args.stage)

    settings = read_settings(args.settings)
    structure = stage / args.structure
    judged = judge(structure, settings)
    verdict, protein, molecules = judged['verdict'], judged['protein'], judged['molecules']
    detergent_residue, tail_beads = judged['detergent_residue'], judged['tail_beads']
    kept_names = set(verdict['in_micelle'])
    kept = [group for detergent, group in zip(judged['detergents'], molecules) if detergent['name'] in kept_names]
    removed = [{'name': detergent['name'], 'residue_id': group[0]['residue_id'], 'beads': len(group),
                'tail_beads': len(detergent['tail'])}
               for detergent, group in zip(judged['detergents'], molecules)
               if detergent['name'] not in kept_names]

    # The picture of the moment, written with the numbers the moment was judged on: a gallery that cannot disagree
    # with a verdict, because both come from the same call above.
    from dashboard.execution.scripts import pdc_snapshot
    pdc_snapshot.write_snapshot(stage, stage.name, structure, detergent_residue=detergent_residue,
                                title=f'{detergent_residue} system, {stage.name}',
                                criterion={'verdict': verdict['verdict'], 'largest_cluster': verdict['largest_cluster'],
                                           'aggregation_number': verdict['aggregation_number'],
                                           'fraction_of_requested': verdict['fraction_of_requested'],
                                           'protein_contact_count': verdict['protein_contact_count'],
                                           'reasons': verdict['reasons']})

    (stage / ASSESSMENT_NAME).write_text(json.dumps(
        {**verdict, 'structure': str(structure), 'structure_sha256': digest(structure),
         'detergent_residue': detergent_residue, 'tail_beads': sorted(tail_beads),
         'protein_beads': len(protein), 'detergents_present': len(molecules)}, indent=2, sort_keys=True))
    # The kept structure is the restart's input, so it is the *dry* one: the protein, when there is one, and the
    # detergents that stay. Measured: it used to carry the water and the ions too (W 5369, ION 128, three detergents),
    # and the restart could then do nothing useful with it -- re-solvation found the box already full and added four
    # water beads, while the dry topology the restart writes described a different system and grompp refused the pair.
    # The restart solvates because removal leaves space where the water never was; it needs a dry structure to fill.
    from dashboard.execution.adapters import pdc_solvation

    solvent = pdc_solvation.SOLVENT_RESIDUES
    atoms = [{'residue_id': atom['residue_id'], 'residue': atom['residue'], 'name': atom['name'],
              'position': atom['position']} for atom in protein if str(atom.get('residue')) not in solvent]
    for group in kept:
        atoms.extend({'residue_id': bead['residue_id'], 'residue': bead['residue'], 'name': bead['name'],
                      'position': bead['position']} for bead in group)
    micelle_output.write_gro(stage / KEPT_NAME, atoms, title=f'{detergent_residue} system, detergents in the micelle',
                             box=pdc_view.read_gro_box(structure))
    (stage / REMOVED_NAME).write_text(json.dumps(
        {'removed': removed, 'kept': sorted(kept_names), 'fraction_removed': round(len(removed) / len(molecules), 6),
         'threshold_fraction': settings.get('selection_threshold_fraction'),
         'reasons': verdict['reasons'], 'aggregation_number': verdict['aggregation_number']},
        indent=2, sort_keys=True))
    print(f"{verdict['verdict']}: largest cluster {verdict['largest_cluster']} of "
          f"{verdict['aggregation_number']}, {len(removed)} outside it")
    return 0


if __name__ == '__main__':
    sys.exit(main())
