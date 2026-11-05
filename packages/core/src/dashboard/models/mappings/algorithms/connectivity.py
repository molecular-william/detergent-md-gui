"""The sugar-first connectivity algorithm: the ring layer's beads, then the remainder chunked.

This is the automatic candidate the repository has always built. A recognised pyranose or furanose
is mapped by the paper's fragments, a ring no template covers by the general fragment rules, and
whatever no ring claimed is a TAIL or LINK chunked four heavy atoms at a time, never across a
branch. A molecule with no ring at all falls back to connected fragments typed from the reference
index.
"""
from copy import deepcopy

from ...sugars import candidate as carbohydrate_candidate
from .. import schema

PARAMETERS = {'max_group_heavy_atoms': 4, 'tie_break': 'ascending-aa-id', 'rings': 'sugar-layer'}


def build(context, structure, index):
    """The candidate this molecule gets from the sugar layer, or from the fragment fallback."""
    candidate = carbohydrate_candidate(structure, context['molecule_id'])
    if candidate is not None:
        return candidate
    return _fragments(context, structure, index)


def _fragments(context, structure, index):
    """A molecule with no recognised ring: connected fragments, typed from the reference index."""
    # Deferred: `suggestions` delegates its preview to this package, so it cannot be imported at load time.
    from .. import suggestions

    beads = []
    for number, group in enumerate(schema.fragment_groups(structure), 1):
        suggestion = suggestions.suggest_bead(context, group, index)['suggestions'][0]
        beads.append({'name': f'BEAD{number:02d}', 'size': suggestion['size'],
                      'type': suggestion['type'], 'atoms': group, 'suggestion': suggestion})
    return {'name': f"{context['molecule_id']} generic graph draft", 'beads': beads,
            'rings': [], 'connections': [], 'schema_version': 3,
            'molecule_id': context['molecule_id'],
            'molecule_snapshot': deepcopy(context['snapshot']),
            'status': 'candidate-unvalidated', 'martini_version': '3',
            'source_structure': context.get('path', ''),
            'limitations': ['No verified molecule-specific sugar or fragment template matched.']}
