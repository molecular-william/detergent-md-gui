from unittest.mock import patch
from dashboard.execution.micelle_job import run_micelle_job
def test_adapter_requires_seed(tmp_path):
 try: run_micelle_job({'template':'x','aggregation_number':2},tmp_path)
 except ValueError as e: assert 'seed' in str(e)
 else: assert False
def test_adapter_delegates(tmp_path):
 with patch('dashboard.execution.micelle_job.subprocess.run') as run:
  run.return_value.returncode=0;run.return_value.stdout='';run.return_value.stderr=''
  r=run_micelle_job({'template':'x','aggregation_number':2,'seed':3},tmp_path)
  assert r['status']=='completed';assert '-m' in r['command']
