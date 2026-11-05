"""What a protein-detergent run's card says before a stage has run.

The timeline is drawn from the static stage plan, so a queued empty-micelle or no-removal run would show protein
preparation, extension and final assessment as if they were still going to run. The run's own prepare-time record
(`skipped_stages`) wins when there is one, because it is the run's answer rather than a reader's preview of its
settings; neither substitutes for a stage's own record once it has run.
"""
from .execution.adapters.pdc import skipped_stages


def planned_skips(job, manifest=None):
    """Stages a pdc run will not run: the prepare-time record first, then the settings' own preview.

    The run card's timeline is drawn from the static stage plan, so a queued empty-micelle or no-removal run used to
    show protein preparation, extension and final assessment as if they were still going to run. A run that has been
    prepared also records its decision in the manifest's `skipped_stages`, with the adapter's own reason; that record
    wins, because it is the run's answer rather than a reader's preview of its settings. Both sides read
    `pdc.skipped_stages`, so the card and the prepare-time record cannot drift, and neither substitutes for a
    stage's own record once it has run.
    """
    if job.get('run_type') != 'pdc':
        return {}
    recorded = (manifest or {}).get('skipped_stages')
    recorded = ({str(name): str(reason) for name, reason in recorded.items()}
                if isinstance(recorded, dict) else {})
    settings = job.get('settings') if isinstance(job.get('settings'), dict) else {}
    # The settings' own preview, from the policy the prepare path records; the run's prepare-time record wins.
    skips = skipped_stages(settings, has_protein=bool(job.get('protein')))
    skips.update(recorded)
    return skips


