"""The run structure view: a run's own `.gro` with the run's own bonds written onto it.

A `.gro` carries coordinates and no bond records, and this vendored viewer's GRO parser guesses them from distances
whatever `inferBonds` says -- so a coarse-grained run drawn straight from its stage files comes out either with a
distance guess or, once the client clears the store, as loose beads with no connectivity at all. The run's own
moleculetype states which beads are bonded, and this is the writer that puts it on the picture -- through the same
two functions the complex system view uses (`pdc_view.molecule_bonds` / `system_pdb`), so a run's picture and a
complex's cannot disagree about what a bond is.

The claims worth pinning are the ones a picture would hide: the CONECT set is the moleculetype's own and never a
superset, a structure whose beads are not the moleculetype's comes back unbonded **with the reason in the file**,
and a file this writer cannot read is an error rather than a half-drawn structure. The topology is located by the
run's own layout rule, so nothing here spells a stage directory by hand.
"""
from __future__ import annotations

import pytest
from werkzeug.exceptions import NotFound

from dashboard.execution.adapters import pdc_view
from dashboard.web.routes.runs import run_topology, structure_target
from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CONSTRAINTS, ddm_moleculetype, gro_atom_line

MAPPED = 'stages/2_mapping/mapped.gro'
TOPOLOGY = 'stages/3_initial_CG/DDM.itp'


def coarse_run(tmp_path, *, beads=DDM_BEADS, topology=TOPOLOGY, residue='DDM'):
    """A run directory holding one coarse-grained solute and, optionally, its moleculetype."""
    stage = tmp_path / 'stages/2_mapping'
    stage.mkdir(parents=True, exist_ok=True)
    lines = ['coarse-grained solute', f'{len(beads):5d}']
    for index, bead in enumerate(beads, start=1):
        lines.append(gro_atom_line(1, residue, bead, index, (index * 0.3, 0.0, 0.0)))
    lines.append('   4.00000   4.00000   4.00000')
    (stage / 'mapped.gro').write_text('\n'.join(lines) + '\n')
    if topology:
        path = tmp_path / topology
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ddm_moleculetype())
    return tmp_path


def conect_pairs(text):
    """The CONECT records of a PDB, as the bead serials they join."""
    return [(int(line[6:11]), int(line[11:16])) for line in text.splitlines() if line.startswith('CONECT')]


def model_pairs():
    return {(min(first, second), max(first, second)) for first, second in (*DDM_BONDS, *DDM_CONSTRAINTS)}


def test_the_conect_set_is_the_moleculetypes_own_bonds_and_never_a_superset(tmp_path):
    """Ten records on disk, ten bonds drawn: four `[ bonds ]` + six `[ constraints ]`, and nothing else."""
    run = coarse_run(tmp_path)
    topology = pdc_view.read_moleculetype(run / TOPOLOGY)

    text = pdc_view.structure_pdb(run / MAPPED, topology=topology)

    pairs = conect_pairs(text)
    assert len(pairs) == len(DDM_BONDS) + len(DDM_CONSTRAINTS), f'not one record per bonded term: {pairs}'
    assert set(pairs) == model_pairs(), f'the bonds are not the model\'s: {sorted(set(pairs) ^ model_pairs())}'
    assert "BONDS ARE THE MODEL'S OWN" in text and '[ constraints ]' in text


def test_beads_that_are_not_the_moleculetypes_are_drawn_unbonded_and_the_file_says_so(tmp_path):
    """The guard that stops a bond between two beads that are not that pair: the picture claims none instead."""
    run = coarse_run(tmp_path, beads=DDM_BEADS[:3])
    topology = pdc_view.read_moleculetype(run / TOPOLOGY)

    text = pdc_view.structure_pdb(run / MAPPED, topology=topology)

    assert conect_pairs(text) == [], 'a bond the moleculetype does not state'
    assert 'NO BONDS RECORDED FOR 1 OF 1 DETERGENT MOLECULES' in text


def test_a_run_that_states_no_topology_gets_coordinates_and_no_bonds(tmp_path):
    run = coarse_run(tmp_path, topology=None)

    text = pdc_view.structure_pdb(run / MAPPED, topology=None)

    assert conect_pairs(text) == []
    assert len([line for line in text.splitlines() if line.startswith('HETATM')]) == len(DDM_BEADS)


def test_the_molecule_is_found_by_its_beads_not_by_whichever_residue_the_file_lists_first(tmp_path):
    """A run's own `4_CG_sim/md.gro` starts with solvent. The bonds belong to the solute, not to the first bead.

    Measured on the live stage layout: naming the molecule after `atoms[0]` leaves the solute of a whole-box stage
    drawn with no bonds at all -- in the one picture a reader most wants.
    """
    run = coarse_run(tmp_path)
    path = run / 'stages/4_CG_sim/md.gro'
    path.parent.mkdir(parents=True)
    lines = ['the whole box', f'{len(DDM_BEADS) + 2:5d}']
    lines.append(gro_atom_line(1, 'W', 'W', 1, (0.0, 0.0, 0.0)))
    for serial, bead in enumerate(DDM_BEADS, start=2):
        lines.append(gro_atom_line(2, 'DDM', bead, serial, (serial * 0.3, 0.0, 0.0)))
    lines.append(gro_atom_line(1, 'NA', 'NA', len(DDM_BEADS) + 2, (5.0, 0.0, 0.0)))
    lines.append('   8.00000   8.00000   8.00000')
    path.write_text('\n'.join(lines) + '\n')
    topology = pdc_view.read_moleculetype(run / TOPOLOGY)

    text = pdc_view.structure_pdb(path, topology=topology)

    assert sorted(conect_pairs(text)) == sorted(model_pairs()), 'the solute is not the molecule that got bonded'
    names = [line[12:16].strip() for line in text.splitlines() if line.startswith('HETATM')]
    assert 'W' not in names and 'NA' not in names, 'the solvent is not part of this view'


def test_a_file_that_is_not_a_gro_is_refused_rather_than_half_drawn(tmp_path):
    """A `.pdb` already states its own records, and the artifact route serves it: this writer says so rather than
    guessing a serial order it never read."""
    path = tmp_path / 'mapped.pdb'
    path.write_text('END\n')

    with pytest.raises(ValueError, match='not a .gro'):
        pdc_view.structure_pdb(path)


def test_the_moleculetype_is_located_by_the_runs_own_layout(tmp_path):
    """`analysis.runs.layout.cg_topology` is the one place that says where a consumer keeps its topology."""
    run = coarse_run(tmp_path)

    assert run_topology(run, {}) == run / TOPOLOGY


def test_the_manifests_final_itp_names_the_topology_when_the_run_holds_several(tmp_path):
    """A fitted run leaves six `.itp` files under `3_initial_CG/`; the run's own record picks between them."""
    run = coarse_run(tmp_path, topology='stages/3_initial_CG/DDM_initial.itp')
    (run / TOPOLOGY).write_text(ddm_moleculetype())
    manifest = {'stages': [{'name': 'CG simulation', 'environment': {'FINAL_ITP': 'DDM.itp'}}]}

    assert run_topology(run, manifest) == run / TOPOLOGY


def test_a_run_that_states_no_topology_resolves_to_none_rather_than_guessing(tmp_path):
    run = coarse_run(tmp_path, topology=None)

    assert run_topology(run, {}) is None


def test_a_path_that_leaves_the_run_is_refused(tmp_path):
    """A run-relative path is relative to the run and to nothing else."""
    run = coarse_run(tmp_path)

    with pytest.raises(NotFound):
        structure_target(run, '../outside.gro')
    with pytest.raises(NotFound):
        structure_target(run, 'stages/2_mapping/missing.gro')
    with pytest.raises(Exception):
        structure_target(run, '')
    assert structure_target(run, MAPPED) == run / MAPPED
