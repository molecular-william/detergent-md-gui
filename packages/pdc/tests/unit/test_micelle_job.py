from unittest.mock import patch

from dashboard.execution.adapters.micelle import run_micelle_job


def test_adapter_requires_seed(tmp_path):
 try: run_micelle_job({'template':'x','aggregation_number':2},tmp_path)
 except ValueError as e: assert 'seed' in str(e)
 else: assert False
def test_adapter_delegates(tmp_path):
 with patch('dashboard.execution.adapters.micelle.subprocess.run') as run:
  run.return_value.returncode=0;run.return_value.stdout='';run.return_value.stderr=''
  r=run_micelle_job({'template':'x','aggregation_number':2,'seed':3},tmp_path)
  assert r['status']=='completed';assert '-m' in r['command']


def test_adapter_writes_the_builds_console_log(tmp_path):
 """The build's own output belongs to the build's adapter, not to the route that queued it.

 The route assembled `logs/console.log` from the two streams the adapter handed back, which put a web handler in
 charge of what a micelle build records. It is the build's output, and the adapter is the thing that knows it.
 """
 with patch('dashboard.execution.adapters.micelle.subprocess.run') as run:
  run.return_value.returncode=0;run.return_value.stdout='build ok\n';run.return_value.stderr='warning\n'
  r=run_micelle_job({'template':'x','aggregation_number':2,'seed':3},tmp_path)
 log = tmp_path/'logs'/'console.log'
 assert log.is_file(), 'the adapter writes the console log itself'
 assert 'build ok' in log.read_text() and 'warning' in log.read_text(), 'both streams, in order'
 assert r['log'] == 'logs/console.log', 'and says where it put it'
