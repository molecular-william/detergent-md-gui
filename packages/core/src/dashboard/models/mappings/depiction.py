"""An SVG scene of a molecule context with draft bead overlays; no generated chemistry."""
import math
import xml.etree.ElementTree as ET

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
