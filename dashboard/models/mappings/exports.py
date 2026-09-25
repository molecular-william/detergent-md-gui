"""Mapping exports: NDX, MAP, GRO, model.json and bundle README."""
from pathlib import Path
import hashlib
import json

from .. import sugars as carbohydrates
from .context import as_structure
from ..molecules.packaged import ROOT, SOURCE, molecule
from . import verdict
from .graph import require_usable, validate


def export_files(data, *, context=None):
    """Export review artifacts, keeping a single bead order across all formats.

    Atom IDs refer to the supplied ligand-only SwissParam order. Equal-weight
    heavy-atom COG is explicit; hydrogens are not silently added to the mapping.
    """
    if data.get('schema_version') == 3:
        if context is None:
            from .context import build_context
            context = build_context(ROOT / 'molecules', data.get('molecule_id', ''))
        validation = require_usable(data, context, operation='export')
        structure = as_structure(context)
        atoms = {a['id']: a for a in structure['atoms']}
        atom_names = [a['name'] for a in atoms.values()]
        if len(atom_names) != len(set(atom_names)):
            raise ValueError('Fast_Forward selects atoms by name; source atom names must be unique')
        beads = [{**bead, 'export_name': f'B{i+1:02d}'} for i, bead in enumerate(data['beads'])]
        physical = [b for b in beads if not b.get('virtual_site')]
        ndx = ''.join(f'[ {b["export_name"]} ]\n' + ' '.join(map(str, sorted(b['atoms']))) + '\n\n' for b in physical)
        molecule_name = str(context.get('name') or context.get('molecule_id') or 'molecule')
        mapping = f'[ molecule ]\nLIG1 {molecule_name}\n\n[ martini ]\n' + ' '.join(b['export_name'] for b in physical) + '\n\n[ atoms ]\n'
        assignments = {a: b['export_name'] for b in beads for a in b['atoms']}
        for index in sorted(assignments):
            mapping += f'{index}\t{atoms[index]["name"]}\t{assignments[index]}\n'
        gro = f'{molecule_name} candidate; heavy-atom COG; not a simulation box\n{len(beads):5d}\n'
        for i, bead in enumerate(beads, 1):
            owned = [atoms[a]['xyz'] for a in bead.get('atoms', []) if a in atoms]
            if bead.get('virtual_site'):
                parents = {p: next((b for b in beads if b['name'] == p), None) for p in bead['virtual_site'].get('parents', [])}
                owned = [atoms[a]['xyz'] for parent in parents.values() if parent for a in parent.get('atoms', []) if a in atoms]
            center = [sum(point[d] for point in owned) / len(owned) / 10 for d in range(3)] if owned else [0.0, 0.0, 0.0]
            gro += f'{1:5d}{molecule_name[:5]:<5}{bead["export_name"]:>5}{i:5d}' + ''.join(f'{v:8.3f}' for v in center) + '\n'
        gro += '   0.00000   0.00000   0.00000\n'
        record = {'name': data['name'], 'status': 'candidate-unvalidated', 'martini_version': '3',
                  'mapping_mode': 'COG', 'hydrogens': 'excluded', 'beads': beads, 'validation': validation,
                  'molecule_id': context['molecule_id'], 'molecule_snapshot': context['snapshot'],
                  'source': context.get('path', ''), 'source_quality': context.get('source_quality', {})}
        for key in ('rings', 'connections', 'bonded_options', 'bonded_overrides', 'schema_version', 'provenance', 'limitations'):
            if key in data: record[key] = data[key]
        readme = f'{molecule_name} mapping export — candidate, not a fitted CG force field\n\n'
        readme += 'mapping.ndx uses canonical one-based atom indices. mapping.map uses the selected molecule source. mapped.gro is a heavy-atom COG frame in nm. Virtual sites are described in model.json and require downstream construction.\n'
        return {'mapping.ndx': ndx, 'mapping.map': mapping, 'mapped.gro': gro,
                'model.json': json.dumps(record, indent=2), 'README.txt': readme}
    structure = molecule()
    validation = validate(data, structure)
    blockers = [item['message'] for item in verdict.blocking(validation['issues'], 'can_export')]
    if blockers:
        raise ValueError('Cannot export ambiguous assignments: ' + '; '.join(blockers))
    atoms = {a['id']: a for a in structure['atoms']}
    atom_names = [a['name'] for a in atoms.values()]
    if len(atom_names) != len(set(atom_names)):
        raise ValueError('Fast_Forward selects atoms by name; source atom names must be unique')
    beads = [{**bead, 'export_name': f'B{i+1:02d}'} for i, bead in enumerate(data['beads'])]
    physical = [b for b in beads if not b.get('virtual_site')]
    ndx = ''.join(f'[ {b["export_name"]} ]\n' + ' '.join(map(str, sorted(b['atoms']))) + '\n\n' for b in physical)
    mapping = '[ molecule ]\nLIG1 DDM\n\n[ martini ]\n' + ' '.join(b['export_name'] for b in physical) + '\n\n[ atoms ]\n'
    assignments = {a: b['export_name'] for b in beads for a in b['atoms']}
    for index in sorted(assignments):
        mapping += f'{index}\t{atoms[index]["name"]}\t{assignments[index]}\n'
    gro = f'DDM candidate; heavy-atom COG; not a simulation box\n{len(beads):5d}\n'
    coords = carbohydrates.coordinates(data, [a['xyz'] for a in atoms.values()], list(atoms)) / 10
    for i, bead in enumerate(beads, 1):
        center = coords[i-1]
        gro += f'{1:5d}{"DDM":<5}{bead["export_name"]:>5}{i:5d}' + ''.join(f'{v:8.3f}' for v in center) + '\n'
    gro += '   0.00000   0.00000   0.00000\n'
    record = {'name': data['name'], 'status': 'candidate-unvalidated', 'martini_version': '3',
              'mapping_mode': 'COG', 'hydrogens': 'excluded', 'beads': beads, 'validation': validation,
              'source': structure['source'],
              'source_sha256': hashlib.sha256((SOURCE / 'results/MMFF/lig1.pdb').read_bytes()).hexdigest()}
    for key in ('rings','connections','bonded_options','bonded_overrides','schema_version','provenance','limitations',
                'representation_mode','source_mapping_hash','transformation'):
        if key in data: record[key] = data[key]
    readme = '''DDM mapping export — candidate, not a fitted CG force field

mapping.ndx uses one-based atom indices in the original SwissParam ligand order.
mapping.map uses the Fast_Forward [ molecule ] header LIG1 DDM.
mapped.gro is a single equal-weight heavy-atom COG frame, in nm, with no box.
B01, B02, ... identify the same ordered beads in all three files. Original
labels, assignments, source checksum and validation findings are in model.json.
No topology or bonded parameters are generated by this export.

Use an intact, ligand-only AA trajectory and its matching TPR with ff_map:
ff_map -f lig.xtc -s lig.tpr -m mapping.map -o mapped.xtc -mols LIG1 -mode COG
These ligand-only inputs still need to be produced by the AA workflow.

Hydrogens are deliberately excluded, following the current candidate definition.
Martini heavy-atom grouping guidance does not uniquely specify coordinate weights;
review hydrogen inclusion/weights before fitting (see Fast_Forward documentation).
Size and disconnected-group findings remain review issues, even when files parse.
'''
    if data.get('rings'):
        readme += '\nVirtual sites are included in model.json and mapped.gro, but not as exclusive AA atom groups in map/ndx. Use the dashboard sugar mapping runner to construct them and retain ring scaling. Standalone ff_map does not produce the complete model.\n'
    exported = {'mapping.ndx': ndx, 'mapping.map': mapping, 'mapped.gro': gro,
                'model.json': json.dumps(record, indent=2), 'README.txt': readme}
    if data.get('rings'):
        exported['DDM_initial.itp'] = carbohydrates.topology(
            data, structure, representation_mode=data.get('representation_mode'))
        exported['carbohydrates.py'] = (Path(carbohydrates.__file__)).read_text()
        exported['sugar_mapping.py'] = (ROOT/'dashboard/execution/scripts/sugar_mapping.py').read_text()
        exported['prepare_ring_constraints.py'] = (ROOT/'dashboard/execution/scripts/prepare_ring_constraints.py').read_text()
        exported['README.txt'] = readme.replace('No topology or bonded parameters are generated by this export.',
            'DDM_initial.itp supplies the paper architecture with coordinate-seeded constraints and provisional flexible terms. Run the bundled mapping helper in a 2_mapping directory beside 1_AA-reference/prod/lig.{gro,xtc}; prepare_ring_constraints.py runs from 3_initial_CG before ff_inter. Use the dashboard workflow to fit and assess the complete model; virtual sites cannot be constructed by standalone ff_map.')
    return exported
