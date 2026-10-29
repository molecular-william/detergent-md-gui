"""What a protein-detergent run's card says before a stage has run.

The timeline is drawn from the static stage plan, so a queued empty-micelle or no-removal run would show protein
preparation, extension and final assessment as if they were still going to run. The run's own prepare-time record
(`skipped_stages`) wins when there is one, because it is the run's answer rather than a reader's preview of its
settings; neither substitutes for a stage's own record once it has run.
"""

def planned_skips(job, manifest=None):
    """Stages a pdc run will not run: the prepare-time record first, then the settings' own preview.

    The run card's timeline is drawn from the static stage plan, so a queued empty-micelle or no-removal run used to
    show protein preparation, extension and final assessment as if they were still going to run. A run that has been
    prepared also records its decision in the manifest's `skipped_stages`, with the adapter's own reason; that record
    wins, because it is the run's answer rather than a reader's preview of its settings. Both are drawn from the same
    stage names the plan uses, and neither substitutes for a stage's own record once it has run.
    """
    if job.get('run_type') != 'pdc':
        return {}
    recorded = (manifest or {}).get('skipped_stages')
    recorded = ({str(name): str(reason) for name, reason in recorded.items()}
                if isinstance(recorded, dict) else {})
    settings = job.get('settings') if isinstance(job.get('settings'), dict) else {}
    protein = bool(job.get('protein'))
    skips = dict(recorded)
    if not protein:
        skips.setdefault('Protein preparation', 'empty micelle has no protein to prepare')
    elif not settings.get('prepare_protein', True):
        skips.setdefault('Protein preparation', 'protein preparation is off')
    if settings.get('minimisation_steps') == 0:
        skips.setdefault('Energy minimisation', 'minimisation steps are 0')
    if settings.get('nvt_ps') == 0:
        skips.setdefault('NVT equilibration', 'NVT duration is 0')
    if settings.get('npt_ps') == 0:
        skips.setdefault('NPT equilibration', 'NPT duration is 0')
    if not settings.get('remove_out_of_micelle', True):
        for name in ('Micelle assessment', 'CG extension MD', 'Final assessment'):
            skips.setdefault(name, 'out-of-micelle removal is off')
    if not protein or not settings.get('backmap', True):
        skips.setdefault('Back-mapping (CG2AT2)', 'empty micelle has no protein to align' if not protein
                         else 'back-mapping is off')
    return skips


