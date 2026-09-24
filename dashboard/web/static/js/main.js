import { initializeTabs, selectTab } from './tabs.js';
import { createRuns } from './runs.js';
import { createNewRun } from './new-run.js';
import { createMappings } from './mappings.js';
import { createCompositions } from './compositions.js';

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
  openBondedModel: model => { selectTab('bonded'); document.dispatchEvent(new CustomEvent('dashboard:composition-selected', {detail: model})); },
  openCompositionRun: model => newRun.openComposition(model.id),
});
const mappings=createMappings();
document.addEventListener('dashboard:tab', event=>{
  const id=event.detail.id;
  const loading=id==='runs'?runs.mount():id==='new'?newRun.mount():id==='compositions'?compositions.mount():mappings.mount(id);
  Promise.resolve(loading).catch(error=>{
    const target=document.querySelector(id==='new'?'#launch-blocker':'#notice');
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
});
