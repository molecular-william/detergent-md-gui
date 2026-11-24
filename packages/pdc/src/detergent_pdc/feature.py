"""Protein-detergent simulations: the pdc run type, its panel API and the code paths it took over."""
from pathlib import Path

from dashboard import features
from dashboard.execution import protocol
from flask import abort

from . import kinds as pdc_kinds
from . import layout as pdc_layout
from . import legacy
from . import segments as pdc_segments
from . import topologies as pdc_topologies
from . import view as pdc_view
from .analysis.runs import structure as structure_analysis
from .conformations import cleanup as conformation_cleanup
from .execution.adapters import pdc
from .web.routes import pdc as pdc_routes

PACKAGE = Path(__file__).resolve().parent


def _prepare(job, root):
    """The arguments the pdc adapter's `prepare` takes: a protein, a template and a mapping."""
    return {'protein': job.get('protein'), 'template': job.get('template'),
            'mapping_candidate': job.get('mapping_candidate') or job.get('mapping_snapshot'),
            'settings': job.get('settings'), 'project_root': str(root)}


def _create_settings(settings, job):
    """Generic normalization applies protein-only defaults before the adapter knows the protein.

    `prepare_protein` defaults to true, so an empty-micelle job carried it and `pdc.prepare` refused the
    job it had just accepted -- the failure measured on `bbda8d632309`. The job record is what a retry
    clones, so the rule belongs here, before the record is written.
    """
    if job.get('protein'):
        return settings
    return {**settings, 'prepare_protein': False}


def _box_warnings(payload):
    """The stated starting box dimensions the build would have to widen, by the preview's own rule.

    Admission asks this question at queue time, so a run the reader cannot fit cannot be admitted (a stale preset's
    14 nm box was refused only at system preparation before). The answer comes from 'pdc_preview.preview', the same
    placement the preview card shows: it caches the coarse-grained protein, and an unanswerable question (a missing
    tool, a protein that cannot be coarse-grained, a template no run could use) is not a reason to refuse a queue --
    the run's own readiness and stages report those.
    """
    from dashboard import paths
    from dashboard.execution import tools

    from .execution import pdc_preview
    from .execution.adapters import pdc as pdc_adapter
    from .execution.adapters import pdc_placement, pdc_preparation

    # The queue speaks the panel's spelling for the two aliased choices; validate_payload reads the adapter's.
    supplied = dict(payload)
    if supplied.get('seed') in (None, '') and supplied.get('pdc_seed') not in (None, ''):
        supplied['seed'] = supplied['pdc_seed']
    if supplied.get('placement_mode') in (None, '') and supplied.get('pdc_placement_mode') not in (None, ''):
        supplied['placement_mode'] = supplied['pdc_placement_mode']
    choices = pdc_adapter.validate_payload(supplied)
    template = payload.get('template')
    executable = tools.tool_path('martinize2')
    if not template or not executable:
        return []

    def number(name, default=None):
        value = payload.get(name, default)
        if value in (None, ''):
            return None if default is None else default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    state = paths.current()
    defaults = pdc_adapter.DEFAULTS
    answer = pdc_preview.preview(
        project_root=str(state.project_root), cache_root=state.workspace / pdc_preview.CACHE_DIRECTORY,
        template=template, seed=choices['seed'], protein=payload.get('protein') or None,
        chains=choices['protein_chains'], mapping=payload.get('mapping_candidate') or None,
        molecule_id=payload.get('molecule_id') or None,
        aggregation_number=choices['aggregation_number'], placement_mode=choices['placement_mode'],
        box_margin_nm=number('box_margin_nm', float(defaults['box_margin_nm'])),
        initial_z_nm=number('initial_z_nm'), initial_x_nm=number('initial_x_nm'),
        initial_y_nm=number('initial_y_nm'), radius_nm=float(pdc_placement.DEFAULT_RADIUS_NM),
        executable=executable, prepare_protein=choices['prepare_protein'],
        prepare_executable=tools.tool_path(pdc_preparation.TOOL), workspace=state.workspace,
        belt_gap_nm=number('belt_gap_nm', float(defaults['belt_gap_nm'])),
        min_body_gap_nm=number('min_body_gap_nm', float(defaults['min_body_gap_nm'])),
        belt_axial_window_nm=number('belt_axial_window_nm', float(defaults['belt_axial_window_nm'])),
        belt_vertical_spread=number('belt_vertical_spread', float(defaults['belt_vertical_spread'])),
        belt_vertical_half_nm=number('belt_vertical_half_nm'),
        belt_offset_nm=number('belt_offset_nm', float(defaults['belt_offset_nm'])),
        # The library changes which bodies are stamped, never the belt's measured reach or the cell it needs.
        conformation_library=None)
    return list((answer.get('basis') or {}).get('box_notes') or [])


def _admission(data):
    """Refuse a queued pdc run whose stated starting box cannot hold the system it describes.

    A box the build would have to widen is a cell the reader asked for and cannot have: the run is refused here, at
    the queue, with the sentence the preview card shows under the box -- rather than admitted and widened, or admitted
    and failed at system preparation.
    """
    if not isinstance(data, dict):
        return
    if all(data.get('initial_' + axis + '_nm') in (None, '') for axis in 'xyz'):
        return
    try:
        notes = _box_warnings(data)
    except Exception:  # noqa: BLE001 -- an unanswerable box question must not become a 500 at the queue
        # The box question could not be answered; the run's own readiness and stages say why, and admission does not
        # turn an unrelated refusal into a queue refusal.
        return
    if notes:
        raise ValueError('the starting box cannot hold this system: ' + '; '.join(notes)
                         + '. Clear the box fields to derive them, or state larger values.')


def _readiness(data, root):
    """A protein-detergent build is checked by its own adapter, not by the CG molecule question.

    Resolved through the protocol registry rather than `pdc.PROTOCOL` directly: the adapter is the one the registry
    holds, which is also the one a caller may have replaced.
    """
    return protocol.adapter_for('pdc').readiness({'protein': data.get('protein'),
                                                  'template': data.get('template'),
                                                  'project_root': str(root)})


def structure_measurement(c, jid, body):
    """The thresholds a `pdc-structure` attempt is measured with, validated by the producer's own contract.

    The queue route's signature is `(coordinator, job_id, body)`, the producer publishes one callable that takes the
    body alone, so this is the adapter between them -- not a second copy of the ranges. A threshold the producer
    refuses is the caller's malformed request (400), never a 500 out of the validator.
    """
    try:
        return structure_analysis.validate_payload(body or {})
    except ValueError as error:
        abort(400, str(error))


FEATURE = features.Feature(
    name='pdc',
    blueprints=(pdc_routes.blueprint,),
    protocols={'pdc': lambda: pdc.PROTOCOL},
    # The analyses this feature owns: the run view's Structure and interactions section queues and reads them.
    kinds=pdc_kinds.KINDS,
    # What the Runs filter panel calls this run type.
    run_type_labels={'pdc': 'Protein-detergent'},
    admission={'pdc': _admission},
    prepare={'pdc': _prepare},
    create_settings={'pdc': _create_settings},
    readiness={'pdc': _readiness},
    layout=(pdc_layout.register, pdc_segments.register),
    # The pre-numbering stage directories a legacy run may hold at its root; `cli/migrate_run_layout.py` reads these
    # through the registry rather than keeping a pdc table of its own.
    legacy_stages={'pdc': legacy.LEGACY_STAGES},
    priority=20,
    # This feature's own browser surface: the PDC analysis panel's markup, sheet and module.
    templates=PACKAGE / 'templates',
    static=PACKAGE / 'static',
    styles=('pdc.css',),
    panel_modules={'pdc': ('js/pdc-analysis.js', 'createPdcAnalysis')},
    # The thresholds `pdc-structure` records are a queue-time contract too: the producer's ranges decide, so a bad
    # value is refused before an attempt exists.
    kind_payload={'pdc-structure': structure_measurement},
    # The shared panels' pdc behaviour: the protein-detergent New run form (`new-run-pdc.js`), which run-view
    # structures are beads (`run-view-pdc.js`), and the Structure and interactions section
    # (`run-view-pdc-analysis.js`), registered onto the engine panels as they load.
    extension_modules=('js/new-run-pdc.js', 'js/run-view-pdc.js', 'js/run-view-pdc-analysis.js'),
    planned_skips=pdc_view.planned_skips,
    protein_topologies=pdc_topologies.read_protein_topologies,
    # A stored detergent-shape library records the mapping it was built from, so deleting that mapping (or the
    # parameterization that belongs to it) removes the shapes made from it; the registry asks, this deletes.
    mapping_deletions=(conformation_cleanup.forget_mapping,),
    section=('simulations', {
        'slug': 'protein-detergent',
        'label': 'Protein-detergent simulations',
        'blurb': 'Set up and run a protein with its detergent, and read the results.',
        'tabs': ('runs', 'run-view', 'new-run', 'complexes'),
        'panel_labels': {'new-run': 'Protein-Detergent Simulations'},
        'run_types': ('pdc',),
        # This workspace's New run form and its heading sentence are this feature's fragments: the shell renders what
        # the record names, with no feature vocabulary of its own.
        'form_fragment': 'fragments/new-run-pdc.html',
        'form_blurb': 'fragments/new-run-pdc-blurb.html',
    }),
    panels=(('complexes', ('PDC analysis', '\u2b21')),),
    tab_ids=(('complexes', 'pdc'),),
    # A prepared pdc run records the engine spelling `dashboard/execution/scripts/pdc_*.sh`; the files live here now,
    # and the resolver looks for them in this distribution before the engine's own scripts directory.
    code_prefixes=(('dashboard/execution/scripts/', 'detergent_pdc', 'execution/scripts/'),
                   ('dashboard/execution/adapters/', 'detergent_pdc', 'execution/adapters/')),
)
