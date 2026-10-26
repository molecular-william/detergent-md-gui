"""The Run view panel, driven in a browser: one run, its own structures, its segments, its figures.

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
import re

from playwright.sync_api import expect

from . import panels

AA_RUN = 'aa00aa000001'
CG_RUN = 'cc00cc000002'
FRAMES_RUN = 'ff00ff000003'
PDC_RUN = 'dd00dd000004'
OSMOTIC_RUN = 'ee00ee000005'
#: A second protein-detergent run, for the tests that need the monitor to hold one run and then another.
PDC_OTHER = 'dd00dd000008'
#: A protein-detergent run whose stage files are planted, so `/api/jobs/<id>/trajectory` answers from them.
PDC_SEGMENTS_RUN = 'dd00dd000009'
#: A single-molecule run holding one trajectory, whose `single()` entry is named by its layout role.
ONE_TRAJECTORY_RUN = 'aa00aa00000a'
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


def six_bead_gro():
    """The extension's system after the removal path: fewer atoms than the legs before it, which is the boundary."""
    rows = ['Written by MDAnalysis', '    6']
    for index, (name, xyz) in enumerate(zip(BEADS[:6], MAPPED_NM[:6]), 1):
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
  const host = document.querySelector('#run-view-viewer-A');
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
    readout: document.querySelector('#run-view-readout-A').textContent,
    note: document.querySelector('#run-view-transport-note-A').textContent,
    // The caption is the panel's own statement of which file this component is (`<run> · <path> · <kind>`), so an
    // assertion on it says the structure just read belongs to that path rather than to whatever was drawn before.
    caption: document.querySelector('#run-view-what-A').textContent,
  };
}
"""


def open_panel(page, live_page, workspace='detergent-validation', run=None):
    query = f'?run={run}' if run else ''

    def ready(page):
        expect(page.locator('#runview')).to_be_visible()
        # The three sub-panels below each canvas sit collapsed -- that is the layout's own claim, and a reader opens the
        # one they want. A test that reads or clicks inside one opens it first, through the same `<details>` element.
        for panel in ('holds-details', 'frames-details', 'figures-details'):
            page.locator(f'#run-view-{panel}-A').evaluate('el => { el.open = true; }')

    return panels.open_panel(page, live_page.base_url, f'/{workspace}/run-view{query}', ready=ready)


def mark_stage(page):
    """Mark the component on the stage, so the *next* render can be told from the one already drawn.

    Call it after `open_panel` has settled and *before* the row is clicked. `draw()`
    (`dashboard/web/static/js/run-view-monitor.js:833`) clears the stage with `removeAllComponents()` and then builds
    the next component with `loadFile`, so a mark put on the current component cannot survive a real redraw, and the
    window between the clear and the load has no `compList[0]` at all. That is the per-*draw* discriminator.

    A per-*file* one cannot do this job: a row naming the file already on the stage (`stages/07_reference/lig.gro`
    under an AA run, drawn by `loadRun` on open) leaves the caption unchanged, so a wait on that path, or on an atom
    count those two files share, is satisfied before the click and never pins anything.
    """
    marked = page.locator('#run-view-viewer-A').evaluate("""el => {
      const stage = el.runViewStage;
      const first = stage && stage.compList && stage.compList[0];
      if (!stage || !first) return false;
      first.__stale = true;
      stage.__freshOwed = true;
      return true;
    }""")
    assert marked, 'mark_stage needs a component on the stage to mark, or the wait after it cannot tell a redraw'


def wait_for_component(page, atoms=None, drawn=None, fresh=False):
    """Wait for the component the viewer loaded -- and, when named, for *that file's* render and a *new* component.

    `atoms` alone is not a wait for a click on a second row. The panel's `draw()` clears the stage with
    `removeAllComponents()` and only then awaits `loadFile`, so between those two a predicate over
    `compList[0].structure` sees nothing at all, and before the clear it sees the structure that was already
    drawn -- which is the same eight beads here (`stages/2_mapping/mapped.gro` and
    `stages/3_initial_CG/LIG1.pdb` are both eight-bead files with seven bonds), so an atom count is satisfied
    by the previous file and the click is never waited for.

    `drawn` names the file the finished render has to be, read off the panel's own caption. `draw()` writes
    `Loading <path>…` *before* it touches the stage and `<run> · <path> · <kind>` after `loadFile` resolves, so the
    caption is compared as its own segments: a substring test over the whole line would also match a run id or a
    kind that happens to contain the text. This is file-level proof, and by construction it cannot discriminate a
    redraw of the file already drawn -- that is `fresh`'s job.

    `fresh` requires the component `mark_stage` marked to be *gone*: a new component, built by `loadFile`, carries
    no mark. It is what pins a click whose row names the file already on the stage, and it fails in the clear window
    (`compList[0]` undefined) rather than reading the previous render. `fresh` without a mark is a test bug and is
    reported as one instead of waiting thirty seconds for a predicate that can only pass early.
    """
    if fresh:
        owed = page.locator('#run-view-viewer-A').evaluate("el => !!el.runViewStage?.__freshOwed")
        assert owed, 'fresh=True must follow mark_stage(page); nothing was marked for it to displace'
    if drawn is not None:
        page.wait_for_function(
            """path => {
                 const caption = document.querySelector('#run-view-what-A');
                 const segments = (caption ? caption.textContent : '').split(' · ');
                 return segments.length >= 3 && segments[1] === path;
               }""",
            arg=drawn, timeout=30000)
    if fresh:
        page.wait_for_function(
            """() => {
                 const stage = document.querySelector('#run-view-viewer-A')?.runViewStage;
                 const first = stage?.compList?.[0];
                 if (!stage || !stage.__freshOwed || !first || first.__stale) return false;
                 stage.__freshOwed = false;
                 return true;
               }""",
            timeout=30000)
    page.wait_for_function(
        "() => document.querySelector('#run-view-viewer-A')?.runViewStage?.compList?.[0]?.structure",
        timeout=30000)
    if atoms is not None:
        # Optional chaining all the way: between `removeAllComponents()` and the load resolving, `compList[0]` is
        # undefined, and a predicate that throws is not a wait -- Playwright reports it instead of retrying.
        page.wait_for_function(
            "() => document.querySelector('#run-view-viewer-A')?.runViewStage?.compList?.[0]?.structure?.atomCount"
            f" === {atoms}",
            timeout=30000)


def select_row(page, text):
    row = page.locator('#run-view-holds-A tr').filter(has_text=text)
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
    # The list belongs to each monitor's own combo and is drawn when a reader reaches for it, so the count is taken
    # after focusing the input -- which is what a reader does before reading the list.
    page.locator('#run-view-choose-A').click()
    expect(page.locator('#run-view-list-A button')).to_have_count(4)

    jobs = [url.split('run_type=')[1].split('&')[0] for url in asked if '/api/jobs?' in url and 'run_type=' in url]
    assert sorted(set(jobs)) == ['aa_cg', 'aa_only', 'cg_composition', 'osmotic'], jobs
    assert not any('/api/jobs?' in url and 'run_type=' not in url for url in asked), \
        'the panel must ask the route for a run type, not page every run and narrow it here'

    offered = ' '.join(page.locator('#run-view-list-A button').all_inner_texts())
    assert PDC_RUN not in offered, f'a complex run is offered by the wrong workspace: {offered}'
    assert AA_RUN in offered and CG_RUN in offered
    # The count is the host's, and the requests above are what say the scope is this workspace's own.
    expect(page.locator('#run-view-note')).to_contain_text('completed run')
    assert errors == []


def test_picking_a_run_opens_it_once(dashboard, live_page):
    """One choice, one load. `pick()` called its callback twice, so every pick walked the artifacts, read `/figures`
    and built an NGL scene twice -- visible as duplicate requests, invisible as anything else."""
    seed(dashboard)
    page, errors = live_page
    asked = []
    page.on('request', lambda request: asked.append(request.url))
    open_panel(page, live_page)

    page.locator('#run-view-choose-A').click()
    expect(page.locator('#run-view-list-A button')).to_have_count(4)
    page.locator(f'#run-view-list-A button[data-id="{CG_RUN}"]').click()
    # The input carries the chosen run's id, which is also the wait: the loads below follow the pick.
    # The input is what says the pick landed: it is empty until a run is chosen.
    expect(page.locator('#run-view-choose-A')).not_to_have_value('')
    assert CG_RUN in page.locator('#run-view-choose-A').input_value()

    mine = [url for url in asked if f'/api/jobs/{CG_RUN}' in url and '/analyses' not in url]
    duplicated = sorted({url for url in mine if mine.count(url) > 1})
    assert duplicated == [], f'the pick loaded the same thing twice: {duplicated}'
    assert mine, 'the pick loaded nothing at all'
    assert errors == [], errors


def test_the_chooser_narrows_as_the_reader_types(dashboard, live_page):
    """The combo's own promise: every keystroke filters, over the run's label, molecule, type, id and date.

    This replaces the run-type select that used to narrow the list to one type at a time. That control is gone by the
    reader's own request -- a text input that filters as they type is what they asked for -- so the narrowing is
    asserted through the input instead, including the case where nothing matches and the panel says so.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page)
    field = page.locator('#run-view-choose-A')
    field.click()
    expect(page.locator('#run-view-list-A button')).to_have_count(4)

    field.fill(AA_RUN)
    field.dispatch_event('input')
    expect(page.locator('#run-view-list-A button')).to_have_count(1)
    expect(page.locator('#run-view-list-A button')).to_contain_text(AA_RUN)

    field.fill('nothing-matches-this-at-all')
    field.dispatch_event('input')
    expect(page.locator('#run-view-list-A button')).to_have_count(0)
    expect(page.locator('#run-view-list-A .none')).to_contain_text('No completed run matches')
    assert errors == []


def test_the_protein_detergent_workspace_offers_only_complex_runs(dashboard, live_page):
    """The other half of D2, from the other side: an AA-only run is not that workspace's to show."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, workspace='protein-detergent')
    page.locator('#run-view-choose-A').click()
    expect(page.locator('#run-view-list-A button')).to_have_count(1)
    expect(page.locator('#run-view-list-A button')).to_contain_text(PDC_RUN)
    assert errors == []


# ----------------------------------------------------------------------------------------------- an AA run, drawn


def test_an_aa_runs_gro_is_drawn_with_the_guess_that_is_right_about_chemistry(dashboard, live_page):
    """An all-atom `.gro` is bondless by *format*, not by intent: the guess draws the molecule it names.

    This test used to assert the opposite -- zero bonds on a `.gro` -- because the rule sent every `.gro` down the
    coarse-grained branch and emptied the store. That is right for a bead, where the guess is wrong by construction,
    and wrong for chemistry, which is the one case it is right about: the atomistic half of a comparison was left
    with no bonds at all. The readout names which guess the bonds came from, and the coarse-grained branch is held
    to its own answer by the tests above.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page, atoms=5)

    measured = page.locator('#run-view-viewer-A').evaluate(MEASURE)
    assert measured['atoms'] == 5
    assert measured['bonds'] > 0, 'an all-atom .gro keeps the guess its chemistry is drawn by'
    expect(page.locator('#run-view-readout-A')).to_contain_text('bonds the file states')
    expect(page.locator('#run-view-readout-A')).to_contain_text('bonds the viewer resolved')
    expect(page.locator('#run-view-readout-A')).to_contain_text("this viewer's distance guess")
    expect(page.locator('#run-view-transport-note-A')).to_contain_text('.gro')
    expect(page.locator('#run-view-what-A')).to_contain_text('stages/07_reference/lig.gro')
    assert errors == []


def test_an_aa_runs_molecule_is_the_one_case_the_viewers_own_guess_is_left_on(dashboard, live_page):
    """An all-atom `.pdb` with no `CONECT` is the third branch: the guess reproduces the chemistry."""
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page, atoms=5)

    mark_stage(page)
    select_row(page, 'lig1.pdb')
    wait_for_component(page, atoms=5, drawn='stages/common/molecule/MMFF/lig1.pdb', fresh=True)
    measured = page.locator('#run-view-viewer-A').evaluate(MEASURE)
    assert measured['atoms'] == 5
    assert measured['bonds'] > 0, 'the viewer\'s own distance guess reproduces a real molecule'
    expect(page.locator('#run-view-readout-A')).to_contain_text('bonds the file states')
    expect(page.locator('#run-view-readout-A')).to_contain_text('reproduces the chemistry')
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

    measured = page.locator('#run-view-viewer-A').evaluate(MEASURE)
    drawn = {tuple(pair) for pair in measured['pairs']}
    assert measured['atoms'] == 8
    assert measured['bonds'] == len(MODEL_BONDS), (
        f"the run's moleculetype states {len(MODEL_BONDS)} bonds and the viewer drew {measured['bonds']}")
    assert drawn == set(MODEL_BONDS), f"the drawn bonds are not the model's: {sorted(drawn ^ set(MODEL_BONDS))}"
    expect(page.locator('#run-view-what-A')).to_contain_text('stages/2_mapping/mapped.gro')
    expect(page.locator('#run-view-readout-A')).to_contain_text("bonds the run's own topology states")
    expect(page.locator('#run-view-readout-A')).to_contain_text("the run's own moleculetype, written as CONECT")
    # The readout names the file's own topology, not a directory: a protein-detergent run keeps its detergent's model
    # somewhere else entirely, and this sentence was the one that told a pdc reader to look under `3_initial_CG/`.
    expect(page.locator('#run-view-readout-A')).to_contain_text('its own topology file')
    assert 'stages/3_initial_CG/' not in page.locator('#run-view-readout-A').inner_text()
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

    measured = page.locator('#run-view-viewer-A').evaluate(MEASURE)
    assert measured['bonds'] == 0, 'a bond nothing declares must not be drawn'
    expect(page.locator('#run-view-readout-A')).to_contain_text('states no moleculetype')
    expect(page.locator('#run-view-readout-A')).to_contain_text('the picture claims no bonds')
    assert errors == []


def test_a_cg_file_that_carries_conect_is_drawn_from_it_and_never_guessed_at(dashboard, live_page):
    """Trap 1, measured on the component: seven records in, seven bonds drawn -- not fourteen.

    The wait is per-draw: the component drawn before the click is marked (`mark_stage`) and the wait requires a
    component that is not, because an atom count cannot tell this row from the one before it -- both files are eight
    beads with seven bonds. The path is named as well, so the caption has to have settled on
    `stages/3_initial_CG/LIG1.pdb` before the component is read at all.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)

    mark_stage(page)
    select_row(page, 'LIG1.pdb')
    wait_for_component(page, atoms=8, drawn='stages/3_initial_CG/LIG1.pdb', fresh=True)
    measured = page.locator('#run-view-viewer-A').evaluate(MEASURE)
    # The same instant as the structure read, and named on the panel's own caption: `draw()` writes the bond
    # provenance into this readout *after* `loadFile` resolves, so a measurement taken in the click's own window
    # would not see it -- but only a file that carries CONECT records reaches that branch, so the readout is what
    # says this is the CONECT file's structure rather than the mapped `.gro` that was drawn before the click.
    assert measured['caption'].split(' · ')[1:2] == ['stages/3_initial_CG/LIG1.pdb'], (
        f'the measurement was not taken on the file the click named: {measured["caption"]}')
    assert 'carries CONECT' in measured['readout'], (
        f'the measurement was not taken on the CONECT-carrying file: {measured["readout"]}')
    drawn = {tuple(pair) for pair in measured['pairs']}
    assert measured['bonds'] == len(MODEL_BONDS), (
        f'the file states {len(MODEL_BONDS)} bonds and the viewer drew {measured["bonds"]}: the CONECT records '
        f'were double-drawn with a distance guess ({sorted(drawn)})')
    assert drawn == set(MODEL_BONDS), f'the drawn bonds are not the file\'s own: {sorted(drawn ^ set(MODEL_BONDS))}'
    expect(page.locator('#run-view-readout-A')).to_contain_text('carries CONECT')
    expect(page.locator('#run-view-readout-A')).to_contain_text('the distance guess is off')
    assert errors == []


def test_the_guard_is_what_keeps_the_guess_out_of_a_conect_file(dashboard, live_page):
    """The counterfactual: without the guard, the file's seven records are drawn with the guess's own added on.

    Read through NGL directly rather than through the panel, because the panel must not offer a way to switch the
    guard off -- what this proves is that the parameter the guard sets is what stands between the two numbers.

    No row is clicked here: the counterfactual below is loaded in a host of its own with `inferBonds: 'all'` stated
    at the call, so nothing it measures comes from the panel's component. The click and the `atoms=8` wait that used
    to sit here pinned nothing -- the panel's file is eight beads before and after -- and read as if they did; the
    panel's own guard is proved by the test above.
    """
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)

    # The guess bites where beads sit closer than their stand-in elements' covalent radii sum, and the stand-ins are
    # now written where a reader finds them (`N` for the S class, `H` for T). Measured: at the file's own spacings
    # that sum is under every bonded pair, so the guess adds nothing and the counterfactual needs beads packed
    # closer. The subject is the *parameter*, so the fixture is a compressed copy of the same bead file rather than
    # the file a run writes -- what must hold either way is that the guard is the difference between the file's
    # seven records and more.
    packed = [tuple(value * NANOMETRE_TO_ANGSTROM * 0.5 for value in xyz) for xyz in MAPPED_NM]
    measured = page.locator('#run-view-viewer-A').evaluate("""async (element, text) => {
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
    mark_stage(page)
    select_row(page, 'LIG1.pdb')
    wait_for_component(page, atoms=8, drawn='stages/3_initial_CG/LIG1.pdb', fresh=True)

    measured = page.locator('#run-view-viewer-A').evaluate(MEASURE)
    drawn = [None if value is None else round(value / NANOMETRE_TO_ANGSTROM, 4) for value in measured['radii']]
    expected = [round(RADII_NM[SIZES[name]] * DRAWN_BEAD_SCALE, 4) for name in BEADS]
    assert drawn == expected, f'the beads are not drawn at their own size classes: {drawn} against {expected}'
    # The stand-in elements are nearly the same size as each other; the model's classes are not.
    assert len(set(drawn)) == 2, 'a size ranking from the element column, not the model'
    expect(page.locator('#run-view-readout-A')).to_contain_text('model.json size classes')
    expect(page.locator('#run-view-readout-A')).to_contain_text(f'drawn at {DRAWN_BEAD_SCALE}x')
    assert errors == []


# ---------------------------------------------------------------------------------------------------------- figures


#: Martini 3's polarity families as `ngl-beads.js` colours them. This fixture's moleculetype types every bead
#: `SP1r`, which is polar, so the whole mapped model is one colour and the legend is what names it.
FAMILY_COLOURS = {'unstated': '#cccccc', 'C': '#7048e8', 'N': '#e8590c', 'P': '#2f9e44', 'Q': '#2b6cb0'}

#: The colours the canvas resolved, and the legend under it read back from the page.
MEASURE_FAMILY = """
async () => {
  const component = document.querySelector('#run-view-viewer-A').runViewStage.compList[0];
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
    mark_stage(page)
    select_row(page, 'md.gro')
    wait_for_component(page, atoms=8, drawn='stages/4_CG_sim/md.gro', fresh=True)

    measured = page.locator('#run-view-viewer-A').evaluate(MEASURE_FAMILY)
    assert measured['scheme'] == 'bfactor', measured['scheme']
    assert measured['colours'] == [FAMILY_COLOURS['P']] * 8, measured['colours']
    assert measured['hidden'] is False, 'a coarse picture with no legend under it'
    assert [entry['family'] for entry in measured['entries']] == ['unstated', 'C', 'N', 'P', 'Q']
    assert {entry['declared'] for entry in measured['entries']} == set(FAMILY_COLOURS.values())

    # The all-atom sibling: no legend, because there is no family to decode.
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page)
    # `stages/07_reference/lig.gro` is the file `loadRun` already drew on open, so a caption or atom-count wait
    # cannot tell this click from the render it replaces -- the per-draw mark is the only discriminator here, and
    # the path is kept because the file the legend must *not* appear for is part of the claim.
    mark_stage(page)
    select_row(page, 'lig.gro')
    wait_for_component(page, atoms=5, drawn='stages/07_reference/lig.gro', fresh=True)
    atomistic = page.locator('#run-view-viewer-A').evaluate(MEASURE_FAMILY)
    assert atomistic['hidden'] is True, 'an all-atom structure got a bead legend'
    assert errors == []


def test_figures_are_listed_and_opened_inline_through_the_artifact_route(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=CG_RUN)
    wait_for_component(page, atoms=8)

    link = page.locator('#run-view-figures-A a')
    expect(link).to_have_count(1)
    href = link.get_attribute('href')
    assert href == f'/api/jobs/{CG_RUN}/artifacts/stages/5_assessment/score_matrix_LIG1.png?inline=1', href
    assert link.get_attribute('target') == '_blank'
    expect(page.locator('#run-view-figures-note-A')).to_contain_text('zoomable')
    assert errors == []


def test_a_run_with_no_figure_says_so_instead_of_showing_an_empty_list(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=AA_RUN)
    wait_for_component(page, atoms=5)
    expect(page.locator('#run-view-figures-A a')).to_have_count(0)
    expect(page.locator('#run-view-figures-note-A')).to_contain_text('published no figure')
    assert errors == []


def test_a_complex_run_plays_here_and_its_segments_say_where_it_is_rebuilt(dashboard, live_page):
    """A protein-detergent run is drawn in this panel now, with the CG chain's segments under the frames.

    What used to make this panel unable to draw one was that the run's CG trajectory matched no role in the run
    layout, so the snapshots analysis skipped it. The layout resolves it and `/api/jobs/<id>/trajectory` states which
    legs are one system and where the system is rebuilt (its own integration test pins that answer, and it is measured
    on the real run); this test is the panel's half, with the endpoint stubbed so the rendering is what is under test.
    A run drawn here must also stop saying it is drawn elsewhere, which the caption assertion below holds.
    """
    seed(dashboard)
    page, errors = live_page
    segments = {'id': PDC_RUN, 'run_type': 'pdc', 'why': None, 'boundaries': [
        {'at': 'CG extension MD', 'after': 'CG assessment MD', 'atoms_from': 8, 'atoms_to': 6}],
        'segments': [
            {'name': 'System preparation', 'atoms': 4, 'trajectory': None, 'group': None,
             'note': 'the built system, before solvation'},
            {'name': 'NVT equilibration', 'atoms': 8, 'trajectory': 'stages/1_system/system.gro', 'group': 1},
            {'name': 'CG extension MD', 'atoms': 6, 'trajectory': 'stages/1_system/system.gro', 'group': 2},
        ]}
    hits = []

    def serve_trajectory(route):
        hits.append(route.request.url)
        route.fulfill(json=segments)

    page.route(re.compile(r'/api/jobs/[^/]+/trajectory'), serve_trajectory)
    open_panel(page, live_page, workspace='protein-detergent', run=PDC_RUN)
    assert PDC_RUN in page.locator('#run-view-choose-A').input_value()

    # `#run-view-segments-A` *is* the tbody, so the rows are its own children, not a `tbody` inside it.
    rows = page.locator('#run-view-segments-A tr')
    expect(rows).to_have_count(3, timeout=30000)
    expect(rows.nth(0)).to_contain_text('System preparation')
    # A stage with no trajectory is idle, and the row says *why* it is: a bare `true` cannot tell "nothing to play"
    # from "the same file as another row".
    expect(rows.nth(0)).to_have_attribute('data-idle', 'no-trajectory')
    # `group` is a system: group 1 on the measured run holds four distinct `.xtc` files, so calling it a trajectory
    # contradicted the table above the sentence.
    expect(page.locator('#run-view-segments-note-A')).to_contain_text('3 stages in 2 systems')
    boundary = page.locator("#run-view-segments-A tr[data-boundary='true']")
    expect(boundary).to_have_count(1)
    expect(boundary).to_contain_text('CG extension MD')
    expect(boundary).to_contain_text('system rebuilt here: 6 atoms, from 8')
    assert 'drawn in Complexes' not in page.locator('#run-view-what-A').inner_text()
    assert hits, 'the panel asked for the run\'s trajectory'
    assert errors == []


def test_the_segments_are_asked_for_even_when_the_artifact_index_fails(dashboard, live_page):
    """`/trajectory` answers from the stage files alone, so a broken index must not silence it.

    It used to be asked after `await draw(...)`, behind two `return`s -- an artifact index that failed and a
    structure list that matched nothing -- so a run in either state never asked, never printed the endpoint's own
    `why`, and left the reader with an empty panel and no reason for it. The call is fired, not awaited: this test
    also holds that a slow answer cannot be what draws the canvas, because the index here fails before any canvas.
    """
    seed(dashboard)
    page, errors = live_page
    segments = {'id': PDC_RUN, 'run_type': 'pdc', 'why': None, 'segments': [
        {'name': 'System preparation', 'atoms': 4, 'trajectory': None, 'group': None},
        {'name': 'CG assessment MD', 'atoms': 4, 'trajectory': 'stages/1_system/system.gro', 'group': 1}]}
    page.route(re.compile(r'/api/jobs/[^/]+/trajectory'), lambda route: route.fulfill(json=segments))
    page.route(re.compile(r'/api/jobs/[^/]+/artifacts'),
               lambda route: route.fulfill(status=500, json={'error': 'the index is unavailable'}))

    open_panel(page, live_page, workspace='protein-detergent', run=PDC_RUN)

    expect(page.locator('#run-view-segments-A tr')).to_have_count(2, timeout=30000)
    expect(page.locator('#run-view-segments-note-A')).to_contain_text('2 stages in 1 system')
    expect(page.locator('#run-view-holds-A')).to_contain_text('the index is unavailable')
    assert errors == []


def test_a_failed_segments_answer_for_the_previous_run_does_not_land_in_the_next(dashboard, live_page):
    """The token test is the catch block's first statement too, or run A's failure is printed in run B's panel.

    Run A's `/trajectory` is held open here until the monitor has already moved to run B, which is the ordering the
    panel cannot avoid: the answer is fired and the reader can pick another run before it lands. Its failure belongs
    to the row the reader left.
    """
    seed(dashboard)
    plant(dashboard, PDC_OTHER, job(PDC_OTHER, 'pdc', 'Complex build 2', '2026-10-04T11:00:00+00:00'),
          {'stages/1_system/system.gro': mapped_gro()})
    page, errors = live_page
    held = []
    second = {'id': PDC_OTHER, 'run_type': 'pdc', 'why': None, 'segments': [
        {'name': 'System preparation', 'atoms': 8, 'trajectory': 'stages/1_system/system.gro', 'group': 1}]}

    def serve(route):
        if PDC_RUN in route.request.url:
            held.append(route)      # answered by this test, after the monitor has moved on
            return
        route.fulfill(json=second)

    page.route(re.compile(r'/api/jobs/[^/]+/trajectory'), serve)
    open_panel(page, live_page, workspace='protein-detergent', run=PDC_RUN)
    page.locator('#run-view-choose-A').click()
    page.locator(f'#run-view-list-A button[data-id="{PDC_OTHER}"]').click()
    expect(page.locator('#run-view-segments-note-A')).to_contain_text('1 stage in 1 system', timeout=30000)

    assert held, 'the first run\'s answer was never held, so nothing stale was left to land'
    for route in held:
        route.fulfill(status=500, json={'error': 'the first run could not be read'})
    page.wait_for_timeout(500)

    expect(page.locator('#run-view-segments-note-A')).to_contain_text('1 stage in 1 system')
    assert 'the first run could not be read' not in page.locator('#run-view-segments-note-A').inner_text(), \
        'a failure that belongs to the run the monitor left was written into the run it holds'
    assert errors == []


def test_the_boundary_row_is_read_from_the_endpoints_own_fields(dashboard, live_page):
    """The table is drawn from a real `/api/jobs/<id>/trajectory` answer, not from a stub this file wrote.

    The stub above hard-codes `at`/`atoms_from` and `atoms`, so renaming any of them in `analysis/runs/segments.py`
    would leave it green while the panel printed "from undefined". This plants a protein-detergent run's own stage
    files -- two systems of different atom counts, six in the extension and eight in the assessment -- and lets the
    endpoint answer.
    """
    plant(dashboard, PDC_SEGMENTS_RUN, job(PDC_SEGMENTS_RUN, 'pdc', 'Complex build 3', '2026-10-04T12:00:00+00:00'),
          {'stages/1_system/system.gro': six_bead_gro(),
           'stages/2_assessment/prod/run.gro': mapped_gro(),
           'stages/2_assessment/prod/whole.xtc': 'the assessment leg\'s trajectory, never read by this endpoint\n',
           'stages/4_extension/prod/run.gro': six_bead_gro(),
           'stages/4_extension/prod/whole.xtc': 'the extension\'s own trajectory, a different file\n'})
    page, errors = live_page

    open_panel(page, live_page, workspace='protein-detergent', run=PDC_SEGMENTS_RUN)

    rows = page.locator('#run-view-segments-A tr')
    expect(rows).to_have_count(3, timeout=30000)
    expect(page.locator('#run-view-segments-note-A')).to_contain_text('3 stages in 2 systems')
    boundary = page.locator("#run-view-segments-A tr[data-boundary='true']")
    expect(boundary).to_contain_text('CG extension MD')
    expect(boundary).to_contain_text('system rebuilt here: 6 atoms, from 8')
    # The row with nothing to play is marked as such, and the duplicate the endpoint drops is marked differently.
    expect(page.locator("#run-view-segments-A tr[data-idle='no-trajectory']")).to_have_count(1)
    assert errors == []


def test_a_single_molecule_run_shows_no_stage_table(dashboard, live_page):
    """A single-molecule run has one trajectory, so a table whose Stage column holds a layout role is not a table.

    `segments.single()` names its one entry by the layout role (`cg_stage_trajectory` here) rather than by a stage,
    and the sr-only caption calls the table the CG chain's -- so the table is drawn for a `pdc` answer only. A run
    with nothing to play still says so, which is the sentence kept for both run types.
    """
    seed(dashboard)
    plant(dashboard, ONE_TRAJECTORY_RUN, job(ONE_TRAJECTORY_RUN, 'aa_cg', 'Maltose CG, one trajectory',
                                             '2026-10-07T10:00:00+00:00'),
          {'stages/4_CG_sim/md.gro': mapped_gro(),
           'stages/4_CG_sim/md.xtc': 'the stage\'s own trajectory, never read by this endpoint\n'})
    page, errors = live_page
    open_panel(page, live_page, run=ONE_TRAJECTORY_RUN)
    wait_for_component(page, atoms=8)

    expect(page.locator('#run-view-segments-table-A')).to_be_hidden()
    expect(page.locator('#run-view-segments-wrap-A')).to_be_hidden()
    assert 'cg_stage_trajectory' not in page.locator('#run-view-segments-A').inner_text()

    # A run with nothing to play still gets the endpoint's own sentence rather than silence.
    open_panel(page, live_page, run=AA_RUN)
    expect(page.locator('#run-view-segments-table-A')).to_be_hidden()
    expect(page.locator('#run-view-segments-note-A')).to_contain_text('offers no trajectory to play')

    # And a protein-detergent run is the table: its rows are stages, in the order the run ran them.
    open_panel(page, live_page, workspace='protein-detergent', run=PDC_RUN)
    expect(page.locator('#run-view-segments-table-A')).to_be_visible()
    expect(page.locator('#run-view-segments-A tr')).to_have_count(1)
    assert errors == []


# ----------------------------------------------------------------------------------------------------- the frames


def test_the_published_frame_series_is_listed_first_and_is_the_file_the_row_plays(dashboard, live_page):
    seed(dashboard)
    page, errors = live_page
    open_panel(page, live_page, run=FRAMES_RUN)
    wait_for_component(page, atoms=8)

    first = page.locator('#run-view-holds-A tr').first
    expect(first).to_contain_text('snapshots/CG-frames.pdb')
    assert first.get_attribute('aria-selected') == 'true'
    measured = page.locator('#run-view-viewer-A').evaluate(MEASURE)
    assert measured['frames'] == 5, 'the multi-model PDB must be a trajectory, not five models drawn at once'
    # The series carries the model's own bonds, as the producer writes them (`pdc_view.series_pdb`). This asserted
    # zero until the file was made to carry them: a published series with no CONECT is a picture of grey spheres
    # with no connectivity, which is the defect a reader reported from the panel.
    assert measured['bonds'] == len(MODEL_BONDS), \
        f"the series drew {measured['bonds']} bonds for a model that states {len(MODEL_BONDS)}"
    expect(page.locator('#run-view-frames-A button')).to_have_count(3)
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

    naive = page.locator('#run-view-viewer-A').evaluate("""async (element, text) => {
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

    drawn = page.locator('#run-view-viewer-A').evaluate(MEASURE)
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
    # Waited for rather than read once: the link lands on the run view and the host chooses the run it names, which
    # takes the requests it takes. The claim is that the run is chosen by the time the page has settled.
    page.wait_for_function(
        f"() => (document.querySelector('#run-view-choose-A')?.value || '').includes('{AA_RUN}')", timeout=20000)
    expect(page.locator('#run-view-identity-A')).to_contain_text(AA_RUN)
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

    first = page.locator('#run-view-holds-A tr').first
    expect(first).to_contain_text('snapshots/CG-frames.pdb')
    assert first.get_attribute('aria-selected') == 'true'
    assert page.locator('#run-view-viewer-A').evaluate(MEASURE)['frames'] == 5, \
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


# ------------------------------------------------------------------------------------------- the layout itself


def test_the_run_view_is_two_monitors_each_with_a_combo_and_three_panels_below(dashboard, live_page):
    """The shape that was asked for, asserted as the page: two monitors, a combo and three panels on each.

    Adopted from the draft that was judged and re-pointed at the panel it became. Two canvases side by side, a
    "choose a run" combo above each, and "what this run holds" / "frames" / "figures" below each one, collapsed --
    the collapse is the claim, and a reader opens the one they want. Only completed runs are ever offered, which the
    host's own requests say rather than its intentions.
    """
    seed(dashboard)
    page, errors = live_page
    asked = []
    page.on('request', lambda request: asked.append(request.url))
    # Navigated here rather than through `open_panel`, because that helper opens the three panels a reader may want
    # to read -- and "collapsed by default" is one of the things this test is about.
    page.goto(f'{live_page.base_url}/detergent-validation/run-view')
    expect(page.locator('#runview')).to_be_visible()
    # Two monitors and monitor A's canvas. Monitor B holds whatever the host paired it with, and a run whose
    # structures the fixture did not plant draws nothing -- which is a fact about the fixture, not about the layout.
    page.wait_for_function(
        "() => document.querySelectorAll('.monitor[data-side]').length === 2"
        " && document.querySelector('#run-view-viewer-A canvas')", timeout=30000)

    assert page.locator('#run-view-monitors .monitor').count() == 2
    canvas = {side: page.locator(f'#run-view-viewer-{side}').bounding_box() for side in ('A', 'B')}
    assert canvas['A']['x'] < canvas['B']['x'], 'the monitors are side by side, not stacked'
    for side in ('A', 'B'):
        assert page.locator(f'#run-view-choose-{side}').input_value(), f'monitor {side} holds no run'
        for panel in ('holds', 'frames', 'figures'):
            details = page.locator(f'#run-view-{panel}-details-{side}')
            assert details.evaluate('el => el.open') is False, f'{panel}-{side} opened itself'
            assert details.bounding_box()['y'] >= canvas[side]['y'], f'{panel}-{side} is not below the canvas'
    assert asked and all('status=completed' in url for url in asked if '/api/jobs?' in url), \
        'only completed runs are offered'
    assert errors == []
