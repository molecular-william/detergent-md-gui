from dashboard.web.routes import runs
from unittest.mock import patch
from dashboard.app import default_coordinator as web

def test_micelle_build_api_persists_run(tmp_path):
 with patch.object(web,'DATA',tmp_path/'jobs.sqlite3'),patch.object(web,'RUNS',tmp_path/'runs'),patch.object(web,'WORKERS',{}),patch.object(web,'ANALYSIS_WORKERS',{}):
  with patch.object(runs,'run_micelle_job',return_value={'status':'completed','returncode':0,'command':['micelle-build'],'stdout':'ok','stderr':''}):
   with web.app.test_client() as c:
    r=c.post('/api/micelle/build',json={'template':'x','aggregation_number':10,'seed':4}); assert r.status_code==201; assert r.json['method']=='micelle'; assert r.json['status']=='completed'
