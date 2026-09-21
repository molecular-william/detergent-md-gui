import json
from pathlib import Path
from micelle.registry import load_template
from micelle.packing import golden_angle_directions,pack_micelle
from micelle.validation import validate_positions

def template(tmp):
 (tmp/'x.pdb').write_text('')
 (tmp/'x.itp').write_text('')
 p=tmp/'x.json';p.write_text(json.dumps({'name':'X','residue':'X','beads':[{'name':'B1'},{'name':'B2'}],'coordinates':'x.pdb','topology':'x.itp'}));return p

def test_seed_and_template(tmp_path):
 t=load_template(template(tmp_path)); assert t.name=='X'
 assert (golden_angle_directions(8,4)==golden_angle_directions(8,4)).all()
 c,_=pack_micelle(None,t,8,4); assert validate_positions(c,8)['valid']

def test_invalid_count(tmp_path):
 c,_=pack_micelle(None,None,4,1,radius=.1); assert not validate_positions(c,4,min_distance=.5)['valid']
