from datetime import datetime, timezone, timedelta
from dashboard.execution import temporary


def test_cleanup_protects_latest_five_and_applies_age_cutoffs(tmp_path):
    now=datetime.now(timezone.utc)
    jobs=[]
    for i in range(6):
        jobs.append({'id':f'{i:012x}','temporary_validation':True,'bonded_state_id':'s','status':'completed','ended_at':(now-timedelta(days=8)).isoformat()})
    deleted=[]
    result=temporary.cleanup(jobs,tmp_path,deleted.append,now)
    assert len(deleted)==1 and any(x['status']=='deleted' for x in result)
    recent={'id':'recent000001','temporary_validation':True,'bonded_state_id':'s','status':'completed','ended_at':(now-timedelta(days=1)).isoformat()}
    assert temporary.cleanup([recent],tmp_path,deleted.append,now)==[]
