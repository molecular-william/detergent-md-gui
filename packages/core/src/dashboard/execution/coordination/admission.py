"""Run-type admission rules shared by the queue and clone routes.

Raises ValueError for rejected payloads; the application-level error handler
converts that to HTTP 400 with a JSON body. Kept free of Flask imports so the
admission rules can be unit-tested and reused outside the web layer.
"""

AA_ONLY_FORBIDDEN = (
    'mapping_candidate',
    'mapping_snapshot',
    'reference_run_id',
    'cg_equil_ps',
    'cg_production_ps',
    'cg_seed',
    'sasa_probe_nm',
)

# The CG parameterizers a payload may name. Only the run types that *map* an atomistic structure choose one; a run whose
# topology comes from a mapping -- a protein-detergent build, a composition, an osmotic series -- has no choice to make.
# Asking every run for one is how a pdc job was refused with "Unsupported method" while its own adapter was ready.
CG_METHODS = ('fast_forward', 'bartender')


def validate_run_type(data):
    """Reject payloads whose run_type and fields are inconsistent."""
    if not hasattr(data, 'get'):
        raise ValueError('Expected an object')
    from ... import features
    from .. import protocol
    features.ensure()
    kind = data.get('run_type')
    # The published run types, not a second list: a feature's type is admitted when its distribution is installed, and
    # a name no adapter answers is refused here before it reaches the coordinator.
    if kind is not None and kind not in protocol.RUN_TYPES:
        raise ValueError('Unknown run type')
    rule = features.admission_for(kind)
    if rule is not None:
        rule(data)
        return
    if kind == 'osmotic':
        settings = data.get('settings') or data
        # **The shape first, and from the run type itself.** A payload that names no concentrations is the shape each
        # sibling job of the old series had, and it is refused here so a payload that reaches the coordinator without
        # passing through the series route cannot create one. The rule and its wording live in the adapter
        # (`refuse_legacy_shape`) and are imported rather than restated: one vocabulary, one refusal sentence.
        from ..adapters import osmotic as osmotic_adapter
        refused = osmotic_adapter.refuse_legacy_shape(settings)
        if refused:
            raise ValueError(refused)
        # The one thing a condition cannot be built without: the directory its own files are copied out of. Checked
        # here as well as in the route, because a payload can reach the coordinator without passing through it.
        if settings.get('solute_root') in (None, ''):
            raise ValueError('Osmotic runs require solute_root: the molecule, its topology and the water tile')
        # This run type is not a *shared reference* consumer: its solute comes from a mapping, and the mapping
        # candidate carries the provenance of the run it was made from. A reference id here would be resolved as if
        # the condition consumed the AA trajectory, which it does not -- so it is refused rather than ignored.
        if data.get('reference_run_id') not in (None, ''):
            raise ValueError('An osmotic condition takes its solute from a mapping, not from a shared AA reference; '
                             'the mapping candidate records the run it was made from')
        return
    if kind == 'cg_composition':
        if not data.get('composition_id'):
            raise ValueError('CG composition runs require composition_id')
        for key in ('molecule_id', 'molecule_snapshot', 'reference_run_id', 'mapping_candidate',
                    'mapping_snapshot'):
            if data.get(key) not in (None, ''):
                raise ValueError('CG composition runs cannot include AA or ordinary mapping inputs')
        return
    if kind in (None, 'aa_cg') and data.get('method') not in CG_METHODS:
        raise ValueError('Unsupported method')
    if kind != 'aa_only':
        return
    if any(data.get(key) not in (None, '') for key in AA_ONLY_FORBIDDEN):
        raise ValueError('AA-only cannot include CG inputs or a reference source')
    if data.get('method') not in (None, '', 'gromacs'):
        raise ValueError('AA-only uses GROMACS without a CG parameterizer')
