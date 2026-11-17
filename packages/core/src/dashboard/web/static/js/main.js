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
    '/api/defaults?run_type=cg',
  ];
  for (const path of paths) cachedApi(path, {maxAge: CATALOGUE_MAX_AGE}).catch(() => {});
}

//: Mount the engine's panels, then the installed features'. `specs` is `{panel DOM id: {url, factory}}`, emitted by
//: the shell from `dashboard.features.browser_panels()`, so a feature's module is fetched only when its distribution
//: is installed -- a `[det]` deployment never downloads the protein-detergent panel.
export async function boot(specs = {}, extensions = []) {
  initModules();
  const panels = panelIds();
  //: Feature *panel* modules are imported when their tab first opens, not at boot: a Runs reader does not wait for
  //: a panel it never draws. The map is the one place a feature panel is created, so the promise-backed hooks below
  //: and the tab that opens the panel share one import and one instance.
  const featurePanels = new Map();
  function featurePanel(id) {
    if (!specs[id]) return Promise.resolve(null);
    let entry = featurePanels.get(id);
    if (!entry) {
      entry = {};
      entry.promise = import(specs[id].url).then(module => {
        entry.instance = module[specs[id].factory]();
        // The promise-backed hook becomes the instance's own method once the panel exists -- the same instance,
        // because this cache is the one that created it.
        if (id === panels.complexes) window.pdcSetRun = entry.instance.setRun;
        return entry.instance;
      });
      // A failed import is not cached: the page reports it, and a later open asks again.
      entry.promise.catch(() => featurePanels.delete(id));
      featurePanels.set(id, entry);
    }
    return entry.promise;
  }

  // The extension modules register their hooks on a shared engine panel (New run, Run view) when they load; they are
  // imported here, before the first await below, and awaited before any panel can mount. A feature's *panel* module
  // is not one of these: it is fetched by `featurePanel` when its tab opens.
  const extensionImports = extensions.map(url => import(url));

  // The engine's panels are built from static imports, so everything below this line runs synchronously before the
  // first await. That matters for the window hooks: a module script's top-level `await` does NOT defer the page's
  // `load` event, so a hook published after an await is missing when a browser test (or a person at a console) calls
  // it from `load`. A feature panel is created after its own import resolves; `pdcSetRun` is promise-backed until
  // then and is replaced by the instance's own method once that instance exists, so both callers see one panel.
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
    setCloneSource: newRun.setCloneSource,  // open the clone form on a chosen run
    selectTab,                              // move to a panel by its DOM id
    pdcSetRun: specs[panels.complexes]
      ? ((...args) => featurePanel(panels.complexes).then(panel => panel.setRun(...args)))
      : undefined,
  };
  Object.assign(window, hooks);

  // The one panel the server marked open cannot mount until the extension imports below resolve, so it says so in
  // the meantime. Read back the aria-selected tab rather than decide again, the same way `initializeTabs` does.
  const openTab = document.querySelector('nav.subtabs [role=tab][aria-selected="true"][data-tab]')
    || document.querySelector('nav.subtabs [role=tab][data-tab]');
  const openSection = openTab ? document.getElementById(openTab.dataset.tab) : null;
  setPanelBusy(openSection, 'Loading the dashboard modules…');
  try {
    await Promise.all(extensionImports);
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
      : specs[id]?featurePanel(id).then(panel => panel.mount())
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
