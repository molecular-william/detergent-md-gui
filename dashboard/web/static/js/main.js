import { panelIds } from './shared.js';
import { initializeTabs, selectTab } from './tabs.js';
import { createRuns } from './runs.js';
import { createNewRun } from './new-run.js';
import { createMappings } from './mappings.js';
import { createCompositions } from './compositions.js';
import { createPdc } from './pdc.js';
import { createMappingValidation } from './mapping-validation.js';

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
const mappings=createMappings();
document.addEventListener('dashboard:tab', event=>{
  const id=event.detail.id;
  const panels=panelIds();
  const loading=id===panels.runs?runs.mount():id===panels['new-run']?newRun.mount():id===panels.combinations?compositions.mount():id===panels.complexes?pdc.mount():id===panels['mapping-validation']?validation.mount():mappings.mount(id);
  Promise.resolve(loading).catch(error=>{
    const target=document.querySelector(id===panels['new-run']?'#launch-blocker':'#notice');
    target.textContent=error.message;target.hidden=false;
  });
});
initializeTabs();

// Keep the existing acceptance-test and manual refresh entry points stable.
// Mutable form, card and mapping state remains private to its owning module.
Object.assign(window, {
  refreshJobs: runs.refreshJobs,
  refreshConsole: runs.refreshConsole,
  setCloneSource: newRun.setCloneSource,
  selectTab,
  pdcSetRun: pdc.setRun,
});
