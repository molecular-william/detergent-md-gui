"""The Complexes panel draws the model's bonds, not the viewer's guess.

Measured on a placement frame of an empty-micelle run: the panel drew 90 bonds where the model has 60, and among
them S1A-TAIL1 -- a head bead bonded to the first tail bead, which `detergent_CG.itp` does not bond (its own single
head-to-tail bond is S1A-TAIL3, 0.4294 nm). NGL guesses bonds from interatomic distances when a PDB carries no
CONECT records -- `inferBonds` defaults to `'all'` -- and every bead in these files is written as a radius stand-in
element, so the guess is generous.

Both halves of the fix are held here, because either alone is wrong: a file that carries the model's bonds with a
panel that still guesses draws 150 (the model's 60 plus the same 90), and a panel that stops guessing on a file that
carries none draws nothing at all. The test reads the count and the pairs off the loaded structure
(`compList[0].structure`, the seam this repo's other viewer tests read a structure through) and holds them to the
moleculetype.

The frame is a fixture rather than a run: the eleven beads of one DDM molecule are the coordinates the run's
`1_system/system.gro` held, and the six copies stand in for the frame's six molecules, which the placement stamped
from the same geometry -- 3 nm apart, so no two beads in different molecules are near enough for the guess. No test
reads the developer's workspace.
"""
from tests.dashboard.support import DDM_BEADS, DDM_BONDS, DDM_CONSTRAINTS, DDM_PLACEMENT, ddm_moleculetype, ddm_system_gro

MOLECULES = 6
SPACING_NM = 3.0

INDEX = {
    'job_id': 'pdcbonds',
    'snapshots': [
        {'name': 'placement', 'time_ps': None, 'pdb': 'snapshots/placement.pdb', 'stage': '1_system',
         'atoms': len(DDM_PLACEMENT) * MOLECULES, 'verdict': None},
    ],
}

#: What the panel's viewer holds after the picture is loaded: the atoms, the drawn bond count, and the drawn pairs
#: as bead serials. `bondStore` is where NGL keeps the bonds a representation draws (`atomIndex1`/`atomIndex2`).
MEASURE = """
(el) => {
  const structure = el.pdcStage.compList[0].structure;
  const store = structure.bondStore;
  const pairs = [];
  for (let index = 0; index < store.count; index += 1) {
    const first = store.atomIndex1[index] + 1;
    const second = store.atomIndex2[index] + 1;
    pairs.push(first < second ? [first, second] : [second, first]);
  }
  return {atoms: structure.atomCount, count: store.count, pairs: pairs};
}
"""


def gro_line(residue_id, residue, name, serial, xyz):
    """One .gro atom line, in the fixed-width fields the format gives: 5, 5, 5, 5, then 3 x 8.3f."""
    return (f'{residue_id:5d}{residue[:5]:<5}{name[:5]:>5}{serial:5d}'
            f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}')


def written_snapshot(tmp_path):
    """A stage holding the run's moleculetype and a placement frame, written through the real writer."""
    from dashboard.execution.scripts import pdc_snapshot

    stage = tmp_path / '1_system'
    stage.mkdir()
    (stage / 'detergent_CG.itp').write_text(ddm_moleculetype())
    lines = ['protein-detergent complex (DDM, AN=6)', str(len(DDM_PLACEMENT) * MOLECULES)]
    serial = 0
    for molecule in range(MOLECULES):
        for name, xyz in zip(DDM_BEADS, DDM_PLACEMENT):
            serial += 1
            lines.append(gro_line(2 + molecule, 'DDM', name, serial,
                                  (xyz[0] + molecule * SPACING_NM, xyz[1], xyz[2])))
    lines.append('   30.00000   10.00000   10.00000')
    structure = stage / 'system.gro'
    structure.write_text('\n'.join(lines) + '\n')

    record = pdc_snapshot.write_snapshot(stage, 'placement', structure, title='placed system')
    return stage, (stage / record['pdb']).read_text()


def register_built_run(dashboard, job_id='00000000abcd'):
    """A pdc run whose setup stage holds a built system, registered the way the store registers one."""
    stage = dashboard.coordinator.RUNS / job_id / 'stages' / '1_system'
    stage.mkdir(parents=True)
    (stage / 'detergent_CG.itp').write_text(ddm_moleculetype())
    (stage / 'system.gro').write_text(ddm_system_gro(MOLECULES))
    dashboard.coordinator.database().insert({'id': job_id, 'run_type': 'pdc', 'status': 'running',
                                             'stage': '1_system', 'molecule_id': 'DDM',
                                             'created': '2026-10-13T00:00:00+00:00'})
    return job_id


def model_bonds():
    """The model's own bonds over the frame, by the bead serial the writer gives each bead."""
    pairs = set()
    for molecule in range(MOLECULES):
        offset = molecule * len(DDM_BEADS)
        for first, second in (*DDM_BONDS, *DDM_CONSTRAINTS):
            pair = (offset + first, offset + second)
            pairs.add((min(pair), max(pair)))
    return pairs


#: The reader's own complaint, by bead serial: the first molecule's head bead drawn onto its first and second tail
#: bead. The moleculetype bonds neither -- its one head-to-tail bond is S1A-TAIL3 (atom 1 to atom 11).
FORBIDDEN = {'S1A-TAIL1': (1, 9), 'S1A-TAIL2': (1, 10)}


def assert_drawn_bonds(measured):
    """Hold a viewer's drawn bonds to the model: the count, the pairs, and no head-onto-tail guess among them."""
    drawn = {tuple(pair) for pair in measured['pairs']}
    model = model_bonds()
    named = [name for name, pair in FORBIDDEN.items() if pair in drawn]

    assert measured['count'] == len(model), (
        f'the panel drew {measured["count"]} bonds where the model has {len(model)}: '
        f'{len(drawn - model)} of them are not the model\'s, and {named} among them')
    assert not named, f'the panel drew {named}, which the moleculetype does not bond'
    assert drawn == model, f'the drawn bonds are not the model\'s: {sorted(drawn ^ model)}'


def test_the_panel_draws_the_models_bonds_rather_than_guessing_them(dashboard, live_page, tmp_path):
    page, errors = live_page
    _, text = written_snapshot(tmp_path)
    page.route('**/api/pdc/*/snapshots', lambda route: route.fulfill(json=INDEX))
    page.route('**/api/pdc/*/snapshots/**', lambda route: route.fulfill(body=text, content_type='text/plain'))
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')
    page.get_by_role('tab', name='Complexes', exact=True).click()

    page.evaluate("window.pdcSetRun('pdcbonds')")
    button = page.locator('#pdc-snapshots button').first
    button.wait_for(timeout=30000)
    button.click()
    page.wait_for_function(
        "() => document.querySelector('#pdc-viewer').pdcStage?.compList[0]?.structure?.atomCount === "
        f'{len(DDM_PLACEMENT) * MOLECULES}', timeout=30000)

    assert_drawn_bonds(page.locator('#pdc-viewer').evaluate(MEASURE))
    assert errors == []


def test_the_built_system_view_draws_the_models_bonds_too(dashboard, live_page):
    """The other door into the same viewer: the route's built system, not a snapshot.

    Measured on the tree before this: `/api/pdc/<run>/system.pdb` served `1_system/system.gro` through the writer
    with no topology, so the file gave every molecule its own residue but carried no CONECT records -- and the
    panel, which switches NGL's distance-based guess off only when the file has them, drew 90 bonds where the
    model has 60. The route now hands the writer the run's own moleculetype, and the panel's existing rule draws
    the model, so the two doors show the same 60 bonds.
    """
    page, errors = live_page
    job_id = register_built_run(dashboard)
    page.goto(f'{live_page.base_url}/protein-detergent/complexes')
    page.get_by_role('tab', name='Complexes', exact=True).click()

    page.evaluate(f"window.pdcSetRun('{job_id}')")
    page.wait_for_function(
        "() => document.querySelector('#pdc-viewer').pdcStage?.compList[0]?.structure?.atomCount === "
        f'{len(DDM_PLACEMENT) * MOLECULES}', timeout=30000)

    assert_drawn_bonds(page.locator('#pdc-viewer').evaluate(MEASURE))
    assert errors == []
