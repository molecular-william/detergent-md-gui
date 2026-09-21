from unittest.mock import patch
from micelle.gromacs import grompp
def test_missing_gromacs(tmp_path):
 with patch('micelle.gromacs.shutil.which',return_value=None): assert grompp('a','b','c',tmp_path)['status']=='unavailable'
