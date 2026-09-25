"""Thin dashboard adapter: the micelle package remains the scientific owner."""
import subprocess
import sys


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
 return {'status':'completed' if result.returncode==0 else 'failed','returncode':result.returncode,'command':cmd,'stdout':result.stdout,'stderr':result.stderr}
