// One monitor of the Run view: a run selected from a combo, its structure on a canvas, and its own "what this run
// holds" / "CG chain segments" / "figures" panels below the canvas, collapsed.
//
// Two of these sit side by side (`run-view.js` builds them), which is why everything here is scoped to `side`: every
// element id in this file is written `#<name>-<side>`, resolved once through `id()`, and never a bare `#run-view-…`
// that two monitors would fight over. The alternative -- one panel that swaps runs -- is the thing this replaced.
//
// The per-run work below is the panel's own: the structure index, the bond rule's application, the bead sizing, the
// readout, and the CG chain's segments (which legs are one system, and where the system is rebuilt, from
// `/api/jobs/<id>/trajectory`). The bond rule is one module (`run-view-structure.js`), the bead table is another
// (`ngl-beads.js`), and the chooser filters as you type over the run's own label, molecule, type, id and date.
// Nothing here decides anything twice.

import { $, api } from './shared.js';
import { BEAD_FAMILY_PARAMETERS, BEAD_RADIUS_PARAMETERS, applyBeadRadii, renderBeadLegend, sizeClassOf } from './ngl-beads.js';
import { conectCount, dropBonds, inStage, isCoarseGrained, loadParameters, structureExtension,
         structureRank } from './run-view-structure.js';
import { runViewExtensionFor } from './run-view-extension.js';

//: The route pages the artifact index and caps `limit` at 100, so every request here states its own limit.
const PAGE_LIMIT = 100;
//: D18 -- the scale this panel draws its beads at, on top of `ngl-beads.js`'s table, for reading only.
const BEAD_SCALE = 0.3;

export function createMonitor({root, side, runs, onPick}) {
  const id = name => `#${name}-${side}`;
  root.innerHTML = monitorMarkup(side);
  // Resolved once, by the monitor's own ids. Every lookup in this file goes through one of these handles, so two
  // monitors in one page cannot reach into each other.
  const holds = $(id('run-view-holds'));
  const identity = $(id('run-view-identity'));
  const holdsCount = $(id('run-view-holds-count'));
  const what = $(id('run-view-what'));
  const segmentsWrap = $(id('run-view-segments-wrap'));
  const segmentsTable = $(id('run-view-segments-table'));
  const segmentsBody = $(id('run-view-segments'));
  const segmentsNote = $(id('run-view-segments-note'));
  const segmentsCount = $(id('run-view-segments-count'));
  const viewer = $(id('run-view-viewer'));
  const readoutHost = $(id('run-view-readout'));
  const figures = $(id('run-view-figures'));
  const figuresNote = $(id('run-view-figures-note'));
  const figuresCount = $(id('run-view-figures-count'));
  const legend = $(id('run-view-legend'));

  let selected = null;               // the run this monitor holds
  let structures = [];
  let sizeClasses = null;

  // The counts in the three summaries are read off the panels themselves rather than tracked separately, so a
  // collapsed panel still says how much is behind it and no second bookkeeping can disagree with the first.
  function refreshCounts() {
    holdsCount.textContent = holds.querySelectorAll('tr').length ? `(${holds.querySelectorAll('tr').length})` : '';
    const segments = segmentsBody.querySelectorAll('tr').length;
    segmentsCount.textContent = segments ? `(${segments})` : '';
    figuresCount.textContent = figures.querySelectorAll('li').length ? `(${figures.querySelectorAll('li').length})` : '';
  }
  for (const host of [holds, segmentsBody, figures, figuresNote]) {
    new MutationObserver(refreshCounts).observe(host, {childList: true, subtree: true, characterData: true});
  }

  // ------------------------------------------------------------------------------------------------ the combo

  const combo = chooser(root, side, runs, job => onPick(job));


// The monitor's own markup, built here rather than in the page template: two of everything is the layout, and the
// ids are the only thing that differs between the two. The `<details>` are collapsed, which is what "minimizable and
// minimized by default" asked for, and each summary carries the count of what is behind it.
function monitorMarkup(side) {
  return `
  <div class="monitor" data-side="${side}">
    <div class="card monitor-head">
      <div class="chooser" data-open="false">
        <label class="grow"><span class="hint cap">Choose a run (completed only)</span>
          <input type="text" class="filter" id="run-view-choose-${side}" autocomplete="off" spellcheck="false"
                 placeholder="type a molecule, run type, id or date…"></label>
        <div class="list" role="listbox" id="run-view-list-${side}"></div>
      </div>
    </div>
    <div class="card run-view-stage">
      <div id="run-view-viewer-${side}" class="run-view-viewer" role="img"
           aria-label="Structure from the run this monitor holds"></div>
      <div id="run-view-legend-${side}" class="bead-legend" data-bead-legend hidden
           aria-label="Bead colour by Martini 3 polarity family"></div>
      <div id="run-view-readout-${side}" class="run-view-readout"></div>
    </div>
    <details class="card run-view-sub" id="run-view-holds-details-${side}">
      <summary>what this run holds <span class="count" id="run-view-holds-count-${side}"></span></summary>
      <div class="body">
        <p class="hint" id="run-view-identity-${side}"></p>
        <p id="run-view-what-${side}"></p>
        <div class="table-scroll"><table class="run-view-structures">
          <caption class="sr-only">Structure files in the run this monitor holds</caption>
          <thead><tr><th scope="col">File</th><th scope="col">Bonds</th></tr></thead>
          <tbody id="run-view-holds-${side}"><tr><td colspan="2">No run selected.</td></tr></tbody>
        </table></div>
      </div>
    </details>
    <details class="card run-view-sub" id="run-view-segments-details-${side}">
      <summary>CG chain segments <span class="count" id="run-view-segments-count-${side}"></span></summary>
      <div class="body">
        <div class="table-scroll" id="run-view-segments-wrap-${side}" hidden>
          <table class="run-view-segments" id="run-view-segments-table-${side}">
            <caption class="sr-only">The CG MD segments this run holds, in stage order</caption>
            <thead><tr><th scope="col">Stage</th><th scope="col">Atoms</th>
              <th scope="col">Trajectory</th><th scope="col">Note</th></tr></thead>
            <tbody id="run-view-segments-${side}"></tbody>
          </table>
          <p class="hint" id="run-view-segments-note-${side}"></p>
        </div>
      </div>
    </details>
    <details class="card run-view-sub" id="run-view-figures-details-${side}">
      <summary>figures <span class="count" id="run-view-figures-count-${side}"></span></summary>
      <div class="body">
        <ul id="run-view-figures-${side}" class="run-view-figures"></ul>
        <p class="hint" id="run-view-figures-note-${side}"></p>
      </div>
    </details>
  </div>`;
}

// The combo: an input with its own filtered listbox, so a reader types and the list narrows. Words in any order,
// matched against what a reader would type, and only completed runs are ever offered -- the host filters that, and
// this says how many were held back rather than hiding them silently.
function chooser(root, side, runs, onPick) {
  const box = root.querySelector('.chooser');
  const input = root.querySelector('.filter');
  const list = root.querySelector('.list');
  let selected = null, active = 0;
  //: What the reader has typed *since* they last reached for the box. The input also carries the chosen run's own
  //: label, so filtering by its value would filter every run out the moment a reader clicked the box without
  //: typing -- which is exactly what happened, and what an empty list under a focused box looks like.
  let query = '';

  const matches = (job, text) => {
    const needle = String(text || '').trim().toLowerCase();
    if (!needle) return true;
    const haystack = `${job.label || ''} ${job.molecule_id || ''} ${job.run_type || ''} ${job.id || ''} `
      + `${String(job.created || '').slice(0, 10)}`.toLowerCase();
    return needle.split(/\s+/).every(word => haystack.includes(word));
  };

  function render() {
    const shown = (runs || []).filter(job => matches(job, query));
    active = Math.min(active, Math.max(shown.length - 1, 0));
    box.dataset.open = 'true';
    if (!shown.length) {
      list.innerHTML = '<div class="none">No completed run matches that.</div>';
      return;
    }
    const groups = [];
    for (const job of shown) {
      const type = job.run_type || 'other';
      if (!groups.length || groups[groups.length - 1].type !== type) groups.push({type, jobs: []});
      groups[groups.length - 1].jobs.push(job);
    }
    list.replaceChildren(...groups.flatMap(group => {
      const head = document.createElement('div');
      head.className = 'group';
      head.textContent = group.type;
      return [head, ...group.jobs.map(job => {
        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute('role', 'option');
        button.dataset.id = job.id;
        button.innerHTML = `<span>${job.label || job.molecule_id || job.id}</span> `
          + `<span class="meta">· ${job.run_type} · ${job.id} · ${String(job.created || '').slice(0, 10)}</span>`;
        button.dataset.selected = String(selected && selected.id === job.id);
        return button;
      })];
    }));
  }

  function pick(job) {
    if (!job) return;
    selected = job;
    input.value = `${job.label || job.molecule_id || job.id} · ${job.run_type} · ${job.id}`;
    query = '';
    box.dataset.open = 'false';
    // Once. This used to call onPick here *and* above the field updates, so every pick opened the run twice: two
    // artifact walks, two `/figures` reads and two NGL loads for one choice.
    if (onPick) onPick(job);
  }

  input.addEventListener('focus', () => { query = ''; active = 0; render(); });
  input.addEventListener('input', () => { query = input.value; active = 0; render(); });
  input.addEventListener('keydown', event => {
    const shown = (runs || []).filter(job => matches(job, query));
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      active = Math.max(0, Math.min(shown.length - 1, active + (event.key === 'ArrowDown' ? 1 : -1)));
      list.querySelectorAll('button').forEach((button, index) => button.dataset.active = String(index === active));
      return;
    }
    if (event.key === 'Enter') { event.preventDefault(); pick(shown[active]); return; }
    if (event.key === 'Escape') box.dataset.open = 'false';
  });
  list.addEventListener('click', event => {
    const button = event.target.closest('button[data-id]');
    if (button) pick((runs || []).find(job => job.id === button.dataset.id));
  });
  document.addEventListener('click', event => {
    if (!box.contains(event.target)) box.dataset.open = 'false';
  });

  return {
    set: job => { selected = job; input.value = job
      ? `${job.label || job.molecule_id || job.id} · ${job.run_type} · ${job.id}` : ''; },
    get: () => selected,
    focus: () => input.focus(),
  };
}


  async function loadRun(job) {
    viewer.hidden = false;
    // Who this monitor is holding, in one line: the id, what the run is called, the molecule it is about and the
    // day it ran. It was the list that used to say this, and the list is two combos now.
    identity.textContent = `${job.id} · ${job.label || 'untitled'} · `
      + `${job.molecule_name || job.detergent || '—'}`
      + (job.created ? ` · ${String(job.created).slice(0, 10)}` : '');
    what.textContent = 'Reading what this run holds…';
    holds.replaceChildren(row('Reading the run directory…', ''));
    // The segments are asked for here -- before the artifact index, the structure gate and the canvas -- and fired
    // rather than awaited: `/trajectory` answers from the run's stage files alone, so neither an index that failed
    // nor a structure list that matched nothing can stop the panel asking, and the endpoint's own `why` is printed
    // for a run with nothing to list.
    loadSegments(job);

    let entries = [];
    try {
      const [gro, pdb] = await Promise.all([
        artifactIndex(job.id, '.gro'), artifactIndex(job.id, '.pdb')]);
      entries = dedupe([...gro, ...pdb]);
    } catch (error) {
      holds.replaceChildren(row(`The run directory could not be read: ${error.message}`, ''));
      return;
    }

    structures = entries
      .filter(entry => inStage(entry.path) && structureExtension(entry.path)
                       && !entry.path.includes('/inputs/'))
      .map(entry => ({path: entry.path, rank: structureRank(entry.path)}))
      .sort((first, second) => first.rank - second.rank || second.path.localeCompare(first.path));

    renderHolds(job);
    loadFigures(job);
    sizeClasses = await loadSizeClasses(job);
    if (!structures.length) {
      what.textContent = 'This run holds no structure file this viewer can open (.gro or .pdb under stages/).';
      readout([]);
      return;
    }
    await draw(job, structures[0].path);
  }

  async function artifactIndex(jobId, term) {
    // A page is not the index. The route pages the artifact index and caps `limit` at 100, and the index is walked
    // in *directory* order rather than by age, so a run that has written many files can hold a structure past the
    // first page. The reader therefore walks every page until the last short one and returns the whole index.
    const entries = [];
    for (let page = 1; ; page += 1) {
      const query = new URLSearchParams({limit: String(PAGE_LIMIT), page: String(page), search: term});
      const body = await api(`/api/jobs/${encodeURIComponent(jobId)}/artifacts?${query}`);
      const held = body.artifacts || [];
      entries.push(...held);
      const total = Number(body.total);
      if (held.length < PAGE_LIMIT || !Number.isFinite(total) || entries.length >= total) break;
    }
    return dedupe(entries);
  }

  function dedupe(entries) {
    // The searches overlap in principle, and an entry counted twice is a row with two buttons for one file.
    const seen = new Set();
    return entries.filter(entry => !seen.has(entry.path) && seen.add(entry.path));
  }

  function row(path, bonds) {
    const line = document.createElement('tr');
    const file = document.createElement('td');
    const code = document.createElement('code');
    code.textContent = path;
    file.append(code);
    const bondCell = document.createElement('td');
    bondCell.textContent = bonds;
    line.append(file, bondCell);
    return line;
  }

  function renderHolds(job) {
    holds.replaceChildren(...structures.map(entry => {
      // A coarse-grained `.gro` is served with the run's own `[ bonds ]` + `[ constraints ]` written as CONECT (the
      // structure route); an all-atom `.gro` carries none, which is what the row says.
      const bonds = structureExtension(entry.path) !== 'gro'
        ? 'read when the file is opened'
        : (isCoarseGrained(entry.path, job.run_type)
            ? "the run's own [ bonds ] + [ constraints ], written as CONECT by the structure route"
            : 'none — a .gro carries no bond records');
      const line = row(entry.path, bonds);
      line.setAttribute('aria-selected', String(entry.path === (structures[0] || {}).path));
      line.style.cursor = 'pointer';
      line.addEventListener('click', () => { draw(job, entry.path).catch(error => { what.textContent = error.message; }); });
      return line;
    }));
  }

  // The run's stage chain: which legs are one system, and where the system is rebuilt, read from
  // `/api/jobs/<id>/trajectory` (which answers from the run's own stage files). A run whose stage chain a feature
  // owns draws its own table through that feature's `runSelected` hook; the engine keeps only the sentence a run
  // with nothing to play gets, so an install without the feature still says why the sub-panel is empty.
  let segmentsToken = 0;

  async function loadSegments(job) {
    // Every const this function dereferences, guarded together: guarding one of the four is a guard that lets the
    // others throw the moment a page renders without them.
    if (!segmentsWrap || !segmentsTable || !segmentsBody || !segmentsNote) return;
    const token = (segmentsToken += 1);
    segmentsWrap.hidden = true;
    segmentsBody.replaceChildren();
    segmentsNote.textContent = '';
    let answer;
    try {
      answer = await api(`/api/jobs/${encodeURIComponent(job.id)}/trajectory`);
    } catch (error) {
      // The token test comes first here too: a failure that belongs to the run the monitor has already left is that
      // run's failure, and writing it into the next run's panel names an error the reader is not looking at.
      if (token !== segmentsToken) return;
      segmentsTable.hidden = true;
      segmentsWrap.hidden = false;
      segmentsNote.textContent = `The segments could not be read: ${error.message}`;
      return;
    }
    if (token !== segmentsToken) return;   // the monitor moved to another run while this answered
    const why = (answer && answer.why) || '';
    const extension = runViewExtensionFor(job);
    if (extension && typeof extension.runSelected === 'function') {
      await extension.runSelected({
        job, answer,
        nodes: {wrap: segmentsWrap, table: segmentsTable, body: segmentsBody, note: segmentsNote},
        isCurrent: () => token === segmentsToken,
      });
      return;
    }
    // A single-molecule run has one trajectory rather than a chain of stages, so it has no table of them; the
    // endpoint's own sentence about having nothing to play is the one thing kept for it.
    segmentsTable.hidden = true;
    segmentsWrap.hidden = !why;
    segmentsNote.textContent = why;
  }

  async function loadFigures(job) {
    figures.replaceChildren();
    let entries = [];
    // Declared out here, read in here: `body` is scoped to the `try`, and a line after it that reached for
    // `body.superseded` threw a ReferenceError -- which aborted `loadRun` before it drew anything at all.
    let superseded = 0;
    try {
      const body = await api(`/api/jobs/${encodeURIComponent(job.id)}/figures`);
      entries = body.artifacts || [];
      superseded = Number(body.superseded) || 0;
    } catch (error) {
      figuresNote.textContent = `This run's figures could not be read: ${error.message}`;
      return;
    }
    if (!entries.length) {
      figuresNote.textContent = 'This run published no figure. Every figure the workspace holds belongs to the run '
        + 'that drew it, and this one drew none.';
      return;
    }
    figures.replaceChildren(...entries.map(entry => {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = `/api/jobs/${encodeURIComponent(job.id)}/artifacts/`
        + entry.path.split('/').map(encodeURIComponent).join('/') + '?inline=1';
      link.target = '_blank';
      link.rel = 'noopener';
      const code = document.createElement('code');
      code.textContent = entry.path;
      link.append(code);
      item.append(link);
      return item;
    }));
    // One set per analysis, not one per attempt: the route answers with what the run currently publishes, and says
    // how many of its own earlier sets it left out -- a reader who wants those can open them in the Runs gallery.
    figuresNote.textContent = `${entries.length} figure${entries.length === 1 ? '' : 's'}, straight from the stages `
      + 'that wrote them, opened inline through the run artifact route.'
      + (superseded ? ` ${superseded} superseded set${superseded === 1 ? '' : 's'} of the same analyses stay in this `
                      + "run's own analysis tree." : '')
      + ' The zoomable, pannable gallery stays in the Runs panel.';
  }

  // ------------------------------------------------------------------------------------- structures and the readout

  async function loadSizeClasses(job) {
    // D8 -- the run's own `model.json` states each bead's size class when it is readable, and a caption says which
    // was used, because a bead's radius is a claim. It is read whether or not the artifact index returned it: the
    // index is paged, and a 404 here is simply "this run states no size class".
    try {
      const document_ = JSON.parse(await artifactText(job.id, 'stages/2_mapping/model.json'));
      const classes = {};
      for (const bead of document_.beads || []) {
        const size = String(bead.size || '').trim().toUpperCase();
        if (size) for (const name of [bead.export_name, bead.name]) {
          if (name) classes[String(name).trim().toUpperCase()] = size;
        }
      }
      return Object.keys(classes).length ? classes : null;
    } catch (error) {
      return null;
    }
  }

  async function artifactText(jobId, path) {
    const url = `/api/jobs/${encodeURIComponent(jobId)}/artifacts/`
      + path.split('/').map(encodeURIComponent).join('/') + '?inline=1';
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${path} could not be read (${response.status})`);
    return response.text();
  }

  //: The route that writes a run's own bonds onto one of its structures. A `.gro` carries no bond records -- and
  //: this vendored build's GRO parser guesses them from distances whatever `inferBonds` says, which the caller then
  //: clears -- so a coarse-grained model drawn off the artifact route is beads with no connectivity at all, while
  //: the run's own moleculetype, under `stages/3_initial_CG/`, states exactly which beads are bonded. This route is
  //: where those `[ bonds ]` and `[ constraints ]` become CONECT records, and its answer is read as the PDB it is.
  //: `null` means the route refused; the caller then falls back to the artifact route and the file is drawn the way
  //: it always was.
  async function structureText(job, path) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/structure`
      + `?path=${encodeURIComponent(path)}`);
    return response.ok ? response.text() : null;
  }

  function stageFor() {
    if (!viewer) return null;
    // Created on first use: NGL sizes itself to its host element, and the host is sized for it in run-view.css.
    if (!viewer.runViewStage) viewer.runViewStage = new NGL.Stage(viewer, {backgroundColor: 'white'});
    return viewer.runViewStage;
  }

  async function draw(job, path) {
    what.textContent = `Loading ${path}…`;
    const coarse = isCoarseGrained(path, job.run_type);
    // The legend is the key to a bead picture, so it appears with one: the family colours are what a coarse-grained
    // file's b-factor column carries, and an all-atom file is drawn in its elements' colours instead.
    if (legend) {
      renderBeadLegend(legend);
      legend.hidden = !coarse;
    }
    // A coarse-grained `.gro` carries no bond records, and this build's GRO parser guesses from distances whatever
    // `inferBonds` says -- measured: the eight mapped beads of a `.gro` came back with four guessed bonds, which the
    // guard below then clears. Either way the picture is beads with no connectivity, while the run's own moleculetype
    // states the bonds: the run structure route is where they become CONECT records, and the answer is read as the
    // PDB it is, so the CONECT branch below draws exactly those bonds with the distance guess off. Every other file
    // keeps the artifact route and the rule in `run-view-structure.js`; a refused route falls back to that path.
    let text = null, served = false;
    if (coarse && structureExtension(path) === 'gro') {
      text = await structureText(job, path);
      served = text !== null;
    }
    let parameters;
    if (served) {
      parameters = {ext: 'pdb', inferBonds: 'none',
        reason: conectCount(text)
          ? "the run's own moleculetype, written as CONECT over this file's coordinates "
            + "(its own topology file, for the molecule this file holds) — the model's bonds, and the distance "
            + 'guess is off'
          : 'coarse-grained, and this run states no moleculetype for the molecule this file holds, so the picture '
            + 'claims no bonds rather than guessing them'};
    } else {
      text = await artifactText(job.id, path);
      parameters = loadParameters(text, {path, runType: job.run_type});
    }
    const renderer = stageFor();
    if (!renderer) {
      what.textContent = 'This page could not start a 3D view. The file\'s own numbers, which do not need a '
        + 'renderer, still hold.';
      readout([['atoms in the file', String(countRecords(text))],
               ['bonds from the file', String(conectCount(text))],
               ['how the bonds would be decided', parameters.reason]]);
      return;
    }
    renderer.removeAllComponents();
    const component = await renderer.loadFile(new Blob([text], {type: 'text/plain'}), {...parameters});
    // A file that states no bonds of its own must be drawn without any, and `inferBonds: 'none'` is not enough on
    // its own for every format: this build's `PdbParser` passes the flag through to `calculateBonds`, but its
    // `GroParser` calls `calculateBonds(structure)` with no argument at all -- measured: the eight mapped beads of
    // a `.gro` came back with four guessed bonds whatever the flag said. So the store is emptied here too, and
    // **only** where the file carries no `CONECT` of its own, so a file that does state its bonds keeps every one.
    if (parameters.inferBonds === 'none' && conectCount(text) === 0) dropBonds(component.structure);
    if (coarse) {
      // A bead's radius is a size class the model states, not the stand-in element's: `ngl-beads.js` is the one
      // table and the one call, so this view draws the same beads as Complexes and the bead editor. The display
      // scale is this panel's own and stated at the call -- `BEAD_SCALE`, 0.3 -- and it multiplies the table's
      // radius on the way onto the structure, which is the value the readout below reports back.
      applyBeadRadii(component.structure, {scale: BEAD_SCALE, sizeOf: atom => {
        const named = sizeClasses && sizeClasses[String(atom.atomname || '').trim().toUpperCase()];
        return named || sizeClassOf(atom);
      }});
      // The colour is the bead's own type family, from the code the structure writer puts in the b-factor column
      // of the file this panel serves (`ngl-beads.js` is the one table); a file that carries none draws every
      // bead as family-not-stated rather than as the first family.
      component.addRepresentation('ball+stick', {...BEAD_RADIUS_PARAMETERS, ...BEAD_FAMILY_PARAMETERS});
    } else {
      component.addRepresentation('ball+stick', {radiusScale: 0.55, aspectRatio: 2});
    }
    component.autoView();

    holds.querySelectorAll('tr').forEach((line, index) => {
      line.setAttribute('aria-selected', String(structures[index] && structures[index].path === path));
    });
    const structure = component.structure;
    what.textContent = `${job.id} · ${path} · ${coarse ? 'coarse-grained' : 'all-atom'}.`;
    readout([
      ['atoms drawn', String(structure.atomCount)],
      [served ? "bonds the run's own topology states" : 'bonds the file states', String(conectCount(text))],
      ['bonds the viewer resolved', String(structure.bondCount), 'ok'],
      ['how the bonds were decided', parameters.reason],
      ['bead radii', coarse
        ? (sizeClasses
            ? `the run's own stages/2_mapping/model.json size classes, drawn at ${BEAD_SCALE}x`
            : 'uniform — no readable size class')
        : 'not applicable (all-atom)'],
    ]);
  }

  function countRecords(text) {
    return (String(text).match(/^(ATOM|HETATM)/gm) || []).length;
  }

  function readout(cells) {
    readoutHost.replaceChildren(...cells.map(([label, value, kind]) => {
      const cell = document.createElement('span');
      const cap = document.createElement('span');
      cap.className = 'hint';
      cap.textContent = label;
      const strong = document.createElement('b');
      strong.className = kind || '';
      strong.textContent = value;
      cell.append(cap, strong);
      return cell;
    }));
  }

  // The stage measures itself once, so the canvas has to be told when its host changes size; a panel that is not the
  // open one is measured on its return rather than left at the width it was drawn at.
  window.addEventListener('resize', () => { viewer.runViewStage?.handleResize(); });
  document.addEventListener('dashboard:tab', () => { viewer.runViewStage?.handleResize(); });

  return {
    root, side, legend, chooser: combo,
    run: () => selected,
    loadRun: job => { selected = job; combo.set(job); return loadRun(job); },
    // For a run the workspace's own list does not hold -- a link from the Runs table to a run of another
    // workspace -- the monitor still draws it, and this is what says so where the identity line is.
    identify: text => { identity.textContent = text; },
  };
}
