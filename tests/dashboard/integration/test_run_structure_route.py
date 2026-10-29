"""The run structure endpoint: a run's own `.gro`, with the run's own bonds written onto it.

Measured on this box: a `.gro` loaded into the vendored viewer comes back with a distance guess whatever
`inferBonds` says -- eight mapped beads came back with four guessed bonds -- so the panel's guard clears the store,
and a coarse-grained run's mapped model, the picture the run exists to publish, comes out as beads with no
connectivity. The run's own moleculetype under `stages/3_initial_CG/` states which beads are bonded; this route
writes those `[ bonds ]` and `[ constraints ]` as CONECT records over the file's own coordinates, through the same
writer the complex system view uses, and the client's CONECT branch draws them with its distance guess off.

This is the HTTP half. `test_run_view_browser.py` holds the panel's half: the bond count and the pairs read back
off the loaded component rather than off the parameters the panel sent.
"""
from __future__ import annotations

from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CONSTRAINTS, ddm_moleculetype, gro_atom_line

JOB_ID = '00000000feed'
MAPPED = 'stages/2_mapping/mapped.gro'
TOPOLOGY = 'stages/3_initial_CG/DDM.itp'
#: The same two files in the layout a protein-detergent run writes: its detergent's model in `1_system/` and the
#: extension's system under its own stage name.
PDC_JOB = '00000000dcdc'
PDC_STRUCTURE = 'stages/4_extension/prod/run.gro'
PDC_TOPOLOGY = 'stages/1_system/DDM.itp'


def conect_pairs(lines):
    """The CONECT records of a PDB, as the bead serials they join."""
    return [(int(line[6:11]), int(line[11:16])) for line in lines if line.startswith('CONECT')]


def model_pairs():
    return {(min(first, second), max(first, second)) for first, second in (*DDM_BONDS, *DDM_CONSTRAINTS)}


def mapped_gro(beads=DDM_BEADS):
    lines = ['coarse-grained solute', f'{len(beads):5d}']
    for index, bead in enumerate(beads, start=1):
        lines.append(gro_atom_line(1, 'DDM', bead, index, (index * 0.3, 0.0, 0.0)))
    lines.append('   4.00000   4.00000   4.00000')
    return '\n'.join(lines) + '\n'


def coarse_run(dashboard, *, topology=TOPOLOGY, beads=DDM_BEADS, manifest=None):
    """A run whose stages hold a mapped solute and, optionally, its moleculetype."""
    root = dashboard.coordinator.RUNS / JOB_ID
    target = root / MAPPED
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(mapped_gro(beads))
    if topology:
        path = root / topology
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ddm_moleculetype())
    if manifest is not None:
        (root / 'manifest.json').write_text(manifest)
    dashboard.coordinator.database().insert({'id': JOB_ID, 'run_type': 'aa_cg', 'status': 'running',
                                             'stage': '2_mapping', 'molecule_id': 'DDM',
                                             'created': '2026-10-14T00:00:00+00:00'})
    return root


def test_a_runs_mapped_structure_comes_back_with_the_models_own_bonds(dashboard):
    coarse_run(dashboard)

    response = dashboard.client.get(f'/api/jobs/{JOB_ID}/structure?path={MAPPED}')

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert sorted(conect_pairs(text.splitlines())) == sorted(model_pairs()), \
        'the file the route serves is not the model\'s bonds'
    assert "BONDS ARE THE MODEL'S OWN" in text, 'the file does not say where the bonds came from'


def test_a_run_whose_manifest_names_its_topology_uses_that_file(dashboard):
    """A fitted run leaves several `.itp` files; the manifest's own `FINAL_ITP` picks the one it simulated."""
    import json

    coarse_run(dashboard, topology='stages/3_initial_CG/DDM_initial.itp',
               manifest=json.dumps({'stages': [{'name': 'CG simulation',
                                                'environment': {'FINAL_ITP': 'DDM_initial.itp'}}]}))
    (dashboard.coordinator.RUNS / JOB_ID / TOPOLOGY).write_text(ddm_moleculetype())

    text = dashboard.client.get(f'/api/jobs/{JOB_ID}/structure?path={MAPPED}').get_data(as_text=True)

    assert sorted(conect_pairs(text.splitlines())) == sorted(model_pairs())


def test_a_run_with_no_topology_still_gets_its_coordinates_and_claims_no_bonds(dashboard):
    """A missing moleculetype is a state to report, not one to paper over with a viewer's guess."""
    coarse_run(dashboard, topology=None)

    text = dashboard.client.get(f'/api/jobs/{JOB_ID}/structure?path={MAPPED}').get_data(as_text=True)

    assert not conect_pairs(text.splitlines()), 'a bond nothing declares is a bond the picture invented'
    assert 'NO BONDS RECORDED' in text
    assert len([line for line in text.splitlines() if line.startswith('HETATM')]) == len(DDM_BEADS)


def test_a_protein_detergent_runs_structure_carries_the_detergents_bonds(dashboard):
    """A pdc run keeps its detergent's moleculetype in `1_system/`, not in `3_initial_CG/`.

    Measured on `00b9ae6db23f`: `stages/1_system/detergent_CG.itp` is the model its `system.top` includes, and the
    route answered `topology=None` for every one of that run's structures -- coordinates, no CONECT, while the panel
    drew the CG system with its distance guess off and said the bonds were under a directory the run does not have.
    """
    root = dashboard.coordinator.RUNS / PDC_JOB
    structure = root / PDC_STRUCTURE
    structure.parent.mkdir(parents=True)
    structure.write_text(mapped_gro())
    topology = root / PDC_TOPOLOGY
    topology.parent.mkdir(parents=True)
    topology.write_text(ddm_moleculetype())
    dashboard.coordinator.database().insert({'id': PDC_JOB, 'run_type': 'pdc', 'status': 'completed',
                                             'stage': 'Final assessment', 'molecule_id': 'DDM',
                                             'created': '2026-10-22T19:00:00+00:00'})

    response = dashboard.client.get(f'/api/jobs/{PDC_JOB}/structure?path={PDC_STRUCTURE}')

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert sorted(conect_pairs(text.splitlines())) == sorted(model_pairs()), \
        'a pdc structure is served without the detergent bonds its own run states'
    assert 'DDM.itp' in text, 'the file does not say which topology its bonds came from'


def _protein_moleculetype(name):
    return (f'[ moleculetype ]\n{name} 1\n\n[ atoms ]\n'
            '1 Q5 1 PRO BB 1 1\n2 TC4 1 PRO SC1 2 1\n\n[ bonds ]\n1 2 1 0.35 1000\n')


def test_a_protein_detergent_runs_structure_bonds_the_protein_chains_too(dashboard):
    """The route serves the protein's leading beads bonded by their own `1_system/cg/` moleculetypes.

    The protein beads are the leading atoms and their chains' topologies are the files that state their bonds; the
    detergent keeps its own CONECT beside them, and the protein block is checked against its `[ atoms ]` before any
    bond is drawn.
    """
    root = dashboard.coordinator.RUNS / PDC_JOB
    structure = root / PDC_STRUCTURE
    structure.parent.mkdir(parents=True)
    lines = ['protein-detergent system', f'{2 + len(DDM_BEADS):5d}']
    lines.append(gro_atom_line(1, 'PRO', 'BB', 1, (0.0, 0.0, 0.0)))
    lines.append(gro_atom_line(1, 'PRO', 'SC1', 2, (0.3, 0.0, 0.0)))
    for serial, bead in enumerate(DDM_BEADS, start=3):
        lines.append(gro_atom_line(2, 'DDM', bead, serial, (serial * 0.3, 1.0, 0.0)))
    lines.append('   8.00000   8.00000   8.00000')
    structure.write_text('\n'.join(lines) + '\n')
    topology = root / PDC_TOPOLOGY
    topology.parent.mkdir(parents=True)
    topology.write_text(ddm_moleculetype())
    (root / 'stages/1_system/cg').mkdir(parents=True)
    (root / 'stages/1_system/cg/molecule_0.itp').write_text(_protein_moleculetype('molecule_0'))
    dashboard.coordinator.database().insert({'id': PDC_JOB, 'run_type': 'pdc', 'status': 'completed',
                                             'stage': 'CG assessment MD', 'molecule_id': 'DDM',
                                             'created': '2026-10-22T19:00:00+00:00'})

    text = dashboard.client.get(f'/api/jobs/{PDC_JOB}/structure?path={PDC_STRUCTURE}').get_data(as_text=True)
    pairs = conect_pairs(text.splitlines())

    assert (1, 2) in pairs, 'the protein chain was served unbonded'
    assert len(pairs) == 1 + len(DDM_BONDS) + len(DDM_CONSTRAINTS), f'the wrong bond set: {pairs}'
    assert "PROTEIN BONDS ARE THE MODEL'S OWN, NOT GUESSED" in text


def test_a_path_that_leaves_the_run_is_a_404(dashboard):
    """A path is run-relative and nothing else: no other directory is reachable through this route."""
    coarse_run(dashboard)

    for relative in ('../../etc/passwd', 'stages/../../../outside.gro', 'stages/2_mapping/mapped.gro/../../../../x'):
        response = dashboard.client.get(f'/api/jobs/{JOB_ID}/structure?path={relative}')
        assert response.status_code == 404, (relative, response.status_code)


def test_a_file_that_is_not_a_gro_and_a_file_that_is_not_there_are_refused(dashboard):
    """A `.pdb` carries its own records and is served by the artifact route; a missing file is a missing file."""
    root = coarse_run(dashboard)
    (root / 'stages/2_mapping/mapped.pdb').write_text('END\n')

    assert dashboard.client.get(
        f'/api/jobs/{JOB_ID}/structure?path=stages/2_mapping/mapped.pdb').status_code == 400
    assert dashboard.client.get(
        f'/api/jobs/{JOB_ID}/structure?path=stages/2_mapping/nothing.gro').status_code == 404
    assert dashboard.client.get(f'/api/jobs/{JOB_ID}/structure').status_code == 400


def test_an_unknown_run_is_a_404(dashboard):
    assert dashboard.client.get('/api/jobs/ffffffffffff/structure?path=stages/2_mapping/mapped.gro').status_code == 404


def test_a_runs_mapped_structure_carries_the_fragments_its_mapping_states(dashboard):
    """The ring letters on the single structure are the ones a frame series of the same run carries.

    Both are written from the run's own `2_mapping/model.json`, so a reader fitting a series on one ring sees the
    same letter here -- one document, one set of names, whichever picture is on screen.
    """
    import json

    root = coarse_run(dashboard)
    mapping = root / 'stages/2_mapping/model.json'
    mapping.write_text(json.dumps({'name': 'fixture', 'beads': [
        {'export_name': 'B01', 'letter': 'A', 'size': 'S'}, {'export_name': 'B02', 'letter': 'A', 'size': 'S'}]}))

    text = dashboard.client.get(f'/api/jobs/{JOB_ID}/structure?path={MAPPED}').get_data(as_text=True)

    assert "CHAIN LETTERS CARRY THE MODEL'S OWN FRAGMENTS" in text, 'the file does not say what the letters are'
    assert 'A 2 beads (B01, B02)' in text, text.splitlines()[0]
    assert {line[21] for line in text.splitlines() if line.startswith('HETATM')} == {'A'}
    mapping.unlink()
    plain = dashboard.client.get(f'/api/jobs/{JOB_ID}/structure?path={MAPPED}').get_data(as_text=True)
    assert 'CHAIN LETTERS' not in plain, 'a run whose mapping is gone still claims fragments'
