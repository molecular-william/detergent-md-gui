import { panelIds } from './shared.js';
import { initializeTabs, selectTab } from './tabs.js';
import { createRuns } from './runs.js';
import { createNewRun } from './new-run.js';
import { createMappings } from './mappings.js';
import { createCompositions } from './compositions.js';
import { createPdc } from './pdc.js';
import { createMappingValidation } from './mapping-validation.js';
import { createOsmoticSeries } from './osmotic.js';
import { createRunView } from './run-view.js';

const runs = createRuns({
  onClone: source => newRun.cloneRun(source),
  onDeleted: id => newRun.clearDeletedClone(id),
  onValidate: id => { selectTab('validation'); return validation.open(id); },
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
const pdc = createPdc();
const validation = createMappingValidation();
const osmotic = createOsmoticSeries();
const runView = createRunView();
const mappings=createMappings();
document.addEventListener('dashboard:tab', event=>{
  const id=event.detail.id;
  const panels=panelIds();
  const loading=id===panels.runs?runs.mount():id===panels['run-view']?runView.mount():id===panels['new-run']?newRun.mount():id===panels.combinations?compositions.mount():id===panels.complexes?pdc.mount():id===panels['mapping-validation']?validation.mount():id===panels['osmotic-pressure']?osmotic.mount():mappings.mount(id);
  Promise.resolve(loading).catch(error=>{
    const target=document.querySelector(id===panels['new-run']?'#launch-blocker':'#notice');
    target.textContent=error.message;target.hidden=false;
  });
});
initializeTabs();

// Test hooks. These are published for the browser tier and for a person at a console, and nothing in the application
// reads them back -- the panels import what they need. `test_rendered_hosts.py` fails if that stops being true,
// because a module that reads one has quietly made a test hook part of the page, and the hook can then no longer be
// moved without breaking it. Mutable form, card and mapping state stays private to its owning module, which is why
// only these five are here.
Object.assign(window, {
  refreshJobs: runs.refreshJobs,          // re-poll the run list without waiting for the timer
  refreshConsole: runs.refreshConsole,    // refresh the console pane without a visibility change
  setCloneSource: newRun.setCloneSource,  // open the clone form on a chosen run
  selectTab,                              // move to a panel by its DOM id
  pdcSetRun: pdc.setRun,                  // point the complex panel at a run
});
