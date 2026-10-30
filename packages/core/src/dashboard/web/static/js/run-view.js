// The Run view panel: two monitors side by side, each holding a run of its own, in either workspace.
//
// Scoped, never duplicated. The workspace the panel was mounted in decides which run types it offers -- the scope
// arrives in the page (`#run-view-scope`, written from `web/sections.py`'s per-workspace `run_types`) -- and this
// host asks `/api/jobs` for each of those types *by name* rather than paging every run on disk. Every run type is
// drawn here: the monitor draws its structure and lists the chain's own segments under it, because
// `/api/jobs/<id>/trajectory` answers from the run's stage files.
//
// Two runs at once is the point: a coarse-grained run and the atomistic reference it consumed read side by side, so
// a reader can see what a mapping was measured against. `run-view-monitor.js` holds one monitor's work -- its
// structure, its segments, its figures -- and every element id in it is suffixed by side, so two of them in one page
// cannot reach into each other.
//
// What the host owns: the run list (completed runs only), the two combos, and the remembered pair. Nothing here draws
// anything.
//
// A monitor's readout reports what the *renderer* resolved -- atom count and bond count read back off the loaded
// structure -- never what the panel intended to send. A guard asserted only on the request is a guard that cannot
// fail, and both failure modes it exists for (a selection matching nothing, an inference quietly adding bonds)
// render as a plausible picture with a clean console.

import { $, api, panelIds } from './shared.js';
import { createMonitor } from './run-view-monitor.js';

// The seam a feature's module imports to register its run type's file conventions and stage chain. Re-exported here
// so the panel a feature extends is the module it names (`/static/js/run-view.js`).
export { registerRunViewExtension } from './run-view-extension.js';

//: The route pages the artifact index and caps `limit` at 100, so every request here states its own limit.
const PAGE_LIMIT = 100;
//: Where the pair and the collapse states are remembered, so a comparison a reader returns to reopens as they left
//: it. One key for the panel rather than one per workspace: a run does not move between workspaces.
const STATE_KEY = 'run-view.state';
//: The sides, in the order they are drawn. Two, and only two: a third column was considered and turned down.
const SIDES = ['A', 'B'];

export function createRunView() {
  const section = () => $('#' + panelIds()['run-view']);
  const grid = $('#run-view-monitors');
  const note = $('#run-view-note');
  const swapButton = $('#run-view-swap');

  let scope = {slug: '', types: []};
  let runs = [];              // completed runs in this workspace, newest first; mutated in place, never replaced
  let monitors = [];
  let loaded = false;

  function remember() {
    try {
      const state = JSON.parse(localStorage.getItem(STATE_KEY) || '{}') || {};
      state.pair = monitors.map(monitor => (monitor.run() || {}).id || '');
      state.collapsed = {};
      // Keyed by the element's own id rather than by its position: a block inserted above the sub-panels -- the
      // trajectory block's argument form is one -- would otherwise move every remembered state onto its neighbour,
      // and a reader's layout would open the wrong panel. An id nothing remembers is a panel at its default, closed.
      monitors.forEach(monitor => [...monitor.root.querySelectorAll('details[id]')].forEach(details => {
        state.collapsed[details.id] = !details.open;
      }));
      localStorage.setItem(STATE_KEY, JSON.stringify(state));
    } catch (error) {
      /* a browser that refuses storage is a browser whose state is not remembered, not a panel that fails */
    }
  }

  function recalled() {
    try {
      return JSON.parse(localStorage.getItem(STATE_KEY) || '{}') || {};
    } catch (error) {
      return {};
    }
  }

  function readScope() {
    const block = $('#run-view-scope');
    try {
      const parsed = JSON.parse(block ? block.textContent : '{}');
      scope = {slug: parsed.slug || '', types: Array.isArray(parsed.types) ? parsed.types : []};
    } catch (error) {
      scope = {slug: '', types: []};
    }
  }

  async function loadRuns() {
    // Completed runs only, and one request per run type in scope -- the route's own `run_type` filter, so this page
    // holds its workspace's runs and `total` describes them rather than a hidden superset of every run on disk.
    runs.length = 0;
    if (!scope.types.length) {
      note.textContent = 'No run type is registered for this workspace, so there is nothing here to choose.';
      return;
    }
    const answers = await Promise.all(scope.types.map(async type => {
      const query = new URLSearchParams({view: 'summary', limit: String(PAGE_LIMIT), run_type: type,
                                        status: 'completed'});
      try {
        return {jobs: (await api(`/api/jobs?${query}`)).jobs || []};
      } catch (error) {
        return {jobs: [], error: error.message};
      }
    }));
    runs.push(...answers.flatMap(answer => answer.jobs)
      .sort((first, second) => String(second.created || '').localeCompare(String(first.created || ''))
                              || String(second.id || '').localeCompare(String(first.id || ''))));
    const failed = answers.filter(answer => answer.error).map(answer => answer.error);
    note.textContent = failed.length
      ? `${runs.length} completed run${runs.length === 1 ? '' : 's'} available; some could not be read: ${failed[0]}`
      : `${runs.length} completed run${runs.length === 1 ? '' : 's'} available.`;
    for (const monitor of monitors) monitor.chooser.set(monitor.run());
  }

  function build() {
    // Built once: two monitors, each with its own combo, canvas, segments table and three collapsed panels. The
    // remembered collapse state is applied before the first run is chosen, so a reader's own layout does not flash.
    grid.replaceChildren();
    const state = recalled();
    monitors = SIDES.map(side => {
      const root = document.createElement('div');
      root.className = 'monitor-host';
      grid.append(root);
      const monitor = createMonitor({
        root, side, runs,
        onPick: job => { open(monitor, job).catch(() => {}); },
      });
      [...monitor.root.querySelectorAll('details[id]')].forEach(details => {
        details.open = (state.collapsed || {})[details.id] === false;
        details.addEventListener('toggle', remember);
      });
      return monitor;
    });
  }

  // ----------------------------------------------------------------------------------------------- the pair

  async function open(monitor, job) {
    // Every run type is drawn here. What once made this panel unable to draw one was that the run's CG trajectory
    // matched no role in `analysis/runs/layout.py`; a feature registers its layout, so a run's production trajectory
    // resolves, and the segments (which legs merge, and where the system is rebuilt) come from
    // `/api/jobs/<id>/trajectory`.
    await monitor.loadRun(job);
    remember();
  }

  function referenceOf(job) {
    // The atomistic run a coarse-grained run was measured against, named by the run itself: `reference_run_id` is
    // the only source, and a run that names none is paired with nothing rather than with a guess.
    const wanted = job && (job.reference_run_id || job.reference);
    return runs.find(candidate => candidate.id === String(wanted || '')) || null;
  }

  async function swap() {
    const [first, second] = monitors;
    const left = first.run(), right = second.run();
    if (right) await open(first, right);
    if (left) await open(second, left);
  }

  async function pickInitial() {
    const wanted = new URLSearchParams(location.search).get('run') || '';
    const state = recalled();
    const remembered = (state.pair || []).filter(id => runs.some(job => job.id === id));
    const known = runs.find(job => job.id === wanted);
    const first = known || runs.find(job => job.id === remembered[0])
      || runs.find(job => String(job.run_type) === 'aa_cg') || runs[0];
    if (!first && !wanted) {
      note.textContent = 'No completed run in this workspace yet.';
      return;
    }
    if (known || !wanted) {
      await open(monitors[0], first);
    } else {
      // A link can name a run this workspace's list does not hold. It is drawn anyway -- the artifact routes answer
      // by id -- and the identity line says what it is, rather than pretending it belongs here.
      await monitors[0].loadRun({id: wanted});
      monitors[0].identify(`${wanted} · this run is not in this workspace's scope.`);
    }
    const second = runs.find(job => job.id === remembered[1] && job.id !== first.id)
      || referenceOf(first) || runs.find(job => job.id !== first.id);
    if (second) await open(monitors[1], second);
  }

  return {
    mount: async () => {
      if (!loaded) {
        loaded = true;
        readScope();
        build();
        await loadRuns();
      }
      await pickInitial();
      if (swapButton) swapButton.addEventListener('click', () => { swap().catch(() => {}); });
      return section();
    },
  };
}
