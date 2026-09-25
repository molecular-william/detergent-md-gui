from dashboard.web.routes import runs
from unittest.mock import patch

def test_micelle_build_api_persists_run(dashboard, tmp_path):
 with patch.object(dashboard.coordinator,'DATA',tmp_path/'jobs.sqlite3'),patch.object(dashboard.coordinator,'RUNS',tmp_path/'runs'):
  with patch.object(runs,'run_micelle_job',return_value={'status':'completed','returncode':0,'command':['micelle-build'],'stdout':'ok','stderr':''}):
   with dashboard.client as c:
    r=c.post('/api/micelle/build',json={'template':'x','aggregation_number':10,'seed':4}); assert r.status_code==201; assert r.json['method']=='micelle'; assert r.json['status']=='completed'
