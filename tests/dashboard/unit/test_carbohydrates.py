"""Chemical grouping, virtual-site geometry and topology invariants."""
import copy
import itertools
import json
import tempfile
from pathlib import Path
import numpy as np
from dashboard.models import carbohydrates as sugars
from dashboard.models import mappings
from dashboard.models import draft_model
from dashboard.models import depiction
from dashboard.models import mapping_store


def test_ddm_canonical_ownership_and_coverage():
    c=mappings.automatic_candidate(mappings.molecule(), 'DDM'); physical=[b for b in c['beads'] if not b.get('virtual_site')]
    assert len(physical)==9 and len(c['beads'])==11
    assert sorted(a for b in physical for a in b['atoms'])==list(range(1,36))
    assert c['rings'][0]['carbons']==[14,34,32,19,16,17]
    # C1(21)-O(20)-C4(19): bridge belongs to acceptor B, not donor A.
    assert next(b for b in physical if 20 in b['atoms'])['name']=='S1B'
    assert next(b for b in physical if 21 in b['atoms'])['atoms']==[21,30,31]
    assert next(b for b in physical if b['name']=='S2B')['atoms']==[26,27,28,29]
    v=mappings.validate(c)
    assert v['checks_passed'] and v['mismatch']==-1 and v['virtual_sites']==2


def test_mapping_is_invariant_to_atom_renumbering_and_coordinates():
    s=mappings.molecule(); expected=mappings.automatic_candidate(s,'DDM')
    permutation={a['id']:1000-a['id'] for a in s['atoms']}
    changed=copy.deepcopy(s)
    for a in changed['atoms']: a['id']=permutation[a['id']]; a['xyz']=[-v for v in a['xyz']]
    changed['atoms'].reverse();changed['bonds']=[[permutation[a],permutation[b]] for a,b in s['bonds']]
    actual=mappings.automatic_candidate(changed,'renumbered')
    # Tail order may reverse; chemical groups must remain identical.
    groups=lambda c:{frozenset(b['atoms']) for b in c['beads'] if not b.get('virtual_site')}
    inverse={v:k for k,v in permutation.items()}
    assert groups(expected)=={frozenset(inverse[a] for a in group) for group in groups(actual)}


def test_scaled_geometry_preserves_links_and_virtual_cog():
    s=mappings.molecule();c=mappings.automatic_candidate(mappings.molecule(), 'DDM');names={b['name']:i for i,b in enumerate(c['beads'])}
    raw=sugars.coordinates(c,[a['xyz'] for a in s['atoms']]);scaled=sugars.coordinates(c,[a['xyz'] for a in s['atoms']],scaled=True)
    pairs=sugars.ring_pairs(c)
    for a,b in pairs:
        assert np.isclose(np.linalg.norm(scaled[a-1]-scaled[b-1]),1.15*np.linalg.norm(raw[a-1]-raw[b-1]))
    for a,b in sugars.physical_edges(c,s):
        if (a,b) not in pairs: np.testing.assert_allclose(scaled[a-1]-scaled[b-1],raw[a-1]-raw[b-1],atol=1e-10)
    for i,b in enumerate(c['beads']):
        if b.get('virtual_site'): np.testing.assert_allclose(scaled[i],scaled[[names[n] for n in b['virtual_site']['parents']]].mean(axis=0))


def test_topology_is_parseable_and_has_rigid_rings_and_link_torsion():
    from vermouth.gmx import read_itp
    from vermouth.forcefield import ForceField
    c=mappings.automatic_candidate(mappings.molecule(), 'DDM'); ff=ForceField('check');read_itp(draft_model.initial_topology(c).splitlines(),ff)
    b=ff.blocks['DDM']
    assert len(b.interactions['constraints'])==6
    assert len(b.interactions['virtual_sitesn'])==2
    assert len(b.interactions['exclusions'])==2
    assert len(b.interactions['dihedrals'])==1
    assert b.nodes[3]['mass']==0 and b.nodes[7]['mass']==0
    # The sugar-sugar link (2,5) has all four spanning angles.
    angles={tuple(x.atoms) for x in b.interactions['angles']}
    assert {(0,1,4),(2,1,4),(1,4,5),(1,4,6)}<=angles
    # Constraints/VS must be retained, not fitted by comment-driven FF.
    assert all(not x.meta.get('comment') for x in b.interactions['constraints'])
    draft_model.load(c)


def test_virtual_site_cannot_claim_atoms_or_use_missing_parent():
    import pytest
    c=mappings.automatic_candidate(mappings.molecule(), 'DDM');c['beads'][3]['atoms']=[1]
    with pytest.raises(ValueError,match='no exclusive'):mappings.validate(c)
    c=mappings.automatic_candidate(mappings.molecule(), 'DDM');c['beads'][3]['virtual_site']['parents'][0]='missing'
    with pytest.raises(ValueError,match='parent'):mappings.validate(c)


def test_save_export_retains_architecture(tmp_path,monkeypatch):
    monkeypatch.setattr(mapping_store, 'storage_root', lambda: tmp_path)
    c=mappings.automatic_candidate(mappings.molecule(), 'DDM');saved=mappings.save_draft(c)
    for k in ('rings','connections','provenance'):assert saved[k]==c[k]
    out=mappings.export_files(saved);model=json.loads(out['model.json'])
    assert model['rings']==c['rings'] and int(out['mapped.gro'].splitlines()[1])==11
    assert '[ B04 ]' not in out['mapping.ndx']
    assert 'stroke-dasharray="5 3"' in depiction.render(saved)


def test_surface_envelope_is_radius_and_probe_consistent():
    from dashboard.analysis.surfaces import envelope, PROBE
    v,f=envelope(np.array([[0.,0.,0.]]),[.230],spacing=.015)
    radii=np.linalg.norm(v,axis=1)
    assert np.max(np.abs(radii-(.230+PROBE)))<.002
    assert len(f)>0


def test_free_glucose_matches_official_fragment_types():
    s=mappings.molecule()
    ids={20,21,22,23,24,25,26,27,28,29,30,31}
    isolated={'atoms':[a for a in s['atoms'] if a['id'] in ids], 'bonds':[[a,b] for a,b in s['bonds'] if a in ids and b in ids]}
    c=mappings.automatic_candidate(isolated,'glucose')
    assert [b['type'] for b in c['beads']]==['SP4r','SP4r','SP1r','TC4']
    assert mappings.validate(c,isolated)['checks_passed']


def test_ff_dihedral_membership_controls_restricted_bending():
    import importlib.util
    path=Path('resources/parameterizers/fast_forward/fast_forward/interaction_fit.py')
    spec=importlib.util.spec_from_file_location('patched_fitter',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    fitter=module.InteractionFitter(constraint_converter=10000,max_dihedrals=10,temperature=300,precision=3,dihedral_scaling=1000)
    fitter.dihedrals={'dihedrals':{'a':[[0,1,2,3]],'b':[[4,5,6,7]]}}
    assert module._is_part_of_dihedral([0,1,2],fitter.dihedrals)
    assert module._is_part_of_dihedral([3,2,1],fitter.dihedrals)
    assert not module._is_part_of_dihedral([0,1,6],fitter.dihedrals)


def test_three_repeat_units_get_additional_orientation_torsion():
    from vermouth.gmx import read_itp
    from vermouth.forcefield import ForceField
    source=mappings.molecule(); ids=set(range(20,32)); atoms=[];bonds=[]
    for repeat in range(3):
        for a in source['atoms']:
            if a['id'] not in ids or (repeat and a['id']==20):continue
            a=copy.deepcopy(a);a['id']+=100*repeat;a['xyz'][1]-=8*repeat;atoms.append(a)
        for a,b in source['bonds']:
            if a in ids and b in ids and not(repeat and 20 in (a,b)):bonds.append([a+100*repeat,b+100*repeat])
    bonds += [[27,121],[127,221]]
    structure={'atoms':atoms,'bonds':bonds}
    c=mappings.automatic_candidate(structure,'trisaccharide')
    assert len(c['rings'])==3 and mappings.validate(c,structure)['checks_passed']
    ff=ForceField('three');read_itp(sugars.topology(c,structure).splitlines(),ff)
    assert len(ff.blocks['DDM'].interactions['dihedrals'])==3
