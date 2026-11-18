"""The stage settings a run recorded, and the AA progress bar's step segments.

One module owns both answers so the runs row and the Run view's Analysis tab cannot disagree about them:
the grouping of recorded values, the labels they are shown under, and the step arithmetic behind the bar.
Every answer is read-only. A key the run did not record is not shown, and no value is invented for it --
an older run simply has fewer values in its groups.

The shapes are the plan's (docs/plans/2026-11-16-stage-settings-and-progress.md, extended by
docs/plans/2026-11-17-stage-progress-all-run-types.md):

    groups   -> [{stage, label, fields: [{key, label, value, unit}]}]
    segments -> [{stage, label, kind, steps, fraction, skipped?}] or None
    payload  -> {groups, segments, total_steps}

Every run type with a segment table is divided into its *work* stages, in plan order: AA by step counts (its four
dynamics stages), CG, pdc and osmotic into equal-width stages because their stages have no comparable step count.
Setup, input and publication stages are not segments -- the run's timeline already shows them -- and a stage the
run type says will not run is flagged `skipped` so the bar can hatch it. A run type with no table keeps the single
fill.
"""
from __future__ import annotations

from .. import features
from ..execution import nonbonded, protocol
from ..execution.adapters import aa, cg

#: The reviewed aa-em-v1 step cap, for a run prepared before the minimization numbers were settings. The run's
#: recorded value wins; this only keeps an older run's bar whole instead of dropping its first segment.
MINIMIZATION_STEPS_FALLBACK = 20000

#: The AA stages the bar is divided into, in plan order: (plan stage name, short label, segment kind, setting
#: prefix). The stage name is what `views.progress` reports as `stage`, which is how the bar knows which segment
#: the run is in; the kind is the colour key the stylesheet draws.
AA_SEGMENTS = (
    ('AA minimization', 'Minimization', 'min', 'aa_minimization_'),
    ('AA NVT equilibration', 'NVT equilibration', 'nvt', 'aa_nvt_'),
    ('AA NPT equilibration', 'NPT equilibration', 'npt', 'aa_npt_'),
    ('AA NPT production', 'NPT production', 'production', 'aa_production_'),
)

#: The work stages a run type without step arithmetic is divided into, in plan order: (plan stage name, short label,
#: segment kind). The kinds are the colour keys `stage-settings.js` draws. Setup, input and publication stages are
#: deliberately absent: a CG run's `AA reference` is its pinned input, and pdc's preparation stages build one.
CG_SEGMENTS = (
    ('trajectory mapping', 'Mapping', 'mapping'),
    ('CG parameterization', 'Parameterization', 'fit'),
    ('CG simulation', 'Simulation', 'production'),
    ('CG assessment (ff_assess)', 'Assessment', 'assessment'),
    ('SASA analysis', 'SASA', 'analysis'),
)
PDC_SEGMENTS = (
    ('Energy minimisation', 'Minimisation', 'min'),
    ('NVT equilibration', 'NVT equilibration', 'nvt'),
    ('NPT equilibration', 'NPT equilibration', 'npt'),
    ('CG assessment MD', 'CG assessment MD', 'equilibration'),
    ('Micelle assessment', 'Micelle assessment', 'assessment'),
    ('CG extension MD', 'CG extension MD', 'production'),
    ('Final assessment', 'Final assessment', 'assessment'),
    ('Back-mapping (CG2AT2)', 'Back-mapping', 'backmap'),
)
OSMOTIC_SEGMENTS = (('Osmotic series', 'Osmotic series', 'production'),)

#: The shared Nonbonded and constraints section's keys, in the form's order. They are read back as one group because
#: the run applied one set to every dynamics leg: repeating them under each stage would invent a per-leg value.
SHARED_KEYS = tuple(dict.fromkeys(nonbonded.AA_FIELDS + nonbonded.CG_FIELDS))

#: One table per run type that draws a segmented bar. A type absent here keeps the single fill.
WORK_SEGMENTS = {'cg': CG_SEGMENTS, 'pdc': PDC_SEGMENTS, 'osmotic': OSMOTIC_SEGMENTS}


def groups(job, manifest):
    """The recorded settings, grouped by the stage that consumes them, in plan order.

    An AA run's three minimization numbers are their own group because the form edits them on their own; each
    dynamics leg groups its own prefix; everything else the run recorded is the run's own settings. A CG run
    groups the two CG legs and production's options, and puts the rest -- the atomistic half it consumes and its
    own execution settings -- under Run settings. Any other run type has one group, from its adapter's own
    vocabulary.
    """
    run_type = _run_type(job, manifest)
    settings = _settings(job, manifest)
    labels = _labels(run_type)
    if run_type == 'aa_only':
        claimed = _aa_groups(settings)
    elif run_type == 'cg':
        claimed = _cg_groups(settings)
    else:
        claimed = [('Run settings', 'Run settings', list(settings))]
    groups = [{'stage': stage, 'label': label, 'fields': _fields(keys, settings, labels)}
              for stage, label, keys in claimed]
    # Any recorded key no group claimed is still the run's, so it belongs where it is listed rather than dropped:
    # a value the run recorded must not disappear from the panel because a group table did not know it.
    claimed_keys = {key for _, _, keys in claimed for key in keys}
    remaining = [key for key in settings if key not in claimed_keys]
    if remaining and run_type in ('aa_only', 'cg'):
        groups.append({'stage': 'Run settings', 'label': 'Run settings',
                       'fields': _fields(remaining, settings, labels)})
    return [group for group in groups if group['fields']]


def segments(job, manifest):
    """(segments, total_steps) for the run's bar, or (None, None) when it cannot be drawn.

    Only the stages the run's own workflow plan contains are listed, so a plan without a stage does not claim part of
    the bar; the fractions are over the stages that are listed, and sum to one. An AA-only run's segment is
    weighted by its step count (the minimization's own cap, or a dynamics leg's duration over its timestep); a run
    type with no comparable step count gets equal-width segments and a null `steps`. A stage the run type says will
    not run carries `skipped`, and `total_steps` is null when the widths are not steps.
    """
    run_type = _run_type(job, manifest)
    plan = set(_plan_names(job, manifest))
    rows = []
    total = None
    if run_type == 'aa_only':
        settings = _settings(job, manifest)
        for stage, label, kind, prefix in AA_SEGMENTS:
            if stage not in plan:
                continue
            steps = _steps(settings, prefix)
            if steps is None:
                return None, None
            rows.append({'stage': stage, 'label': label, 'kind': kind, 'steps': steps})
        total = sum(row['steps'] for row in rows)
        if not rows or total <= 0:
            return None, None
        for row in rows:
            row['fraction'] = row['steps'] / total
    else:
        table = WORK_SEGMENTS.get(run_type)
        if table is None:
            return None, None
        rows = [{'stage': stage, 'label': label, 'kind': kind, 'steps': None}
                for stage, label, kind in table if stage in plan]
        if not rows:
            return None, None
        for row in rows:
            row['fraction'] = 1 / len(rows)
    skipped = _skipped(job, manifest)
    for row in rows:
        if row['stage'] in skipped:
            row['skipped'] = True
    return rows, total


def payload(job, manifest):
    """The detail payload: the groups, and the segments a bar is drawn from."""
    rows, total = segments(job, manifest)
    return {'groups': groups(job, manifest), 'segments': rows, 'total_steps': total}


def _aa_groups(settings):
    """(stage, label, keys) for an AA-only run, in the order the run's plan runs them."""
    return [('AA minimization', 'Energy minimization',
             ('aa_minimization_steps', 'aa_minimization_emtol', 'aa_minimization_emstep')),
            ('AA NVT equilibration', 'NVT equilibration', _prefixed(settings, 'aa_nvt_')),
            ('AA NPT equilibration', 'NPT equilibration', _prefixed(settings, 'aa_npt_')),
            ('AA NPT production', 'NPT production', _prefixed(settings, 'aa_production_')),
            ('Nonbonded and constraints', 'Nonbonded and constraints', _shared(settings))]


def _cg_groups(settings):
    """(stage, label, keys) for a CG run: the two CG legs, production's options, then everything else."""
    production = [key for key in settings
                  if key.startswith('cg_production_') or key in cg.PRODUCTION_OVERRIDES or key == 'nstxtcout']
    return [('CG minimization', 'CG minimization', _prefixed(settings, 'cg_minimization_')),
            ('CG equilibration', 'CG equilibration', _prefixed(settings, 'cg_equil_')),
            ('CG production', 'CG production', production),
            ('Nonbonded and constraints', 'Nonbonded and constraints', _shared(settings))]


def _shared(settings):
    """The recorded keys of the one Nonbonded and constraints section, in the form's order."""
    return [key for key in SHARED_KEYS if key in settings]


def _prefixed(settings, prefix):
    """The recorded keys under one stage's prefix, in the order the run recorded them."""
    return [key for key in settings if key.startswith(prefix)]


def _fields(keys, settings, labels):
    """One group's fields: only the keys this run recorded, labelled from its adapter's table when it has one."""
    return [{'key': key, 'label': labels.get(key) or key.replace('_', ' '), 'value': settings[key], 'unit': None}
            for key in keys if key in settings]


def _skipped(job, manifest):
    """The stages the run type says will not run, by name (the feature's own `planned_skips`)."""
    return features.planned_skips(job, manifest) or {}


def _settings(job, manifest):
    """The settings the run recorded: the manifest's, else the job row's, as one mapping."""
    recorded = manifest.get('settings') if isinstance(manifest, dict) else None
    if not isinstance(recorded, dict):
        recorded = job.get('settings') if isinstance(job, dict) else None
    return recorded if isinstance(recorded, dict) else {}


def _run_type(job, manifest):
    """The run type the record names; the manifest wins because it is the prepared run's own statement."""
    for source in (manifest, job):
        if isinstance(source, dict) and source.get('run_type'):
            return source['run_type']
    return None


def _plan_names(job, manifest):
    """The stage names the run's own workflow plan contains, oldest spelling (names only) included."""
    for source in (manifest, job):
        plan = source.get('stage_plan') if isinstance(source, dict) else None
        if isinstance(plan, (list, tuple)) and plan:
            return [entry[0] if isinstance(entry, (list, tuple)) and entry else getattr(entry, 'name', entry)
                    for entry in plan]
    return [name for name, _ in aa.STAGES]


def _labels(run_type):
    """The label each setting is shown under, from the adapter tables that advertise it."""
    if run_type == 'aa_only':
        tables = (aa.SETTING_SPECS, aa.CHOICE_SPECS)
    elif run_type == 'cg':
        tables = (aa.SETTING_SPECS, aa.CHOICE_SPECS, cg.SETTING_SPECS)
    else:
        try:
            adapter = protocol.adapter_for(run_type)
        except ValueError:
            return {}
        tables = (adapter.settings_specs(), adapter.choice_specs())
    labels = {}
    for table in tables:
        for key, spec in table.items():
            if isinstance(spec, (list, tuple)) and spec:
                labels[key] = spec[0]
    return labels


def _steps(settings, prefix):
    """The step count one stage runs, or None when the run recorded no number to compute it from."""
    if prefix == 'aa_minimization_':
        try:
            steps = int(settings.get('aa_minimization_steps', MINIMIZATION_STEPS_FALLBACK))
        except (TypeError, ValueError):
            return None
        return steps if steps > 0 else None
    scope = prefix[len('aa_'):-len('_')]
    try:
        duration = float(settings[f'aa_{scope}_ps'])
        timestep = float(settings[f'aa_{scope}_dt_fs'])
    except (KeyError, TypeError, ValueError):
        return None
    if duration <= 0 or timestep <= 0:
        return None
    return max(1, round(duration * 1000 / timestep))
