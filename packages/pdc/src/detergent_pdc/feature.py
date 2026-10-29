"""Protein-detergent simulations: the pdc run type, its panel API and the code paths it took over."""
from pathlib import Path

from dashboard import features
from dashboard.execution import protocol

from . import layout as pdc_layout
from . import legacy
from . import segments as pdc_segments
from . import topologies as pdc_topologies
from . import view as pdc_view
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


def _readiness(data, root):
    """A protein-detergent build is checked by its own adapter, not by the CG molecule question.

    Resolved through the protocol registry rather than `pdc.PROTOCOL` directly: the adapter is the one the registry
    holds, which is also the one a caller may have replaced.
    """
    return protocol.adapter_for('pdc').readiness({'protein': data.get('protein'),
                                                  'template': data.get('template'),
                                                  'project_root': str(root)})

FEATURE = features.Feature(
    name='pdc',
    blueprints=(pdc_routes.blueprint,),
    protocols={'pdc': lambda: pdc.PROTOCOL},
    prepare={'pdc': _prepare},
    create_settings={'pdc': _create_settings},
    readiness={'pdc': _readiness},
    layout=(pdc_layout.register, pdc_segments.register),
    # The pre-numbering stage directories a legacy run may hold at its root; `cli/migrate_run_layout.py` reads these
    # through the registry rather than keeping a pdc table of its own.
    legacy_stages={'pdc': legacy.LEGACY_STAGES},
    priority=20,
    # This feature's own browser surface: the Complexes panel's markup, sheet and module.
    templates=PACKAGE / 'templates',
    static=PACKAGE / 'static',
    styles=('pdc.css',),
    panel_modules={'pdc': ('js/pdc.js', 'createPdc')},
    # The shared panels' pdc behaviour: the protein-detergent New run form (`new-run-pdc.js`) and which run-view
    # structures are beads (`run-view-pdc.js`), registered onto the engine panels as they load.
    extension_modules=('js/new-run-pdc.js', 'js/run-view-pdc.js'),
    planned_skips=pdc_view.planned_skips,
    protein_topologies=pdc_topologies.read_protein_topologies,
    section=('simulations', {
        'slug': 'protein-detergent',
        'label': 'Protein-detergent simulations',
        'blurb': 'Set up and run a protein with its detergent, and read the results.',
        'tabs': ('runs', 'run-view', 'new-run', 'complexes'),
        'panel_labels': {'new-run': 'Protein-Detergent Simulations'},
        'run_types': ('pdc',),
        # This workspace's New run form and its heading sentence are this feature's fragments, and its gallery has
        # no figures to open yet: the shell renders what the record names, with no feature vocabulary of its own.
        'form_fragment': 'fragments/new-run-pdc.html',
        'form_blurb': 'fragments/new-run-pdc-blurb.html',
        'gallery_note': 'fragments/run-view-no-figures.html',
    }),
    panels=(('complexes', ('Complexes', '\u2b21')),),
    blurbs=(('complexes', 'build and inspect a system'),),
    tab_ids=(('complexes', 'pdc'),),
    # A prepared pdc run records the engine spelling `dashboard/execution/scripts/pdc_*.sh`; the files live here now,
    # and the resolver looks for them in this distribution before the engine's own scripts directory.
    code_prefixes=(('dashboard/execution/scripts/', 'detergent_pdc', 'execution/scripts/'),
                   ('dashboard/execution/adapters/', 'detergent_pdc', 'execution/adapters/')),
)
