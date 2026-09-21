import json


def write_aa_fixture(root, molecule_id='Fixture'):
    folder = root / molecule_id; folder.mkdir(parents=True)
    rows = ['[ moleculetype ]', 'LIG 1', '[ atoms ]',
            '1 CT 1 LIG C1 1 0 12.011', '2 CT 1 LIG C2 2 0 12.011',
            '3 CT 1 LIG C3 3 0 12.011', '4 CT 1 LIG C4 4 0 12.011',
            '5 HC 1 LIG H1 5 0 1.008', '[ bonds ]',
            '1 2 1 0.15 1000', '2 3 1 0.15 1000', '3 4 1 0.15 1000', '1 5 1 0.10 1000']
    (folder / 'molecule.itp').write_text('\n'.join(rows) + '\n')
    gro = ['Fixture', '5']
    for i, name in enumerate(('C1', 'C2', 'C3', 'C4', 'H1'), 1): gro.append(f'{1:5d}{"LIG":<5}{name:>5}{i:5d}{i * .1:8.3f}{0.:8.3f}{0.:8.3f}')
    (folder / 'molecule.gro').write_text('\n'.join(gro + ['1 1 1', '']))
    (folder / 'metadata.json').write_text(json.dumps({'name': molecule_id, 'molecule_type': 'LIG', 'net_charge': 0, 'force_field': 'charmm36-jul2022.ff', 'water_model': 'tip3p'}))
    return folder
