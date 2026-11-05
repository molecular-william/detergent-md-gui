"""The algorithms an automatic mapping candidate can be built with.

One entry point, `generate`, so the route, the editor and the tests dispatch by name and see the
same `{available, candidate, reasons}` answer. The gate lives here and not in a builder: the
automatic path must never hand back a document its own validator rejects, and a bead whose atoms are
not one connected group, or one the mapping layer's size convention cannot describe, is exactly that.
"""
from copy import deepcopy

from .. import graph
from ..context import as_structure
from . import connectivity, spectral

DEFAULT = 'connectivity'
ALGORITHMS = {'connectivity': connectivity, 'spectral': spectral}
#: The defects the automatic path refuses to return: a bead not connected in the bond graph, and a bead
#: whose heavy-atom count its stated size cannot carry (over the four-atom cap included).
BLOCKING = ('disconnected', 'size')


def generate(context, index, algorithm=DEFAULT):
    """The automatic candidate for one algorithm, or why there is none."""
    builder = ALGORITHMS.get(algorithm)
    if builder is None:
        return {'available': False, 'candidate': None,
                'reasons': [f'Unknown mapping algorithm {algorithm!r}; choose one of '
                            f'{", ".join(sorted(ALGORITHMS))}.']}
    automatic = context.get('capabilities', {}).get('automatic', {})
    if not automatic.get('available'):
        return {'available': False, 'candidate': None, 'reasons': list(automatic.get('reasons', []))}
    structure = as_structure(context)
    try:
        candidate = builder.build(context, structure, index)
    except (KeyError, ValueError) as exc:
        return {'available': False, 'candidate': None, 'reasons': [str(exc)]}
    document = _document(context, candidate, algorithm, index)
    try:
        issues = graph.validate(document, structure)['issues']
    except ValueError as exc:
        return {'available': False, 'candidate': None, 'reasons': [str(exc)]}
    blocking = [issue['message'] for issue in issues if issue['code'] in BLOCKING]
    if blocking:
        return {'available': False, 'candidate': None, 'reasons': blocking}
    return {'available': True, 'candidate': document, 'reasons': []}


def _document(context, candidate, algorithm, index):
    """The candidate as the editor's document: bound to its molecule, saying what produced it."""
    document = deepcopy(candidate)
    document['schema_version'] = 3
    document['molecule_id'] = context['molecule_id']
    document['molecule_snapshot'] = deepcopy(context['snapshot'])
    document['provenance'] = {
        **document.get('provenance', {}), 'origin': 'automatic', 'algorithm': algorithm,
        'parameters': ALGORITHMS[algorithm].PARAMETERS,
        'reference_index_sha256': index.get('index_sha256'),
        'references': [reference for bead in document.get('beads', [])
                       for reference in bead.get('suggestion', {}).get('references', [])]}
    document.pop('file', None)
    document.pop('sha256', None)
    document.pop('validation', None)
    return document
