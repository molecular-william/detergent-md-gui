"""Run a persisted screening plan serially through the dashboard coordinator.

Usage: python -m dashboard.cli.screen_candidates /absolute/path/plan.json
Restart with the same plan to resume. Unique labels recover accepted requests
after a client interruption. Stop on failure or cancellation; never auto-retry MD.
"""
import fcntl
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def api(route, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    with urlopen(Request('http://127.0.0.1:5000'+route, data=body, headers={'Content-Type':'application/json'}), timeout=60) as response:
        return json.load(response)


def save(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2)+'\n'); temp.replace(path)


def run(path):
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = json.loads(path.read_text())
        plan['status']='running';save(path,plan)
        try:
            for entry in plan['runs']:
                if not entry.get('id'):
                    matches=[j for j in api('/api/jobs') if j.get('label')==entry['request']['label']]
                    if len(matches)>1: raise ValueError('Ambiguous campaign label; inspect jobs before resuming')
                    if matches: entry['id']=matches[0]['id']
                    else:
                        while True:
                            try: entry['id']=api('/',entry['request'])['id'];break
                            except HTTPError as exc:
                                message=exc.read().decode()
                                if exc.code!=409 or 'capacity is busy' not in message: raise RuntimeError(message) from exc
                                time.sleep(10)
                    save(path,plan)
                print(f"Monitoring {entry['id']}: {entry['request']['label']}",flush=True)
                while True:
                    job=api('/api/jobs/'+entry['id']); entry['status']=job['status'];entry['stage']=job.get('stage');save(path,plan)
                    if job['status']=='completed': break
                    if job['status'] in ('failed','cancelled','cancelling'):
                        raise RuntimeError(f"{entry['id']}: {job['status']}: {job.get('error','')}")
                    time.sleep(10)
            plan['status']='completed'
        except Exception as exc:
            plan['status']='stopped';plan['error']=str(exc);raise
        finally: save(path,plan)


if __name__=='__main__': run(Path(sys.argv[1]).resolve())
