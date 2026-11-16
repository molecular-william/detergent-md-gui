"""`references.identity` reads the molecule and version a selection pinned, plus its chemistry.

A selection names its folder, not its bytes, so the identity is structural: two versions of one molecule must not share
it, and a chemistry change must not keep it. The map-of-digests spelling is gone with the digest-era selection.
"""
import hashlib
import json

from dashboard.analysis.runs import references

METADATA = {'force_field': 'charmm36-jul2022', 'water_model': 'tip3p', 'molecule_type': 'protein', 'net_charge': 0}


def expected(molecule_id='protein', version='v1', metadata=METADATA):
    body = {'molecule': {'id': molecule_id, 'version': version},
            'chemistry': {key: metadata[key] for key in ('force_field', 'water_model', 'molecule_type', 'net_charge')}}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def selection(version='v1', **changes):
    return {'id': changes.pop('id', 'protein'), 'version': version, 'metadata': {**METADATA, **changes}}


def test_the_identity_is_the_molecule_its_version_and_its_chemistry():
    assert references.identity(selection()) == expected()


def test_two_versions_of_one_molecule_do_not_share_an_identity():
    assert references.identity(selection('v1')) != references.identity(selection('v2'))


def test_two_molecules_do_not_share_an_identity():
    assert references.identity(selection(id='other')) != references.identity(selection())


def test_a_chemistry_change_moves_the_identity():
    assert references.identity(selection(net_charge=1)) != references.identity(selection())
    assert references.identity(selection(force_field='other')) != references.identity(selection())
