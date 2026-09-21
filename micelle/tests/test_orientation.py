import numpy as np
from micelle.orientation import infer_orientation
def test_opm_precedence():
 r=infer_orientation(np.eye(3),opm={'axis':(0,0,2)},explicit_axis=(1,0,0));assert r.method=='opm';assert np.allclose(r.axis,(0,0,1))
def test_heuristic(): assert infer_orientation(np.random.default_rng(2).normal(size=(20,3))).method=='heuristic'
