"""Detergent validation: the single-molecule workspace, its panel APIs and the osmotic series."""
from pathlib import Path

from dashboard import features
from dashboard.execution import protocol

from . import evidence as evidence_tables
from . import kinds as kind_rows
from . import sugar_layout
from .execution.adapters import osmotic as osmotic_adapter
from .web.routes import analyses as analyses_routes
from .web.routes import bonded, osmotic, sugars, targets

PACKAGE = Path(__file__).resolve().parent


def _osmotic_protocol():
    """The osmotic adapter, imported when the registry asks for it rather than while this record is built."""
    from .execution.adapters import osmotic as adapter
    return adapter.PROTOCOL


def _prepare(job, root):
    """The arguments the osmotic adapter's `prepare` takes. Its settings are the series, not a molecule."""
    return {'settings': job.get('settings') or {}, 'mapping_snapshot': job.get('mapping_snapshot'),
            'molecule_id': job.get('molecule_id'), 'molecule_root': root / 'molecules'}


def _readiness(data, root):
    """An osmotic series is asked about itself: is the solute a sugar, are its files here, do the concentrations fit."""
    return protocol.adapter_for('osmotic').readiness({
        'molecule_id': data.get('molecule_id'), 'molecule_root': data.get('molecule_root') or root / 'molecules',
        'project_root': str(root), 'solute_root': data.get('solute_root'),
        'mapping_snapshot': data.get('mapping_snapshot'), 'settings': data.get('settings') or {}})


def _admission(data):
    """The payload contract of an osmotic condition, refused before a job record exists."""
    settings = data.get('settings') or data
    refused = osmotic_adapter.refuse_legacy_shape(settings)
    if refused:
        raise ValueError(refused)
    # The one thing a condition cannot be built without: the directory its own files are copied out of.
    if settings.get('solute_root') in (None, ''):
        raise ValueError('Osmotic runs require solute_root: the molecule, its topology and the water tile')
    # Not a shared-reference consumer: its solute comes from a mapping, which records the run it was made from.
    if data.get('reference_run_id') not in (None, ''):
        raise ValueError('An osmotic condition takes its solute from a mapping, not from a shared AA reference; '
                         'the mapping candidate records the run it was made from')


def _mapping_payload(c, jid, body):
    """The comparison's request, derived from the run itself.

    The analysis needs the mapping the run was built from, the molecule, and the topology it simulated. All three
    are already in the run's own record -- the mapping snapshot it consumed and `cg_names.final_itp` -- so the
    request carries no filesystem path a client could invent, and a run with no snapshot is refused rather than
    compared through someone else's.
    """
    job = c.lookup(jid)
    manifest = c.manifest_data(job)
    # The comparison needs the mapped trajectory and the terms a fit wrote, which only a revision-kind CG run has.
    # A reference or composition run simulated a model whose coordinates came from elsewhere, so comparing it through
    # a mapping would be comparing through someone else's assignment. A migrated `aa_cg` run states its kind in
    # `cg_model_kind`; a run written after the migration states it in `parameterization`.
    kind = ((manifest.get('parameterization') or {}).get('kind')
            or manifest.get('cg_model_kind') or 'revision')
    if job.get('run_type') != 'cg' or kind != 'revision':
        raise ValueError('The mapping comparison is defined for a CG run that consumed a parameterization revision')
    mapping = job.get('mapping_snapshot') or {}
    if not (isinstance(mapping, dict) and mapping.get('beads')):
        mapping = manifest.get('mapping_candidate') or {}
    if not (isinstance(mapping, dict) and mapping.get('beads')):
        raise ValueError('This run records no mapping snapshot to compare through')
    names = manifest.get('cg_names') or {}
    return {**(body or {}), 'mapping_snapshot': mapping,
            'molecule': job.get('molecule_id') or job.get('detergent'),
            'entry_name': (body or {}).get('entry_name'),
            'cg_topology': names.get('final_itp') or manifest.get('FINAL_ITP')}


FEATURE = features.Feature(
    name='validation',
    blueprints=(bonded.blueprint, osmotic.blueprint, targets.blueprint,
                analyses_routes.blueprint, sugars.blueprint),
    protocols={'osmotic': _osmotic_protocol},
    # What the Runs filter panel calls this feature's run types.
    run_type_labels={'osmotic': 'Osmotic series'},
    kinds=kind_rows.KINDS,
    code_roots=(('detergent_validation', Path(__file__).resolve().parent),),
    layout=(sugar_layout.register,),
    kind_payload={'carbohydrate-validation': analyses_routes.payload,
                  'mapping-consistency': _mapping_payload},
    evidence_sections=evidence_tables.EVIDENCE_SECTIONS,
    molecule_profiles=evidence_tables.MOLECULE_PROFILES,
    section=('validation', {
        'slug': 'detergent-validation',
        'label': 'Detergent validation',
        'blurb': "Build and check a detergent's coarse-grained model",
        'tabs': ('runs', 'run-view', 'new-run', 'bead-assignment', 'bond-interactions', 'combinations',
                 'osmotic-pressure'),
        'run_types': ('aa_only', 'cg', 'osmotic'),
        'panel_labels': {'new-run': 'Single Molecule Simulations'},
    }),
    panels=(('bead-assignment', ('Bead Assignment', '\u25ce')), ('bond-interactions', ('Bond Interactions', '\u21c4')),
            ('combinations', ('Combinations', '\u29c9')),
            ('osmotic-pressure', ('Osmotic Series', '\u25b3'))),
    tab_ids=(('bead-assignment', 'mappings'), ('bond-interactions', 'bonded'), ('combinations', 'compositions'),
             ('osmotic-pressure', 'osmotic-pressure')),
    code_prefixes=(('dashboard/execution/scripts/', 'detergent_validation', 'execution/scripts/'),
                   ('dashboard/execution/adapters/', 'detergent_validation', 'execution/adapters/')),
    prepare={'osmotic': _prepare},
    readiness={'osmotic': _readiness},
    admission={'osmotic': _admission},
    priority=10,
    # This feature's own browser surface: the Osmotic Series panel's markup, and the Run view analysis sections'
    # module and sheet (the Mapping Validation tab is retired; its per-run sections live in Run view).
    templates=PACKAGE / 'templates',
    static=PACKAGE / 'static',
    styles=('osmotic.css', 'run-view-mapping.css'),
    extension_modules=('js/run-view-mapping.js', 'js/run-view-mapping-map.js', 'js/run-view-sugar.js'),
    panel_modules={'osmotic-pressure': ('js/osmotic.js', 'createOsmoticSeries')},
)
