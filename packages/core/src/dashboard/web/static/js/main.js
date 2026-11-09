import { panelIds, cachedApi, storage, CATALOGUE_MAX_AGE } from './shared.js';
import { initializeTabs, selectTab } from './tabs.js';
import { createRuns } from './runs.js';
import { createNewRun } from './new-run.js';
import { createMappings } from './mappings.js';
import { createCompositions } from './compositions.js';
import { createRunView } from './run-view.js';
import { initModules } from './modules.js';
import { setPanelBusy } from './panel-busy.js';

//: The lists New run, Mappings and Bonded read, warmed once the shell is idle. They are catalogues -- changed only by
//: an action that invalidates them -- so a later panel mount is a cache hit instead of a round trip. `/api/jobs`, the
//: queue, running progress and generated figures are deliberately absent: those are live and are never prefetched.
//: The saved form's molecule is the key the New run and Bonded reference lists would ask for.
function prefetchCatalogues() {
  let form = {};
  try { form = storage.get('form', {}) || {}; } catch (error) { form = {}; }
  const molecule = form.molecule_id || form.detergent || 'DDM';
  const paths = [
    '/api/molecules',
    '/api/mappings?view=summary',
    '/api/mappings/context',
    '/api/cg-models?view=summary',
    '/api/mappings?view=summary&molecule_id=' + encodeURIComponent(molecule),
    '/api/references?molecule_id=' + encodeURIComponent(molecule),
    '/api/defaults?run_type=aa_cg',
  ];
  for (const path of paths) cachedApi(path, {maxAge: CATALOGUE_MAX_AGE}).catch(() => {});
}

//: Mount the engine's panels, then the installed features'. `specs` is `{panel DOM id: {url, factory}}`, emitted by
//: the shell from `dashboard.features.browser_panels()`, so a feature's module is fetched only when its distribution
//: is installed -- a `[det]` deployment never downloads the protein-detergent panel.
export async function boot(specs = {}, extensions = []) {
  initModules();
  const panels = panelIds();
  const pending = {};
  for (const [panel, spec] of Object.entries(specs)) pending[panel] = import(spec.url);
  // A feature's extension modules register their hooks on a shared engine panel (New run, Run view) when they load;
  // importing them here, before the first await below, means they are registered before any panel can mount.
  for (const url of extensions) pending[url] = import(url);

  // The engine's panels are built from static imports, so everything below this line runs synchronously before the
  // first await. That matters for the console hooks: a module script's top-level `await` does NOT defer the page's
  // `load` event, so a hook published after an await is missing when a browser test (or a person at a console) calls
  // it from `load`. The feature panels are created after the imports resolve; `pdcSetRun` is promise-backed until then
  // and is replaced by the instance's own method once that instance exists, so both callers see one panel.
  const pdcReady = pending[panels.complexes]
    ? pending[panels.complexes].then(module => module.createPdc())
    : null;
  let osmotic = null;
  //: The pdc panel's instance, created after the feature imports resolve; the tab listener below reads it, so it
  //: lives at boot's scope rather than inside the try that awaits it.
  let pdc = null;
  const runs = createRuns({
    onClone: source => newRun.cloneRun(source),
    onDeleted: id => newRun.clearDeletedClone(id),
  });
  const newRun = createNewRun({
    selectTab,
    refreshJobs: runs.refreshJobs,
    refreshStorage: runs.refreshStorage,
  });
  const compositions = createCompositions({
    selectTab,
    openBondedModel: model => { selectTab('bonded'); return mappings.openBondedModel(model); },
    openCompositionRun: model => newRun.openComposition(model.id),
  });
  const runView = createRunView();
  const mappings = createMappings();
  const hooks = {
    refreshJobs: runs.refreshJobs,          // re-poll the run list without waiting for the timer
    refreshConsole: runs.refreshConsole,    // refresh the console pane without a visibility change
    setCloneSource: newRun.setCloneSource,  // open the clone form on a chosen run
    selectTab,                              // move to a panel by its DOM id
    pdcSetRun: pdcReady ? ((...args) => pdcReady.then(panel => panel.setRun(...args))) : undefined,
  };
  Object.assign(window, hooks);

  // The one panel the server marked open cannot mount until the feature imports below resolve, so it says so in the
  // meantime. Read back the aria-selected tab rather than decide again, the same way `initializeTabs` does.
  const openTab = document.querySelector('nav.subtabs [role=tab][aria-selected="true"][data-tab]')
    || document.querySelector('nav.subtabs [role=tab][data-tab]');
  const openSection = openTab ? document.getElementById(openTab.dataset.tab) : null;
  setPanelBusy(openSection, 'Loading the dashboard modules…');
  try {
    const modules = {};
    for (const [panel, promise] of Object.entries(pending)) modules[panel] = await promise;
    pdc = pdcReady ? await pdcReady : null;
    osmotic = modules[panels['osmotic-pressure']] ? modules[panels['osmotic-pressure']].createOsmoticSeries() : null;
    if (pdc) window.pdcSetRun = pdc.setRun;
  } finally {
    setPanelBusy(openSection, '');
  }

  document.addEventListener('dashboard:tab', event => {
    const id = event.detail.id;
    const section = document.getElementById(id);
    const current = panelIds();
    setPanelBusy(section, 'Loading this panel…');
    const loading = id===current.runs?runs.mount()
      : id===current['run-view']?runView.mount()
      : id===current['new-run']?newRun.mount()
      : id===current.combinations?compositions.mount()
      : id===current.complexes&&pdc?pdc.mount()
      : id===current['osmotic-pressure']&&osmotic?osmotic.mount()
      : mappings.mount(id);
    Promise.resolve(loading).catch(error=>{
      const target=document.querySelector(id===current['new-run']?'#launch-blocker':'#notice');
      target.textContent=error.message;target.hidden=false;
    }).finally(()=>setPanelBusy(section, ''));
  });
  initializeTabs();
  // After the open panel has mounted: never on the critical path. A short settle first, then an idle slot, so the
  // catalogue requests never contend with the first panel's own paint. `requestIdleCallback` is not universal, so the
  // timeout fallback runs the same warm-up once.
  const idle = window.requestIdleCallback
    ? callback => window.requestIdleCallback(callback, {timeout: 2000})
    : callback => setTimeout(callback, 200);
  setTimeout(() => idle(prefetchCatalogues), 1500);
}
