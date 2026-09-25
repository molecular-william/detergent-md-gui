"""Representation transforms used by carbohydrate validation attempts."""

from copy import deepcopy

from ..mappings.identity import candidate_identity


PHYSICAL_ONLY = 'physical_only_ring_constrained'
TC4 = 'tc4'
TRANSFORMATION = 'remove_tc4_retain_ring_constraints@1'


def representation_modes():
    return [
        {'id': TC4, 'label': 'TC4 reference',
         'description': 'Published carbohydrate mapping with massless TC4 ring sites.'},
        {'id': PHYSICAL_ONLY, 'label': 'Physical-only, ring-constrained',
         'description': 'Physical beads only, retaining the 1.15-scaled ring constraints.'},
    ]


def validate_representation(mapping, mode):
    if mode not in {TC4, PHYSICAL_ONLY}:
        raise ValueError(f'Unknown carbohydrate representation: {mode}')
    if not isinstance(mapping, dict) or not isinstance(mapping.get('beads'), list):
        raise ValueError('A carbohydrate representation requires a mapping with beads')
    rings = mapping.get('rings')
    if mode == PHYSICAL_ONLY and not rings:
        raise ValueError('Physical-only carbohydrate representation requires ring definitions')
    beads = {bead.get('name'): bead for bead in mapping['beads']}
    for ring in rings or []:
        parents = ring.get('beads')
        if not isinstance(parents, list) or len(parents) != 3 or len(set(parents)) != 3:
            raise ValueError('A carbohydrate ring requires three distinct physical beads')
        if not set(parents) <= beads.keys():
            raise ValueError('Carbohydrate ring references a missing physical bead')
        if any(beads[name].get('virtual_site') for name in parents):
            raise ValueError('Carbohydrate ring vertices must be physical beads')
        if ring.get('scale') != 1.15:
            raise ValueError('Carbohydrate ring constraints must use scale 1.15')
        site_name = ring.get('virtual_site')
        if mode == TC4:
            site = beads.get(site_name)
            if not site or site.get('virtual_site', {}).get('parents') != parents:
                raise ValueError('TC4 ring virtual-site parents disagree with the ring definition')
        elif site_name is not None:
            raise ValueError('Physical-only representation cannot retain a virtual-site ring reference')


def derive_representation(mapping, mode):
    """Return a deterministic validation snapshot without mutating ``mapping``."""
    validate_representation(mapping, TC4 if mode == PHYSICAL_ONLY else mode)
    result = deepcopy(mapping)
    if mode == TC4:
        return result
    result['beads'] = [bead for bead in result['beads'] if not bead.get('virtual_site')]
    for ring in result.get('rings', []):
        ring.pop('virtual_site', None)
    result['representation_mode'] = PHYSICAL_ONLY
    result['source_mapping_hash'] = candidate_identity(mapping)
    result['transformation'] = TRANSFORMATION
    validate_representation(result, PHYSICAL_ONLY)
    return result
