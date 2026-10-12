"""Dashboard adapter for a micelle build: the micelle package remains the scientific owner.

What this owns is the dashboard's side of a build -- the payload's shape, the command, and the run's own console log.
The route that queues one used to assemble that log from the two streams this returned, which put a web handler in
charge of what a build records.
"""
import subprocess
import sys
from pathlib import Path


def run_micelle_job(payload,run_dir):
 if not isinstance(payload,dict): raise ValueError('micelle payload must be an object')
 required=('template','aggregation_number','seed')
 missing=[k for k in required if k not in payload]
 if missing: raise ValueError('missing micelle fields: '+', '.join(missing))
 if not isinstance(payload['seed'],int) or payload['seed']<0: raise ValueError('seed must be a non-negative integer')
 cmd=[sys.executable,'-m','micelle','build','--template',str(payload['template']),'--aggregation-number',str(payload['aggregation_number']),'--seed',str(payload['seed']),'--output',str(run_dir)]
 if payload.get('protein'):cmd += ['--protein',str(payload['protein'])]
 if payload.get('ions') is not None:cmd += ['--ions',str(payload['ions'])]
 result=subprocess.run(cmd,text=True,capture_output=True)
 logs=Path(run_dir)/'logs';logs.mkdir(parents=True,exist_ok=True)
 (logs/'console.log').write_text(result.stdout+result.stderr)
 return {'status':'completed' if result.returncode==0 else 'failed','returncode':result.returncode,'command':cmd,'log':'logs/console.log','error':None if result.returncode==0 else result.stderr}
