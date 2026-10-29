import { panelIds } from './shared.js';
import { initializeTabs, selectTab } from './tabs.js';
import { createRuns } from './runs.js';
import { createNewRun } from './new-run.js';
import { createMappings } from './mappings.js';
import { createCompositions } from './compositions.js';
import { createRunView } from './run-view.js';

//: Mount the engine's panels, then the installed features'. `specs` is `{panel DOM id: {url, factory}}`, emitted by
//: the shell from `dashboard.features.browser_panels()`, so a feature's module is fetched only when its distribution
//: is installed -- a `[det]` deployment never downloads the protein-detergent panel.
export async function boot(specs = {}, extensions = []) {
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
  let validation = null;
  let osmotic = null;
  const runs = createRuns({
    onClone: source => newRun.cloneRun(source),
    onDeleted: id => newRun.clearDeletedClone(id),
    onValidate: id => { if (!validation) return; selectTab('validation'); return validation.open(id); },
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

  const modules = {};
  for (const [panel, promise] of Object.entries(pending)) modules[panel] = await promise;
  const pdc = pdcReady ? await pdcReady : null;
  validation = modules[panels['mapping-validation']] ? modules[panels['mapping-validation']].createMappingValidation() : null;
  osmotic = modules[panels['osmotic-pressure']] ? modules[panels['osmotic-pressure']].createOsmoticSeries() : null;
  if (pdc) window.pdcSetRun = pdc.setRun;

  document.addEventListener('dashboard:tab', event => {
    const id = event.detail.id;
    const current = panelIds();
    const loading = id===current.runs?runs.mount()
      : id===current['run-view']?runView.mount()
      : id===current['new-run']?newRun.mount()
      : id===current.combinations?compositions.mount()
      : id===current.complexes&&pdc?pdc.mount()
      : id===current['mapping-validation']&&validation?validation.mount()
      : id===current['osmotic-pressure']&&osmotic?osmotic.mount()
      : mappings.mount(id);
    Promise.resolve(loading).catch(error=>{
      const target=document.querySelector(id===current['new-run']?'#launch-blocker':'#notice');
      target.textContent=error.message;target.hidden=false;
    });
  });
  initializeTabs();
}
