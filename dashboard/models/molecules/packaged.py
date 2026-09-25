"""Packaged DDM source graph, bead catalogue and file paths.

The mapping layer no longer assumes a default molecule. Callers that need the
packaged SwissParam reference for DDM (the smoke test, the sugar-first
candidate builder, the mapping exports' README) import these symbols
explicitly instead of relying on a module-level default.
"""
import re
from copy import deepcopy
from functools import lru_cache

from ... import paths

ROOT = paths.DEFAULT.project_root
SOURCE = ROOT / 'molecules' / 'DDM'


def molecule():
    """Packaged DDM SwissParam atom/bond graph."""
    return deepcopy(_molecule((SOURCE/'results/MMFF/lig1.itp').read_text(),
                              (SOURCE/'results/MMFF/lig1.pdb').read_text()))


@lru_cache(maxsize=4)
def _molecule(topology_text, coordinate_text):
    section = ''
    topology = {}
    bonds = []
    for line in topology_text.splitlines():
        text = line.split(';')[0].strip()
        if text.startswith('['):
            section = text.strip('[] ').strip()
        elif text and not text.startswith('#'):
            fields = text.split()
            if section == 'atoms':
                topology[int(fields[0])] = {'name': fields[4], 'mass': float(fields[7])}
            elif section == 'bonds':
                bonds.append([int(fields[0]), int(fields[1])])
    atoms = []
    for line in coordinate_text.splitlines():
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        index, name = int(line[6:11]), line[12:16].strip()
        if index not in topology or topology[index]['name'] != name:
            raise ValueError('SwissParam coordinate and topology atom order differ')
        atoms.append({'id': index, 'name': name, 'element': re.sub(r'[^A-Za-z]', '', name)[:1],
                      'heavy': topology[index]['mass'] > 2,
                      'xyz': [float(line[i:i+8]) for i in (30, 38, 46)]})
    if len(atoms) != len(topology):
        raise ValueError('SwissParam coordinate and topology atom counts differ')
    return {'atoms': atoms, 'bonds': bonds, 'source': 'molecules/DDM/results/MMFF/lig1.pdb',
            'bond_source': 'molecules/DDM/results/MMFF/lig1.itp'}


def bead_types():
    """Catalog of Martini 3.0.0 atom types plus sugar-fragment annotations."""
    path = ROOT/'resources/templates/small_mols_fast_forward/3_initial_CG/martini_v3.0.0.itp'
    stat = path.stat()
    return deepcopy(_bead_types(path, stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=4)
def _bead_types(path, modified, size):
    section = ''; result = []
    special = {'SP4r':'Carbohydrate diol fragment (paper)', 'SP1r':'Carbohydrate ether-containing fragment (paper)',
               'SN6':'Glycosidic donor fragment lacking bridge oxygen (paper)', 'TC4':'Tiny apolar; also used for massless sugar-ring interaction sites'}
    with path.open() as stream:
        for line in stream:
            raw = line.split(';')[0].strip()
            if raw.startswith('['):
                if section == 'atomtypes': break
                section = raw.strip('[] ')
            elif section == 'atomtypes' and raw:
                name = raw.split()[0]; size = name[0] if name[0] in 'ST' and name not in ('SW','TW') else 'R'
                base = name[1:] if size != 'R' else name
                family = {'C':'apolar','N':'intermediate polarity','P':'polar','Q':'charged','X':'special interaction'}.get(base[0],'auxiliary / consult force field')
                result.append({'type':name,'size':size,'description':special.get(name, f'{size} size · {family}; exact interactions defined by Martini 3.0.0')})
    return result