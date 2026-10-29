"""The built-system endpoint carries the model's own bonds, not a viewer's guess at them.

Measured: the route served `1_system/system.gro` through `pdc_view.system_pdb` with no topology. The writer already
gave every detergent molecule its own residue, but the file carried no CONECT records -- so NGL, which switches its
distance-based guess off only when a file has them (`inferBonds` defaults to `'all'`), drew 90 bonds on a frame the
model bonds 60 ways, head beads onto tail beads among them. The route now resolves the run's moleculetype the way
the route does (beside the stage, or in the stage that wrote it) and hands
it to the same writer.

This is the HTTP half of the fix; `test_pdc_bonds_browser.py` holds the panel's half.
"""
from __future__ import annotations

from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CLASSES, DDM_CONSTRAINTS, ddm_moleculetype, ddm_system_gro

JOB_ID = '00000000abcd'
MOLECULES = 3
PROTEIN_BEADS = 1
#: The stand-in element each class is written with -- the column the panel's viewer resolves a radius from.
ELEMENTS = {'R': 'C', 'S': 'N', 'T': 'H'}


def written_system(stage, *, topology=True, molecules=MOLECULES):
    """A stage holding the run's moleculetype and the system a build wrote."""
    if topology:
        (stage / 'detergent_CG.itp').write_text(ddm_moleculetype())
    (stage / 'system.gro').write_text(ddm_system_gro(molecules, protein_beads=PROTEIN_BEADS))


def built_run(dashboard, *, topology=True):
    """A pdc run whose setup stage holds a built system, registered the way the store registers one."""
    stage = dashboard.coordinator.RUNS / JOB_ID / 'stages' / '1_system'
    stage.mkdir(parents=True)
    written_system(stage, topology=topology)
    dashboard.coordinator.database().insert({'id': JOB_ID, 'run_type': 'pdc', 'status': 'running',
                                             'stage': '1_system', 'molecule_id': 'DDM',
                                             'created': '2026-10-13T00:00:00+00:00'})


def conect_pairs(lines):
    """The CONECT records of a PDB, as the bead serials they join."""
    return [(int(line[6:11]), int(line[11:16])) for line in lines if line.startswith('CONECT')]


def model_bonds():
    """The moleculetype's own bonds over the system, by the bead serial the writer gives each bead."""
    pairs = set()
    for molecule in range(MOLECULES):
        offset = PROTEIN_BEADS + molecule * len(DDM_BEADS)
        for first, second in (*DDM_BONDS, *DDM_CONSTRAINTS):
            pairs.add((min(offset + first, offset + second), max(offset + first, offset + second)))
    return pairs


def test_the_built_system_carries_the_models_bonds(dashboard):
    built_run(dashboard)

    response = dashboard.client.get(f'/api/pdc/{JOB_ID}/system.pdb')

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert sorted(conect_pairs(text.splitlines())) == sorted(model_bonds()), \
        'the file the route serves is not the model\'s bonds'
    assert "BONDS ARE THE MODEL'S OWN" in text, 'the file does not say where the bonds came from'


def test_the_built_system_gives_every_detergent_molecule_its_own_residue(dashboard):
    built_run(dashboard)

    lines = dashboard.client.get(f'/api/pdc/{JOB_ID}/system.pdb').get_data(as_text=True).splitlines()

    numbers = [line[22:26].strip() for line in lines if line.startswith('HETATM')]
    assert len(set(numbers)) == MOLECULES + 1, f'the protein and three detergents: {sorted(set(numbers))}'
    assert numbers.count(numbers[1]) == len(DDM_BEADS), 'the eleven beads of one detergent are one residue'


def test_the_built_system_states_each_beads_own_size_class(dashboard):
    """The file the Complexes panel draws from carries the model's three classes, not one stand-in for every bead.

    `ngl-beads.js` resolves a bead's radius from this column, so a file that says `C` everywhere draws every bead at
    the model's R -- 2.64 A for the sugar ring's small beads and the tail's regular ones alike. The protein's bead is
    not a bead the detergent's moleculetype sizes, so it keeps the stand-in, and that is the one class the file does
    not state.
    """
    built_run(dashboard)

    lines = dashboard.client.get(f'/api/pdc/{JOB_ID}/system.pdb').get_data(as_text=True).splitlines()

    elements = [line[76:78].strip() for line in lines if line.startswith('HETATM')]
    per_molecule = [ELEMENTS[DDM_CLASSES[name]] for name in DDM_BEADS]
    assert elements == ['C'] * PROTEIN_BEADS + per_molecule * MOLECULES
    assert elements.count('H') == 2 * MOLECULES, 'the two ring virtual sites are the tiny class'
    assert 'ELEMENTS ARE RADIUS STAND-INS' in '\n'.join(lines)


def test_a_run_with_no_topology_says_so_rather_than_leaving_a_viewer_to_guess(dashboard):
    """A moleculetype that is not there is a state to report, not one to pass over in silence."""
    built_run(dashboard, topology=False)

    text = dashboard.client.get(f'/api/pdc/{JOB_ID}/system.pdb').get_data(as_text=True)

    assert not conect_pairs(text.splitlines()), 'a bond nothing declares is a bond the picture invented'
    assert 'NO BONDS RECORDED' in text
