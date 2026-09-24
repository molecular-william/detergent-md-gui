"""Retention for explicitly marked short bonded-state validation jobs."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil


def cleanup(jobs, runs_root, delete_record, now=None, delete_with_cleanup=None):
    now = now or datetime.now(timezone.utc)
    grouped={}
    for job in jobs:
        if not job.get('temporary_validation'): continue
        key=job.get('bonded_state_id') or job.get('mapping_candidate') or 'unassigned'
        grouped.setdefault(key,[]).append(job)
    protected={j.get('reference_run_id') for j in jobs if j.get('reference_run_id')}; results=[]
    protected.update(j.get('resume_of') for j in jobs if j.get('status') in ('queued','waiting','running','cancelling'))
    for group in grouped.values():
        terminal=sorted((j for j in group if j.get('status') in ('completed','failed','cancelled')),
                        key=lambda j:j.get('ended_at') or j.get('created',''), reverse=True)
        protected.update(j['id'] for j in terminal[:5])
    for job in jobs:
        if not job.get('temporary_validation') or job['id'] in protected or job.get('status') not in ('completed','failed','cancelled'): continue
        stamp=job.get('ended_at') or job.get('created')
        try: age=now-datetime.fromisoformat(stamp)
        except (TypeError,ValueError): continue
        limit=timedelta(days=7 if job['status']=='completed' else 30)
        if age < limit: continue
        path=Path(runs_root)/job['id']
        if path.is_symlink(): results.append({'id':job['id'],'status':'blocked','reason':'symlink'});continue
        def remove_files():
            if path.exists(): shutil.rmtree(path)
        try:
            if delete_with_cleanup:
                delete_with_cleanup(job['id'], remove_files)
            else:
                remove_files(); delete_record(job['id'])
            results.append({'id':job['id'],'status':'deleted','age_days':age.days})
        except (OSError, ValueError) as exc: results.append({'id':job['id'],'status':'failed','reason':str(exc)})
    return results
