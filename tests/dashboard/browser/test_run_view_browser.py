"""The Run view panel, driven in a browser: one run, its own structures, its figures, and where it delegates.

Every run here is a fixture this test builds in its own workspace -- nothing reads the developer's `workspace/`,
which holds surviving runs as evidence rather than as a fixture. The structures are the *shape* a live run has
(the plans' own layout: `stages/07_reference/lig.gro` for an AA run, `stages/2_mapping/mapped.gro` plus a bead PDB
for a CG one, `snapshots/CG-frames.pdb` for a published frame series), and every number asserted is read back off
the component the viewer loaded rather than off the parameters the panel asked for.

Two of the four traps the plan measured are proved here, on real NGL objects:

1. **A CG file that carries `CONECT` must be loaded with the bond inference OFF.** The vendored build parses
   `CONECT` into its `bondStore` and *then* still runs its distance guess (`inferBonds` defaults to `'all'`), so a
   file whose model bonds 7 ways is drawn 14 ways unless the guard is on. The assertion is the drawn bond count and
   the pairs, read from `structure.bondStore` -- not the flag that was sent.
2. **Coarse-grained beads must be drawn at the radii the model's size classes give them**, through the one helper
   `ngl-beads.js` holds, not at their stand-in element's. The radii are read back off the loaded structure, the way
   `test_pdc_bead_radii_browser.py` reads them, and held to the model's own table times this panel's own display
   scale -- both numbers asserted, so neither the table nor the read can drift.

The third and fourth traps belong with the transport row and are proved in `test_run_view_transport_browser.py`.
"""
from playwright.sync_api import expect

AA_RUN = 'aa00aa000001'
CG_RUN = 'cc00cc000002'
FRAMES_RUN = 'ff00ff000003'
PDC_RUN = 'dd00dd000004'
OSMOTIC_RUN = 'ee00ee000005'
#: A coarse-grained run that holds no moleculetype: the state the structure route has to report rather than guess
#: bonds for. Planted by its own test, because the chooser's tests count the runs in the shared seed.
NO_TOPOLOGY_RUN = 'aa00aa000007'
#: A run that has published more attempts than the artifact route pages at once. The index is walked in *directory*
#: order rather than by age, so an attempt whose directory sorts last lands on a later page while still being the
#: newest by `modified_at` -- and the newest `result.json` is what names the frame series.
MANY_RUN = 'bb00bb000006'
#: The routes' own page size (`web/routes/common.py`: `limit` is capped at 100), written out so this file fails if it
#: drifts rather than quietly testing a fixture that fits in one page.
PAGE_CAP = 100
#: One file per earlier attempt, so the newest attempt's five files land past the first page.
EARLIER_ATTEMPTS = 120

BEADS = ('B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08')
#: The Martini 3 polarity family code the fixture's own moleculetype states: every bead is an `SP1r`, which is polar,
#: and a viewer colours from this column (`ngl-beads.js`'s `BEAD_FAMILY_ORDER`).
FAMILY_CODE = 3
#: The sizes the fixture's own `model.json` states: the maltose mapping's classes, six S and the two virtual sites T.
SIZES = {'B01': 'S', 'B02': 'S', 'B03': 'S', 'B04': 'T', 'B05': 'S', 'B06': 'S', 'B07': 'S', 'B08': 'T'}
#: The stand-in element each class is written with in a bead file's element column (`models/compositions/topology.py`).
ELEMENTS = {'R': 'C', 'S': 'N', 'T': 'H'}
#: Martini 3's molecular-volume classes in nanometres, the table `models/sugars/recognition.py` and `ngl-beads.js`
#: both hold. Written out here so this file fails if either drifts.
RADII_NM = {'R': 0.264, 'S': 0.230, 'T': 0.191}
NANOMETRE_TO_ANGSTROM = 10.0
#: The scale this panel draws beads at (`run-view.js`'s `BEAD_SCALE`): the model's own radius times this, for
#: reading only. Written out here so the display size has to be changed in two places, and so the assertion below
#: names both numbers -- the model's radius and the multiplier -- rather than folding them into one.
DRAWN_BEAD_SCALE = 0.3
#: The mapped model's own coordinates (`stages/2_mapping/mapped.gro`), in nanometres, one per bead.
MAPPED_NM = ((1.069, 1.486, 0.935), (1.226, 1.382, 1.177), (1.034, 1.180, 1.111), (1.109, 1.349, 1.074),
             (1.369, 1.334, 1.403), (1.436, 1.083, 1.494), (1.151, 1.058, 1.521), (1.318, 1.158, 1.473))
#: The seven edges the mapped model's own `LIG1.itp` declares: one `[ bonds ]` line and six `[ constraints ]`.
MODEL_BONDS = ((1, 2), (1, 3), (2, 3), (2, 5), (5, 6), (5, 7), (6, 7))
MODEL_JSON = {'name': 'fixture mapping', 'status': 'candidate-unvalidated',
              'beads': [{'name': f'S{index}', 'size': SIZES[name], 'export_name': name}
                        for index, name in enumerate(BEADS, 1)]}


def aa_gro():
    """The AA reference solute: five atoms, coordinates only -- a `.gro` carries no bond records."""
    rows = ['fixture AA reference', '    5']
    for index, xyz in enumerate(((0.0, 0.0, 0.0), (0.15, 0.0, 0.0), (0.30, 0.0, 0.0), (0.45, 0.0, 0.0),
                                 (0.0, 0.11, 0.0)), 1):
        name = 'C%d' % index if index < 5 else 'H1'
        rows.append(f'{1:5d}{"LIG":<5}{name:>5}{index:5d}' + ''.join(f'{value:8.3f}' for value in xyz))
    rows.append('   1.00000   1.00000   1.00000')
    return '\n'.join(rows) + '\n'


def aa_pdb():
    """The molecule input: all-atom, no `CONECT`, so the viewer's own distance guess is the one left on."""
    lines = ['TITLE     fixture molecule input']
    for index, xyz in enumerate(((0.000, 0.000, 0.000), (1.400, 0.000, 0.000), (2.800, 0.000, 0.000),
                                 (4.200, 0.000, 0.000), (0.000, 1.100, 0.000)), 1):
        element = 'H' if index == 5 else 'C'
        name = 'H1' if index == 5 else f'C{index}'
        lines.append(f'ATOM  {index:5d} {name:>4} LIG A   1    '
                     + ''.join(f'{value:8.3f}' for value in xyz) + f'  1.00  0.00          {element:>2}')
    return '\n'.join(lines + ['END']) + '\n'


def bead_pdb(coordinates=None, conect=True):
    """A bead file: the eight mapped beads, each written with the stand-in element of its own size class.

    With `conect` the model's seven edges are written as `CONECT` records -- the file `models/mappings/
    overlay3d.py` and the PDC writer both produce, and the one the guard exists for. Without them it is a file
    that carries coordinates only, which is what a viewer would otherwise guess bonds for.
    """
    coordinates = coordinates or [(x * NANOMETRE_TO_ANGSTROM, y * NANOMETRE_TO_ANGSTROM, z * NANOMETRE_TO_ANGSTROM)
                                  for x, y, z in MAPPED_NM]
    lines = ['REMARK 950 TEST BEAD FRAME, ELEMENTS ARE THE SIZE CLASS STAND-IN']
    for index, (name, xyz) in enumerate(zip(BEADS, coordinates), 1):
        element = ELEMENTS[SIZES[name]]
        lines.append(bead_record(index, name, xyz, element))
    if conect:
        lines += [f'CONECT{first:5d}{second:5d}' for first, second in MODEL_BONDS]
    return '\n'.join(lines + ['END']) + '\n'


def bead_record(serial, name, xyz, element, *, residue='DET', family=FAMILY_CODE):
    """One bead's `HETATM` line in the producer's own columns (`pdc_view.system_pdb`): the size-class element
    stand-in at 77-78 and the family code at 61-66.

    Written from one place because the columns are the point: a fixture whose records sit a column off the standard
    still *looks* like a PDB and carries a family code that no reader can find -- which is exactly what this
    fixture did until a test measured the colours it produced rather than the text it wrote.
    """
    x, y, z = xyz
    return (f'HETATM{serial:5d} {name:<4s} {residue:>3s} A{1:4d}    {x:8.3f}{y:8.3f}{z:8.3f}'
            f'{1.0:6.2f}{float(family):6.2f}          {element:>2s}')


def frames_pdb(count=5):
    """The multi-model PDB the `snapshots` analysis writes: one `MODEL` per sampled frame, `ENDMDL` between them.

    It carries what the producer writes (`pdc_view.series_pdb`): the family code in the b-factor column and the
    model's own bonds as `CONECT`, per model. A fixture with neither is a fixture the panel can only draw as grey,
    unbonded spheres -- which is exactly the defect that reached a published series once.
    """
    lines = []
    for model in range(count):
        lines.append(f'MODEL     {model + 1:4d}')
        for index, (name, (x, y, z)) in enumerate(zip(BEADS, MAPPED_NM), 1):
            lines.append(bead_record(index, name, ((x + model * 0.05) * 10, y * 10, z * 10),
                                     ELEMENTS[SIZES[name]]))
        lines += [f'CONECT{first:5d}{second:5d}' for first, second in MODEL_BONDS]
        lines.append('ENDMDL')
    return '\n'.join(lines + ['END']) + '\n'


#: Where the `snapshots` analysis publishes: inside its own content-addressed attempt, never at the run root
#: (`references/published-analysis-addressing.md`, and `dashboard/analysis/worker.py`'s write of `result.json`).
SNAPSHOT_ATTEMPT = 'analyses/snapshots/1a2b3c4d/5e6f7a8b'
SNAPSHOT_OUTPUT = 'output/9c0d1e2f'


def published_snapshots(files):
    """The files a `snapshots` attempt publishes, plus the `result.json` a reader resolves them through.

    `files` maps a bare snapshot file name to its text. The record's `outputs_sha256` names every published file
    relative to `output_directory`, which is the join the panel has to make.
    """
    root = f'{SNAPSHOT_ATTEMPT}/{SNAPSHOT_OUTPUT}'
    contents = {f'{root}/snapshots/{name}': text for name, text in files.items()}
    contents[f'{SNAPSHOT_ATTEMPT}/result.json'] = json_text({
        'result': {'frames': 40, 'files': list(files), 'role': 'cg_trajectory',
                   'trajectory': 'stages/4_CG_sim/md.xtc',
                   'series': {'file': 'CG-frames.pdb', 'stride': 7, 'sampled': 5}},
        'output_directory': SNAPSHOT_OUTPUT,
        'outputs_sha256': {f'snapshots/{name}': 'a' * 64 for name in files},
    })
    return contents


def many_attempts():
    """A run's artifact tree once it has published more attempts than one page of the index holds.

    Earlier attempts each contribute one file under a signature that sorts *before* the newest attempt's own
    (`00000000` against `1a2b3c4d`), and the newest attempt is published last so its `modified_at` is the newest. Its
    `result.json` therefore sits on a later page while still being the record a reader has to resolve.
    """
    contents = {f'analyses/snapshots/00000000/attempt-{index:03d}/output/frame-{index:03d}.txt':
                "an earlier attempt's output, and not a resolvable record\n"
                for index in range(EARLIER_ATTEMPTS)}
    contents |= published_snapshots({'CG-frames.pdb': frames_pdb(),
                                     'CG-first.pdb': bead_pdb(),
                                     'CG-middle.pdb': bead_pdb(),
                                     'CG-last.pdb': bead_pdb()})
    return contents


def plant(dashboard, run_id, record, files):
    """Insert one run and write its files, the way `seed` does -- for a run only this test needs.

    `seed` is shared by the whole file and several tests count the runs it creates, so a run that belongs to one
    test is built by that test rather than added to the common workspace.
    """
    owner = dashboard.coordinator
    owner.database().insert(record)
    for path, text in files.items():
        target = owner.RUNS / run_id / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def job(run_id, run_type, label, created, **extra):
    return {'id': run_id, 'run_type': run_type, 'label': label, 'created': created, 'status': 'completed',
            'molecule_name': label.split()[0], 'detergent': 'Sucrose', 'method': 'fast_forward'} | extra


def seed(dashboard):
    """Every run this file reads, built in the test's own workspace with the files each one holds."""
    owner = dashboard.coordinator
    rows = {
        AA_RUN: (job(AA_RUN, 'aa_only', 'Sucrose AA reference', '2026-10-01T10:00:00+00:00'),
                 {'stages/07_reference/lig.gro': aa_gro(),
                  'stages/common/molecule/MMFF/lig1.pdb': aa_pdb()}),
        CG_RUN: (job(CG_RUN, 'aa_cg', 'Maltose CG consistency', '2026-10-02T10:00:00+00:00'),
                 {'stages/2_mapping/mapped.gro': mapped_gro(),
                  'stages/2_mapping/model.json': json_text(MODEL_JSON),
                  'stages/3_initial_CG/LIG1.itp': moleculetype(),
                  'stages/3_initial_CG/LIG1.pdb': bead_pdb(),
                  'stages/4_CG_sim/md.gro': mapped_gro(),
                  'stages/5_assessment/score_matrix_LIG1.png': 'not really a png, but the figures route lists it'}),
        FRAMES_RUN: (job(FRAMES_RUN, 'aa_cg', 'Sorbitol CG, frames published', '2026-10-03T10:00:00+00:00'),
                     {'stages/2_mapping/mapped.gro': mapped_gro(),
                      'stages/2_mapping/model.json': json_text(MODEL_JSON),
                      } | published_snapshots({'CG-frames.pdb': frames_pdb(),
                                              'CG-first.pdb': bead_pdb(),
                                              'CG-middle.pdb': bead_pdb(),
                                              'CG-last.pdb': bead_pdb()})),
        PDC_RUN: (job(PDC_RUN, 'pdc', 'Complex build 1', '2026-10-04T10:00:00+00:00'),
                  {'stages/1_system/system.gro': mapped_gro()}),
        OSMOTIC_RUN: (job(OSMOTIC_RUN, 'osmotic', 'Osmotic series', '2026-10-05T10:00:00+00:00'), {}),
    }
    for run_id, (record, files) in rows.items():
        owner.database().insert(record)
        for path, text in files.items():
            target = owner.RUNS / run_id / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)


def json_text(payload):
    import json
    return json.dumps(payload, indent=2)


def mapped_gro():
    rows = ['Written by MDAnalysis', '    8']
    for index, (name, xyz) in enumerate(zip(BEADS, MAPPED_NM), 1):
        rows.append(f'{1:5d}{"LIG1":<5}{name:>5}{index:5d}' + ''.join(f'{value:8.3f}' for value in xyz))
    rows.append('   2.48092   2.48092   2.48092')
    return '\n'.join(rows) + '\n'


def moleculetype():
    """The run's own `stages/3_initial_CG/LIG1.itp`: the eight mapped beads' names in the mapped file's own order,
    and the seven bonded terms that hold them -- three the head ring is pinned by, four the run bonds.

    A run's moleculetype is what states a coarse-grained model's connectivity, which is why the structure route
    reads it: the panel's picture is drawn from that answer rather than from a distance guess.
    """
    atoms = '\n'.join(f'{index} SP1r 1 LIG1 {name} {index} 0 54' for index, name in enumerate(BEADS, 1))
    ring, chains = MODEL_BONDS[:3], MODEL_BONDS[3:]
    constraints = '\n'.join(f'{first} {second} 1 0.361013007037' for first, second in ring)
    bonds = '\n'.join(f'{first} {second} 1 0.429374836245 5000' for first, second in chains)
    return ("; the run's own bonded draft\n[ moleculetype ]\nLIG1 1\n\n"
            f'[ atoms ]\n{atoms}\n\n[ constraints ]\n{constraints}\n\n[ bonds ]\n{bonds}\n')


#: What the readout under the canvas reports, read off the component the viewer loaded -- never off the parameters
#: the panel sent. `atom.radius` is the value `applyBeadRadii` put on the structure, in angstroms.
MEASURE = """
() => {
  const host = document.querySelector('#run-view-viewer');
  const component = host.runViewStage.compList[0];
  const structure = component.structure;
  const radii = [];
  for (let index = 0; index < structure.atomCount; index += 1) {
    radii.push(structure.getAtomProxy(index).radius);
  }
  const store = structure.bondStore;
  const pairs = [];
  for (let index = 0; index < store.count; index += 1) {
    const first = store.atomIndex1[index] + 1;
    const second = store.atomIndex2[index] + 1;
    pairs.push(first < second ? [first, second] : [second, first]);
  }
  const element = component.trajList && component.trajList[0];
  return {
    atoms: structure.atomCount, radii: radii, bonds: store.count, pairs: pairs,
    frames: element ? element.trajectory.frameCount : 0,
    models: structure.frames ? structure.frames.length : 0,
    readout: document.querySelector('#run-view-readout').textContent,
    note: document.querySelector('#run-view-transport-note').textContent,
  };
}
"""


def open_panel(page, live_page, workspace='detergent-validation', run=None):
    query = f'?run={run}' if run else ''
    page.goto(f'{live_page.base_url}/{workspace}/run-view{query}')
    expect(page.locator('#runview')).to_be_visible()


def wait_for_component(page, atoms=None):
    page.wait_for_function(
        "() => document.querySelector('#run-view-viewer')?.runViewStage?.compList?.[0]?.structure",
        timeout=30000)
    if atoms is not None:
        # Optional chaining all the way: between `removeAllComponents()` and the load resolving, `compList[0]` is
        # undefined, and a predicate that throws is not a wait -- Playwright reports it instead of retrying.
        page.wait_for_function(
            "() => document.querySelector('#run-view-viewer')?.runViewStage?.compList?.[0]?.structure?.atomCount"
            f" === {atoms}",
            timeout=30000)


def select_row(page, text):
    row = page.locator('#run-view-holds tr').filter(has_text=text)
    expect(row).to_have_count(1)
    row.click()


# ---------------------------------------------------------------------------------------------------- the registrations


def test_the_panel_renders_in_both_workspaces_and_no_other_label_moved(dashboard, live_page):
    """Validation gains a tab and simulations gains one; every other panel's label is untouched."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page)

    expect(page.locator('#subtabs .subtab')).to_have_count(8)
    expect(page.locator('#subtabs .subtab[aria-selected=true]')).to_contain_text('Run view')
    for label in ('Runs', 'New run', 'Bead Assignment', 'Bond Interactions', 'Combinations', 'Mapping Validation',
                  'Osmotic Series', 'Run view'):
        expect(page.locator(f'#subtabs .subtab:has-text("{label}")')).to_have_count(1)

    open_panel(page, live_page, workspace='protein-detergent')
    expect(page.locator('#subtabs .subtab')).to_have_count(4)
    expect(page.locator('#subtabs .subtab[aria-selected=true]')).to_contain_text('Run view')
    assert errors == []


# ------------------------------------------------------------------------------------------------- the run chooser


def test_the_chooser_asks_for_this_workspaces_run_types_and_lists_none_of_the_others(dashboard, live_page):
    """D2/T5: one request per run type in scope, and a `pdc` run is not this workspace's to show."""
    seed(dashboard)
    page, errors = live_page
    asked = []
    page.on('request', lambda request: asked.append(request.url))
    open_panel(page, live_page)
    expect(page.locator('#run-view-list button')).to_have_count(4)

    jobs = [url.split('run_type=')[1].split('&')[0] for url in asked if '/api/jobs?' in url and 'run_type=' in url]
    assert sorted(set(jobs)) == ['aa_cg', 'aa_only', 'cg_composition', 'osmotic'], jobs
    assert not any('/api/jobs?' in url and 'run_type=' not in url for url in asked), \
        'the panel must ask the route for a run type, not page every run and narrow it here'

    listed = page.locator('#run-view-list .id').all_inner_texts()
    assert PDC_RUN not in listed, f'a complex run is offered by the wrong workspace: {listed}'
    assert AA_RUN in listed and CG_RUN in listed
    expect(page.locator('#run-view-count')).to_contain_text("in this workspace's scope")
    assert errors == []


def test_the_run_type_control_narrows_to_one_type_at_a_time(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page)
    expect(page.locator('#run-view-list button')).to_have_count(4)

    page.locator('#run-view-type').select_option('aa_only')
    expect(page.locator('#run-view-list button')).to_have_count(1)
    expect(page.locator('#run-view-list .id')).to_have_text(AA_RUN)
    assert errors == []


def test_the_protein_detergent_workspace_offers_only_complex_runs(dashboard, live_page):
    """The other half of D2, from the other side: an AA-only run is not that workspace's to show."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, workspace='protein-detergent')
    expect(page.locator('#run-view-list .id')).to_have_text(PDC_RUN)
    assert errors == []


# ----------------------------------------------------------------------------------------------- an AA run, drawn


def test_an_aa_run_draws_its_published_gro_bondless_and_names_where_its_bonds_are(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page, atoms=5)

    measured = page.locator('#run-view-viewer').evaluate(MEASURE)
    assert measured['atoms'] == 5
    # A `.gro` carries no bond records, and this build's GRO parser guesses them from distances whatever
    # `inferBonds` says -- the panel clears the store, so zero bonds are drawn. That is the honest picture rather
    # than a guess, and the readout says which file and where the model's bonds actually are.
    assert measured['bonds'] == 0, 'a .gro must be drawn without invented bonds'
    expect(page.locator('#run-view-readout')).to_contain_text('bonds the file states')
    expect(page.locator('#run-view-readout')).to_contain_text('bonds the viewer resolved')
    expect(page.locator('#run-view-transport-note')).to_contain_text('.gro')
    expect(page.locator('#run-view-readout')).to_contain_text('a .gro carries coordinates and no bond records')
    expect(page.locator('#run-view-what')).to_contain_text('stages/07_reference/lig.gro')
    assert errors == []


def test_an_aa_runs_molecule_is_the_one_case_the_viewers_own_guess_is_left_on(dashboard, live_page):
    """An all-atom `.pdb` with no `CONECT` is the third branch: the guess reproduces the chemistry."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page, atoms=5)

    select_row(page, 'lig1.pdb')
    wait_for_component(page, atoms=5)
    measured = page.locator('#run-view-viewer').evaluate(MEASURE)
    assert measured['atoms'] == 5
    assert measured['bonds'] > 0, 'the viewer\'s own distance guess reproduces a real molecule'
    expect(page.locator('#run-view-readout')).to_contain_text('bonds the file states')
    expect(page.locator('#run-view-readout')).to_contain_text('reproduces the chemistry')
    assert errors == []


# -------------------------------------------------------------------------------- a CG run: the CONECT guard, the radii


def test_a_cg_runs_mapped_model_is_drawn_with_the_models_own_bonds(dashboard, live_page):
    """T3's acceptance: the run's own moleculetype, read off `structure.bondStore` rather than off the request.

    Measured before this: `stages/2_mapping/mapped.gro` drawn straight off the artifact route came back with **0**
    bonds -- a `.gro` carries no bond records, and this build's GRO parser's own distance guess is cleared by the
    panel's guard -- so a CG run's picture showed beads with no connectivity at all while its own
    `stages/3_initial_CG/LIG1.itp` stated seven. The panel now asks the run structure route, which writes those
    `[ bonds ]` + `[ constraints ]` as CONECT, and the count and the pairs are asserted on the component the viewer
    loaded.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)

    measured = page.locator('#run-view-viewer').evaluate(MEASURE)
    drawn = {tuple(pair) for pair in measured['pairs']}
    assert measured['atoms'] == 8
    assert measured['bonds'] == len(MODEL_BONDS), (
        f"the run's moleculetype states {len(MODEL_BONDS)} bonds and the viewer drew {measured['bonds']}")
    assert drawn == set(MODEL_BONDS), f"the drawn bonds are not the model's: {sorted(drawn ^ set(MODEL_BONDS))}"
    expect(page.locator('#run-view-what')).to_contain_text('stages/2_mapping/mapped.gro')
    expect(page.locator('#run-view-readout')).to_contain_text("bonds the run's own topology states")
    expect(page.locator('#run-view-readout')).to_contain_text("the run's own moleculetype, written as CONECT")
    expect(page.locator('#run-view-readout')).to_contain_text('stages/3_initial_CG/')
    assert errors == []


def test_a_cg_run_that_states_no_moleculetype_is_drawn_bondless_and_says_so(dashboard, live_page):
    """The other half of the route: no topology is a state to report, not a licence to guess bonds.

    Planted by this test rather than added to `seed`, because the chooser's own tests count the runs in that
    workspace.
    """
    stage = dashboard.coordinator.RUNS / NO_TOPOLOGY_RUN / 'stages/2_mapping'
    stage.mkdir(parents=True)
    (stage / 'mapped.gro').write_text(mapped_gro())
    dashboard.coordinator.database().insert(
        job(NO_TOPOLOGY_RUN, 'aa_cg', 'Sorbitol CG, no topology', '2026-10-02T11:00:00+00:00'))

    page, errors = live_page
    open_panel(page, live_page, run=NO_TOPOLOGY_RUN)
    wait_for_component(page, atoms=8)

    measured = page.locator('#run-view-viewer').evaluate(MEASURE)
    assert measured['bonds'] == 0, 'a bond nothing declares must not be drawn'
    expect(page.locator('#run-view-readout')).to_contain_text('states no moleculetype')
    expect(page.locator('#run-view-readout')).to_contain_text('the picture claims no bonds')
    assert errors == []


def test_a_cg_file_that_carries_conect_is_drawn_from_it_and_never_guessed_at(dashboard, live_page):
    """Trap 1, measured on the component: seven records in, seven bonds drawn -- not fourteen."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)

    select_row(page, 'LIG1.pdb')
    wait_for_component(page, atoms=8)
    measured = page.locator('#run-view-viewer').evaluate(MEASURE)
    drawn = {tuple(pair) for pair in measured['pairs']}
    assert measured['bonds'] == len(MODEL_BONDS), (
        f'the file states {len(MODEL_BONDS)} bonds and the viewer drew {measured["bonds"]}: the CONECT records '
        f'were double-drawn with a distance guess ({sorted(drawn)})')
    assert drawn == set(MODEL_BONDS), f'the drawn bonds are not the file\'s own: {sorted(drawn ^ set(MODEL_BONDS))}'
    expect(page.locator('#run-view-readout')).to_contain_text('carries CONECT')
    expect(page.locator('#run-view-readout')).to_contain_text('the distance guess is off')
    assert errors == []


def test_the_guard_is_what_keeps_the_guess_out_of_a_conect_file(dashboard, live_page):
    """The counterfactual: without the guard, the file's seven records are drawn with the guess's own added on.

    Read through NGL directly rather than through the panel, because the panel must not offer a way to switch the
    guard off -- what this proves is that the parameter the guard sets is what stands between the two numbers.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)
    select_row(page, 'LIG1.pdb')
    wait_for_component(page, atoms=8)

    # The guess bites where beads sit closer than their stand-in elements' covalent radii sum, and the stand-ins are
    # now written where a reader finds them (`N` for the S class, `H` for T). Measured: at the file's own spacings
    # that sum is under every bonded pair, so the guess adds nothing and the counterfactual needs beads packed
    # closer. The subject is the *parameter*, so the fixture is a compressed copy of the same bead file rather than
    # the file a run writes -- what must hold either way is that the guard is the difference between the file's
    # seven records and more.
    packed = [tuple(value * NANOMETRE_TO_ANGSTROM * 0.5 for value in xyz) for xyz in MAPPED_NM]
    measured = page.locator('#run-view-viewer').evaluate("""async (element, text) => {
      const host = document.createElement('div');
      host.style.width = '200px'; host.style.height = '200px';
      document.body.append(host);
      const stage = new NGL.Stage(host, {backgroundColor: 'white'});
      const component = await stage.loadFile(new Blob([text], {type: 'text/plain'}),
                                             {ext: 'pdb', inferBonds: 'all'});
      const store = component.structure.bondStore, pairs = [];
      for (let index = 0; index < store.count; index += 1) {
        pairs.push([store.atomIndex1[index] + 1, store.atomIndex2[index] + 1]);
      }
      return {bonds: component.structure.bondCount, pairs: pairs};
    }""", bead_pdb(coordinates=packed))
    assert measured['bonds'] > len(MODEL_BONDS), (
        f'the distance guess should have inflated the 7 records; it drew {measured["bonds"]}')
    # The defect's signature: the file's own edges are drawn again on top of themselves, plus edges the model has
    # none of -- the pair every one of these beads is a stand-in for.
    assert [7, 8] in measured['pairs'] or [8, 7] in measured['pairs'] or \
        len(measured['pairs']) != len({tuple(pair) for pair in measured['pairs']}), \
        'the guess must add a bond the model does not have'
    assert errors == []


def test_cg_beads_are_drawn_at_the_radius_their_own_size_class_has(dashboard, live_page):
    """Trap 2: the model's own radii through `ngl-beads.js`, times this panel's display scale.

    The two classes are the model's own -- a stand-in element would draw them all one size -- and the scale is the
    0.3 the reader asked for, which is also what the New Run preview draws at, so the same bead is the same size in
    both panels. At 1 a mapped sugar reads as one lump: a Martini 3 bonded pair sits 1.4-2.2 A apart while an S
    bead's own radius is 2.30 A.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)
    select_row(page, 'LIG1.pdb')
    wait_for_component(page, atoms=8)

    measured = page.locator('#run-view-viewer').evaluate(MEASURE)
    drawn = [None if value is None else round(value / NANOMETRE_TO_ANGSTROM, 4) for value in measured['radii']]
    expected = [round(RADII_NM[SIZES[name]] * DRAWN_BEAD_SCALE, 4) for name in BEADS]
    assert drawn == expected, f'the beads are not drawn at their own size classes: {drawn} against {expected}'
    # The stand-in elements are nearly the same size as each other; the model's classes are not.
    assert len(set(drawn)) == 2, 'a size ranking from the element column, not the model'
    expect(page.locator('#run-view-readout')).to_contain_text('model.json size classes')
    expect(page.locator('#run-view-readout')).to_contain_text(f'drawn at {DRAWN_BEAD_SCALE}x')
    assert errors == []


# ------------------------------------------------------------------------------------------ figures and delegation


#: Martini 3's polarity families as `ngl-beads.js` colours them. This fixture's moleculetype types every bead
#: `SP1r`, which is polar, so the whole mapped model is one colour and the legend is what names it.
FAMILY_COLOURS = {'unstated': '#cccccc', 'C': '#7048e8', 'N': '#e8590c', 'P': '#2f9e44', 'Q': '#2b6cb0'}

#: The colours the canvas resolved, and the legend under it read back from the page.
MEASURE_FAMILY = """
async () => {
  const component = document.querySelector('#run-view-viewer').runViewStage.compList[0];
  const structure = component.structure;
  const parameters = component.reprList[0].repr.getColorParams();
  const scheme = NGL.ColormakerRegistry.getScheme(parameters);
  const colours = [];
  for (let index = 0; index < structure.atomCount; index += 1) {
    colours.push('#' + scheme.atomColor(structure.getAtomProxy(index)).toString(16).padStart(6, '0'));
  }
  const legend = document.querySelector('.run-view-stage .bead-legend');
  return {scheme: parameters.scheme, colours: colours, hidden: legend.hidden,
          entries: [...legend.querySelectorAll('.bead-legend-item')].map(item => ({
            family: item.dataset.family,
            label: item.querySelector('.bead-legend-label').textContent,
            declared: item.querySelector('.bead-legend-swatch').dataset.colour,
          }))};
}
"""


def test_a_cg_run_colours_its_beads_by_family_and_only_then_shows_the_legend(dashboard, live_page):
    """A coarse model's beads are coloured by their type family, and the legend appears with the picture it decodes.

    The file this panel serves for a coarse `.gro` is written by `pdc_view.structure_pdb`, so it carries the family
    code in its b-factor column and the run view colours the same beads the Complexes panel does -- the same module,
    the same five colours. An all-atom structure is drawn in its elements' colours and gets no bead legend at all,
    because a key over a picture it does not describe is a lie.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)
    select_row(page, 'md.gro')
    wait_for_component(page, atoms=8)

    measured = page.locator('#run-view-viewer').evaluate(MEASURE_FAMILY)
    assert measured['scheme'] == 'bfactor', measured['scheme']
    assert measured['colours'] == [FAMILY_COLOURS['P']] * 8, measured['colours']
    assert measured['hidden'] is False, 'a coarse picture with no legend under it'
    assert [entry['family'] for entry in measured['entries']] == ['unstated', 'C', 'N', 'P', 'Q']
    assert {entry['declared'] for entry in measured['entries']} == set(FAMILY_COLOURS.values())

    # The all-atom sibling: no legend, because there is no family to decode.
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page)
    select_row(page, 'lig.gro')
    wait_for_component(page, atoms=5)
    atomistic = page.locator('#run-view-viewer').evaluate(MEASURE_FAMILY)
    assert atomistic['hidden'] is True, 'an all-atom structure got a bead legend'
    assert errors == []


def test_figures_are_listed_and_opened_inline_through_the_artifact_route(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)

    link = page.locator('#run-view-figures a')
    expect(link).to_have_count(1)
    href = link.get_attribute('href')
    assert href == f'/api/jobs/{CG_RUN}/artifacts/stages/5_assessment/score_matrix_LIG1.png?inline=1', href
    assert link.get_attribute('target') == '_blank'
    expect(page.locator('#run-view-figures-note')).to_contain_text('zoomable')
    assert errors == []


def test_a_run_with_no_figure_says_so_instead_of_showing_an_empty_list(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page, atoms=5)
    expect(page.locator('#run-view-figures a')).to_have_count(0)
    expect(page.locator('#run-view-figures-note')).to_contain_text('published no figure')
    assert errors == []


def test_a_complex_run_is_delegated_to_complexes_and_nothing_is_drawn_here(dashboard, live_page):
    """D9: the one genuine duplication, answered by not doing it."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, workspace='protein-detergent', run=PDC_RUN)
    expect(page.locator('#run-view-list .id')).to_have_text(PDC_RUN)

    expect(page.locator('#run-view-delegation')).to_be_visible()
    link = page.locator('#run-view-delegation a')
    expect(link).to_have_count(1)
    assert link.get_attribute('href') == f'/protein-detergent/complexes?run={PDC_RUN}'
    expect(page.locator('#run-view-delegation')).to_contain_text('reads ?run= at mount')

    assert page.locator('#run-view-viewer').is_hidden(), 'no canvas is drawn for a complex run'
    assert page.locator('#run-view-transport').is_hidden(), 'and no transport row either'
    expect(page.locator('#run-view-transport-note')).to_contain_text('deliberately')
    assert page.evaluate("() => document.querySelector('#run-view-viewer').runViewStage") is None
    assert errors == []


# ----------------------------------------------------------------------------------------------------- the frames


def test_the_published_frame_series_is_listed_first_and_is_the_file_the_row_plays(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    first = page.locator('#run-view-holds tr').first
    expect(first).to_contain_text('snapshots/CG-frames.pdb')
    assert first.get_attribute('aria-selected') == 'true'
    measured = page.locator('#run-view-viewer').evaluate(MEASURE)
    assert measured['frames'] == 5, 'the multi-model PDB must be a trajectory, not five models drawn at once'
    # The series carries the model's own bonds, as the producer writes them (`pdc_view.series_pdb`). This asserted
    # zero until the file was made to carry them: a published series with no CONECT is a picture of grey spheres
    # with no connectivity, which is the defect a reader reported from the panel.
    assert measured['bonds'] == len(MODEL_BONDS), \
        f"the series drew {measured['bonds']} bonds for a model that states {len(MODEL_BONDS)}"
    expect(page.locator('#run-view-frames button')).to_have_count(3)
    assert errors == []


def test_a_multi_model_pdb_without_a_trajectory_is_every_model_drawn_at_once(dashboard, live_page):
    """Trap 3: `loadFile` alone draws all five models' atoms in one picture and makes no trajectory.

    Measured directly through NGL, because this is the mistake the panel must not make: the same bytes the panel
    loads correctly, handed to the viewer the naive way.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    naive = page.locator('#run-view-viewer').evaluate("""async (element, text) => {
      const host = document.createElement('div');
      host.style.width = '200px'; host.style.height = '200px';
      document.body.append(host);
      const stage = new NGL.Stage(host, {backgroundColor: 'white'});
      const component = await stage.loadFile(new Blob([text], {type: 'text/plain'}),
                                             {ext: 'pdb', inferBonds: 'none'});
      return {atoms: component.structure.atomCount,
              models: component.structure.frames ? component.structure.frames.length : 0,
              trajectories: component.trajList.length};
    }""", frames_pdb())
    assert naive['atoms'] == 8 * 5, 'every model\'s atoms arrive as one structure'
    assert naive['models'] == 0, 'and no trajectory comes with it'
    assert naive['trajectories'] == 0, 'loadFile does not attach one'

    drawn = page.locator('#run-view-viewer').evaluate(MEASURE)
    assert drawn['atoms'] == 8, 'the panel draws one frame'
    assert drawn['frames'] == 5, 'and holds the trajectory the row plays'
    assert errors == []


# ------------------------------------------------------------------------------------- the door from the Runs table


def test_a_runs_table_row_links_to_its_own_run_view(dashboard, live_page):
    """D10: the list is one door to a run; this link is the other, and it lands on the run already drawn."""
    seed(dashboard)
    page, errors = live_page
    page.goto(f'{live_page.base_url}/detergent-validation/runs')
    expect(page.locator('.job')).to_have_count(5)

    link = page.locator(f'.job[data-id="{AA_RUN}"] .job-view-run')
    expect(link).to_have_count(1)
    assert link.get_attribute('href') == f'/detergent-validation/run-view?run={AA_RUN}'

    link.click()
    expect(page.locator('#runview')).to_be_visible()
    expect(page.locator('#run-view-list button[aria-pressed=true]')).to_contain_text(AA_RUN)
    expect(page.locator('#run-view-identity')).to_contain_text(AA_RUN)
    assert errors == []


def test_the_newest_published_result_is_resolved_even_when_it_lies_past_the_first_page(dashboard, live_page):
    """The reader walks the whole artifact index instead of trusting one page of it.

    The route pages the index (`limit` is capped at 100) and the index is ordered by directory, so this run's newest
    `analyses/snapshots/*/*/result.json` -- the record that names the frame series -- is on the second page. A reader
    that stopped at the first page resolves no record at all for it and lists no frame series.
    """
    planted = {'stages/2_mapping/mapped.gro': mapped_gro()} | many_attempts()
    assert len(planted) > PAGE_CAP, 'the fixture has to be past one page for this to test anything'
    plant(dashboard, MANY_RUN, job(MANY_RUN, 'aa_cg', 'Sorbitol series, many attempts', '2026-10-06T10:00:00+00:00'),
          planted)

    page, errors = live_page
    asked = []
    page.on('request', lambda request: asked.append(request.url))
    open_panel(page, live_page, run=MANY_RUN)
    wait_for_component(page, atoms=8)

    first = page.locator('#run-view-holds tr').first
    expect(first).to_contain_text('snapshots/CG-frames.pdb')
    assert first.get_attribute('aria-selected') == 'true'
    assert page.locator('#run-view-viewer').evaluate(MEASURE)['frames'] == 5, \
        'the newest record names the series, and the row plays it'
    pages = sorted({int(url.split('page=')[1].split('&')[0])
                    for url in asked if '/artifacts?' in url and 'page=' in url})
    assert pages and max(pages) > 1, f'the reader never asked for a page past the first: {pages}'
    assert errors == []


def test_the_rule_hands_an_all_atom_gro_to_the_guess_and_a_coarse_one_to_nothing(dashboard, live_page):
    """The bond rule itself, asked rather than inferred from a picture: this is where "no bonds" lived.

    Both the panel and the draft read this module, so its answer is the answer both of them draw by. An all-atom
    `.gro` gets the viewer's distance guess -- the format carries no bond records, and the guess is right about
    chemistry -- while a coarse-grained `.gro` gets nothing, because on a bead it is wrong by construction.
    """
    page, errors = live_page
    page.goto(f'{live_page.base_url}/')
    answer = page.evaluate("""async () => {
      const m = await import('/static/js/run-view-structure.js');
      return {
        all_atom_gro: m.loadParameters('', {path: '07_reference/lig.gro', runType: 'aa_only'}).inferBonds,
        coarse_gro: m.loadParameters('', {path: 'stages/2_mapping/mapped.gro', runType: 'aa_cg'}).inferBonds,
        states_its_own: m.loadParameters('CONECT', {path: 'a.pdb', runType: 'aa_only'}).inferBonds,
        all_atom_pdb: m.loadParameters('', {path: '07_reference/lig.pdb', runType: 'aa_only'}).inferBonds,
      };
    }""")
    assert answer == {'all_atom_gro': 'all', 'coarse_gro': 'none', 'states_its_own': 'none',
                      'all_atom_pdb': 'all'}, answer
    assert errors == []
