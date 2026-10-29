"""Detergent validation: the single-molecule workspace, its panel APIs and the osmotic series."""
from pathlib import Path

from dashboard import features
from dashboard.execution import protocol

from . import evidence as evidence_tables
from . import kinds as kind_rows
from .execution.adapters import osmotic as osmotic_adapter
from .web.routes import analyses as analyses_routes
from .web.routes import bonded, osmotic, refinement, targets

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


def _stop_reason(settings):
    """Why a sibling was cancelled, naming the condition that ended the series where its molality is known."""
    molality = settings.get('osmotic_molality')
    named = f'{float(molality):g} molal' if isinstance(molality, (int, float)) else 'a sibling condition'
    return f'Series stopped: the {named} condition ended failed, so this condition was not run'


def _on_run_failed(coordinator, job):
    """End a series when one condition ends failed and the series asked to stop.

    A sibling the coordinator owns a worker for is stopped through that worker's cancel event -- only the current
    worker owns its subprocess groups, and a stored PID must never be signalled. A queued sibling this server will
    not start is marked cancelled and says why. Either way the conditions that did not run are recorded on the
    failed run as the gap they are.
    """
    with coordinator.JOBS_LOCK:
        job = coordinator.lookup(job['id'])
        if job.get('run_type') != 'osmotic' or job.get('status') != 'failed':
            return []
        settings = job.get('settings') or {}
        series_id = settings.get('series_id')
        if not series_id or str(settings.get('series_on_failure') or 'carry_on') != 'stop':
            return []
        stopped = []
        for sibling in coordinator.database().all():
            if sibling.get('id') == job['id']:
                continue
            if (sibling.get('settings') or {}).get('series_id') != series_id:
                continue
            if sibling.get('status') not in ('queued', 'waiting', 'running'):
                continue
            if sibling['id'] in coordinator.WORKERS:
                coordinator.WORKERS[sibling['id']].cancel.set()
                coordinator.database().update(sibling['id'], status='cancelling')
            elif sibling.get('status') in ('queued', 'waiting'):
                coordinator.database().update(sibling['id'], status='cancelled', stage='Series stopped',
                                              ended_at=coordinator.now(), error=_stop_reason(settings))
            else:
                continue
            stopped.append({'id': sibling['id'], 'molality': (sibling.get('settings') or {}).get('osmotic_molality')})
        if stopped:
            coordinator.database().update(job['id'], series_stopped=stopped)
        return stopped


FEATURE = features.Feature(
    name='validation',
    blueprints=(bonded.blueprint, osmotic.blueprint, refinement.blueprint, targets.blueprint,
                analyses_routes.blueprint),
    protocols={'osmotic': _osmotic_protocol},
    kinds=kind_rows.KINDS,
    code_roots=(('detergent_validation', Path(__file__).resolve().parent),),
    kind_payload={'carbohydrate-validation': analyses_routes.payload},
    evidence_sections=evidence_tables.EVIDENCE_SECTIONS,
    molecule_profiles=evidence_tables.MOLECULE_PROFILES,
    section=('validation', {
        'slug': 'detergent-validation',
        'label': 'Detergent validation',
        'blurb': "Build and check a detergent's coarse-grained model",
        'tabs': ('runs', 'run-view', 'new-run', 'bead-assignment', 'bond-interactions', 'combinations',
                 'mapping-validation', 'osmotic-pressure'),
        'run_types': ('aa_only', 'aa_cg', 'cg_composition', 'osmotic'),
        'panel_labels': {'new-run': 'Single Molecule Simulations'},
    }),
    panels=(('bead-assignment', ('Bead Assignment', '\u25ce')), ('bond-interactions', ('Bond Interactions', '\u21c4')),
            ('combinations', ('Combinations', '\u29c9')), ('mapping-validation', ('Mapping Validation', '\u2713')),
            ('osmotic-pressure', ('Osmotic Series', '\u25b3'))),
    blurbs=(('bead-assignment', 'the CG mapping editor'),
            ('bond-interactions', 'fitted terms, and the cross-check against the reference'),
            ('combinations', 'building a system from several molecules'),
            ('mapping-validation', 'a mapping against its reference, and across molecules'),
            ('osmotic-pressure', 'a sugar concentration series: set one up, and read the series as it stands')),
    tab_ids=(('bead-assignment', 'mappings'), ('bond-interactions', 'bonded'), ('combinations', 'compositions'),
             ('mapping-validation', 'validation'), ('osmotic-pressure', 'osmotic-pressure')),
    code_prefixes=(('dashboard/execution/scripts/', 'detergent_validation', 'execution/scripts/'),
                   ('dashboard/execution/adapters/', 'detergent_validation', 'execution/adapters/')),
    prepare={'osmotic': _prepare},
    readiness={'osmotic': _readiness},
    admission={'osmotic': _admission},
    priority=10,
    # This feature's own browser surface: the Mapping Validation and Osmotic Series panels' markup, sheet and modules.
    templates=PACKAGE / 'templates',
    static=PACKAGE / 'static',
    styles=('osmotic.css',),
    panel_modules={'validation': ('js/mapping-validation.js', 'createMappingValidation'),
                   'osmotic-pressure': ('js/osmotic.js', 'createOsmoticSeries')},
    on_run_failed=_on_run_failed,
)
