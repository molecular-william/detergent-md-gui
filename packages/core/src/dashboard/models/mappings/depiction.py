"""RDKit 2D structure with draft bead overlays; no generated chemistry."""
import hashlib
import math
import xml.etree.ElementTree as ET
from functools import lru_cache

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

from .. import mappings

COLORS = ['#2864b5', '#169186', '#aa6920', '#8762b6', '#ba4775', '#347844',
          '#a74b32', '#536697', '#8b751b', '#6754ac', '#287d93', '#ae5486']
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def _zigzag_carbon_chains(context, atoms, points):
    """Give long, straight carbon paths a readable skeletal zig-zag."""
    carbon_ids = {atom['id'] for atom in atoms if atom.get('element') == 'C'}
    adjacency = {atom_id: set() for atom_id in carbon_ids}
    for bond in context.get('bonds', []):
        a, b = bond['a'], bond['b']
        if a in adjacency and b in adjacency:
            adjacency[a].add(b)
            adjacency[b].add(a)

    remaining = set(carbon_ids)
    while remaining:
        component = set()
        stack = [remaining.pop()]
        while stack:
            atom_id = stack.pop()
            component.add(atom_id)
            for neighbor in adjacency[atom_id] & remaining:
                remaining.remove(neighbor)
                stack.append(neighbor)
        if len(component) < 5 or any(len(adjacency[atom_id] & component) > 2 for atom_id in component):
            continue
        endpoints = [atom_id for atom_id in component if len(adjacency[atom_id] & component) == 1]
        if len(endpoints) != 2:
            continue

        path = [endpoints[0]]
        previous = None
        while True:
            neighbors = [atom_id for atom_id in adjacency[path[-1]] & component if atom_id != previous]
            if not neighbors:
                break
            previous, next_atom = path[-1], neighbors[0]
            if next_atom in path:
                path = []
                break
            path.append(next_atom)
        if len(path) != len(component) or any(atom_id not in points for atom_id in path):
            continue

        start, end = points[path[0]], points[path[-1]]
        axis_x, axis_y = end[0] - start[0], end[1] - start[1]
        length = math.hypot(axis_x, axis_y)
        if length <= 1e-9:
            continue
        axis_x, axis_y = axis_x / length, axis_y / length
        perpendicular = (-axis_y, axis_x)
        residuals = [abs((point[0] - start[0]) * perpendicular[0] +
                         (point[1] - start[1]) * perpendicular[1]) for point in (points[atom_id] for atom_id in path)]
        spacing = sum(math.hypot(points[path[index + 1]][0] - points[path[index]][0],
                                 points[path[index + 1]][1] - points[path[index]][1])
                      for index in range(len(path) - 1)) / (len(path) - 1)
        if max(residuals) > spacing * 0.15 or spacing <= 1e-9:
            continue

        amplitude = spacing * 0.35
        for index, atom_id in enumerate(path):
            offset = amplitude if index % 2 else -amplitude
            points[atom_id] = [points[atom_id][0] + perpendicular[0] * offset,
                               points[atom_id][1] + perpendicular[1] * offset]


def _scene_bounds(context):
    visible_atoms = [atom for atom in context.get('atoms', []) if atom.get('heavy')]
    if all(atom.get('display_xy') for atom in visible_atoms):
        points = {atom['id']: list(atom['display_xy']) for atom in visible_atoms}
    else:
        points = {atom['id']: [float(atom['xyz'][0]), float(atom['xyz'][1])] for atom in visible_atoms}
    if not points:
        raise ValueError('Molecule has no coordinates for 2D depiction')
    _zigzag_carbon_chains(context, visible_atoms, points)
    min_x = min(point[0] for point in points.values()); max_x = max(point[0] for point in points.values())
    min_y = min(point[1] for point in points.values()); max_y = max(point[1] for point in points.values())
    width, height, padding = 1000.0, 650.0, 70.0
    scale = min((width - 2 * padding) / max(max_x - min_x, 1e-9),
                (height - 2 * padding) / max(max_y - min_y, 1e-9))
    positions = {}
    for atom in visible_atoms:
        point = points[atom['id']]
        positions[atom['id']] = [padding + (point[0] - min_x) * scale,
                                 height - padding - (point[1] - min_y) * scale]
    return positions, width, height


def build_scene(context):
    """Build a stable base SVG and atom positions for an explicit molecule context."""
    positions, width, height = _scene_bounds(context)
    root = ET.Element(tag('svg'), {'viewBox': f'0 0 {width:.0f} {height:.0f}',
                                   'role': 'img', 'aria-label': f'{context.get("name", "Molecule")} molecular structure'})
    ET.SubElement(root, tag('title')).text = f'{context.get("name", "Molecule")} molecular structure'
    bonds = ET.SubElement(root, tag('g'), {'class': 'chemical-bonds'})
    for bond in context.get('bonds', []):
        if bond['a'] not in positions or bond['b'] not in positions:
            continue
        attrs = {'x1': f'{positions[bond["a"]][0]:.2f}', 'y1': f'{positions[bond["a"]][1]:.2f}',
                 'x2': f'{positions[bond["b"]][0]:.2f}', 'y2': f'{positions[bond["b"]][1]:.2f}',
                 'stroke': '#93a4b7', 'stroke-width': '3', 'stroke-linecap': 'round',
                 'data-order-source': bond.get('order_source', 'fallback')}
        ET.SubElement(bonds, tag('line'), attrs)
    atoms = ET.SubElement(root, tag('g'), {'class': 'chemical-atoms'})
    for atom in context.get('atoms', []):
        if not atom.get('heavy'):
            continue
        if atom['id'] not in positions:
            continue
        group = ET.SubElement(atoms, tag('g'), {'class': 'atom heavy',
                                                'data-atom-id': str(atom['id']),
                                                'data-heavy': 'true',
                                                'tabindex': '0',
                                                'aria-label': f'Atom {atom["id"]} ({atom["name"]})'})
        ET.SubElement(group, tag('circle'), {'cx': f'{positions[atom["id"]][0]:.2f}',
                                              'cy': f'{positions[atom["id"]][1]:.2f}',
                                              'r': '11',
                                              'fill': '#ffffff',
                                              'stroke': '#8295aa', 'stroke-width': '2'})
        ET.SubElement(group, tag('text'), {'x': f'{positions[atom["id"]][0] + 14:.2f}',
                                           'y': f'{positions[atom["id"]][1] - 10:.2f}',
                                           'font-size': '13', 'fill': '#45566c'}).text = atom['name']
    return {'svg': ET.tostring(root, encoding='unicode'), 'positions': positions,
            'view_box': [0, 0, width, height], 'source_quality': context.get('source_quality', {})}


def tag(name):
    return '{' + NS + '}' + name


@lru_cache(maxsize=4)
def _base(mol2_text, pdb_text, topology_text):
    mol = Chem.MolFromMol2Block(mol2_text, removeHs=False)
    if mol is None:
        raise ValueError('Cannot read the SwissParam molecular graph for depiction')
    structure = mappings.molecule()
    if mol.GetNumAtoms() != len(structure['atoms']):
        raise ValueError('MOL2 and topology atom counts differ')
    for atom, record in zip(mol.GetAtoms(), structure['atoms']):
        if atom.GetProp('_TriposAtomName') != record['name']:
            raise ValueError('MOL2 and SwissParam atom order differ')
        atom.SetIntProp('swissparam_id', record['id'])
    mol_bonds = {tuple(sorted((b.GetBeginAtomIdx()+1, b.GetEndAtomIdx()+1))) for b in mol.GetBonds()}
    if mol_bonds != {tuple(sorted(b)) for b in structure['bonds']}:
        raise ValueError('MOL2 and topology bond graphs differ')
    mol = Chem.RemoveHs(mol)
    # RDKit preserves the stereocentres assigned from the source MOL2 geometry.
    smiles = Chem.MolToSmiles(mol)
    rdDepictor.Compute2DCoords(mol)
    drawer = rdMolDraw2D.MolDraw2DSVG(1000, 570)
    drawer.drawOptions().padding = .13
    drawer.drawOptions().addStereoAnnotation = True
    for atom in mol.GetAtoms():
        atom.SetProp('atomNote', str(atom.GetIntProp('swissparam_id')))
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
    positions = {atom.GetIntProp('swissparam_id'): (drawer.GetDrawCoords(atom.GetIdx()).x,
                                                    drawer.GetDrawCoords(atom.GetIdx()).y)
                 for atom in mol.GetAtoms()}
    drawer.FinishDrawing()
    return drawer.GetDrawingText(), positions, smiles


def _render_context_mapping(data, context):
    scene = build_scene(context)
    root = ET.fromstring(scene['svg'])
    root.set('aria-label', f'{data.get("name", "Mapping")} — {context.get("name", "molecule")} structure')
    title = root.find(tag('title'))
    if title is not None:
        title.text = f'{data.get("name", "Mapping")} — unvalidated mapping'
    overlay = ET.SubElement(root, tag('g'), {'class': 'bead-overlays'})
    centers = {}
    for bead in data.get('beads', []):
        if bead.get('virtual_site'):
            continue
        points = [scene['positions'][atom] for atom in bead.get('atoms', []) if atom in scene['positions']]
        if points:
            centers[bead['name']] = [sum(point[0] for point in points) / len(points),
                                     sum(point[1] for point in points) / len(points)]
    for index, bead in enumerate(data.get('beads', [])):
        points = [scene['positions'][atom] for atom in bead.get('atoms', []) if atom in scene['positions']]
        if bead.get('virtual_site'):
            points = [centers[name] for name in bead['virtual_site'].get('parents', []) if name in centers]
        if not points:
            continue
        x = sum(point[0] for point in points) / len(points); y = sum(point[1] for point in points) / len(points)
        radius = 18 if bead.get('virtual_site') else max(math.hypot(point[0] - x, point[1] - y) for point in points) + 18
        circle = ET.SubElement(overlay, tag('circle'), {
            'cx': f'{x:.2f}', 'cy': f'{y:.2f}', 'r': f'{radius:.2f}',
            'fill': COLORS[index % len(COLORS)], 'fill-opacity': '.11',
            'stroke': COLORS[index % len(COLORS)], 'stroke-width': '2',
            'stroke-dasharray': '5 3' if bead.get('virtual_site') else 'none',
            'data-bead': str(index), 'data-atoms': ' '.join(map(str, bead.get('atoms', [])))})
        ET.SubElement(circle, tag('title')).text = f'{bead.get("name", "Bead")} · atoms {bead.get("atoms", [])}'
    return ET.tostring(root, encoding='unicode')


def render(data, *, context=None):
    if context is not None:
        mappings.check_schema(data, allow_empty=bool(data.get('schema_version') == 3))
        return _render_context_mapping(data, context)
    mappings.check_schema(data, allow_empty=bool(data.get('schema_version') == 3))
    source = mappings.SOURCE / 'results/MMFF'
    mol2 = (source / 'lig1.mol2').read_text()
    svg, positions, smiles = _base(mol2, (source / 'lig1.pdb').read_text(), (source / 'lig1.itp').read_text())
    root = ET.fromstring(svg)
    root.set('viewBox', '0 0 1000 760'); root.set('height', '760px')
    root.set('role', 'img'); root.set('aria-label', 'DDM molecular structure with candidate bead circles')
    title = ET.Element(tag('title')); title.text = f'{data["name"]} — unvalidated mapping'
    root.insert(0, title)
    metadata = ET.SubElement(root, tag('metadata'))
    metadata.text = ('Source: DDM SwissParam lig1.mol2; SHA256=' + hashlib.sha256(mol2.encode()).hexdigest()
                     + '; isomeric SMILES=' + smiles + '; circle radii show 2D group extent, not physical bead radii.')
    overlay = ET.Element(tag('g'), {'class': 'bead-overlays'})
    bead_centers = {}
    for bead in data['beads']:
        pts=[positions[a] for a in bead['atoms'] if a in positions]
        if pts: bead_centers[bead['name']]=tuple(sum(p[d] for p in pts)/len(pts) for d in (0,1))
    for i, bead in enumerate(data['beads']):
        points = [positions[a] for a in bead['atoms'] if a in positions]
        if bead.get('virtual_site'):
            points=[bead_centers[n] for n in bead['virtual_site']['parents'] if n in bead_centers]
        if not points:
            continue
        x, y = (sum(p[axis] for p in points)/len(points) for axis in (0, 1))
        radius = 18 if bead.get('virtual_site') else max(math.hypot(px-x, py-y) for px, py in points) + 13
        circle = ET.SubElement(overlay, tag('circle'), {'cx': f'{x:.2f}', 'cy': f'{y:.2f}', 'r': f'{radius:.2f}',
                               'fill': COLORS[i % len(COLORS)], 'fill-opacity': '.11',
                               'stroke': COLORS[i % len(COLORS)], 'stroke-width': '2',
                               'stroke-dasharray': '5 3' if bead.get('virtual_site') else 'none', 'data-bead': str(i), 'data-atoms': ' '.join(map(str, bead['atoms']))})
        ET.SubElement(circle, tag('title')).text = f'B{i+1:02d}: {bead["name"]}, atoms {bead["atoms"]}'
    # Insert behind the chemical bonds but after RDKit's white background.
    background = next((i for i, el in enumerate(root) if el.tag == tag('rect')), 0)
    root.insert(background+1, overlay)
    # Expand the viewBox if an invalid/disconnected group creates a large circle.
    circles = list(overlay)
    left = min([0.] + [float(c.get('cx'))-float(c.get('r'))-10 for c in circles])
    top = min([0.] + [float(c.get('cy'))-float(c.get('r'))-10 for c in circles])
    right = max([1000.] + [float(c.get('cx'))+float(c.get('r'))+10 for c in circles])
    lower = max([570.] + [float(c.get('cy'))+float(c.get('r'))+10 for c in circles])
    legend = ET.SubElement(root, tag('g'), {'font-family': 'sans-serif', 'font-size': '18'})
    for i, bead in enumerate(data['beads']):
        x, y = 35+(i % 3)*325, lower+25+(i//3)*28
        ET.SubElement(legend, tag('circle'), {'cx': str(x), 'cy': str(y-4), 'r': '5', 'fill': COLORS[i % len(COLORS)]})
        ET.SubElement(legend, tag('text'), {'x': str(x+12), 'y': str(y)}).text = f'B{i+1:02d} · {bead["name"]} ({bead["size"]})'
    bottom = lower + 65 + math.ceil(len(data['beads'])/3)*28
    ET.SubElement(legend, tag('text'), {'x': '35', 'y': str(bottom-12)}).text = 'Draft mapping · circles enclose assigned atoms in 2D; they are not physical bead radii.'
    root.set('viewBox', f'{left} {top} {right-left} {bottom-top}')
    root.set('height', str(bottom-top)); root.set('width', str(right-left))
    return ET.tostring(root, encoding='unicode')
