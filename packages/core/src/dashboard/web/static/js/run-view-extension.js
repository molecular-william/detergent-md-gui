// The Run view panel's extension seam: a feature registers the parts of the panel only its runs need.
//
// The panel itself is shared shell -- two monitors, a run chooser, a structure canvas and the sub-panels under it.
// What a feature's run type adds is its own file conventions and its own reading of the run's stage chain. Both are
// registered here, by the feature's own module, before any panel mounts (`main.js` imports the feature's extension
// modules ahead of the first `await`); the panel asks this registry at the point of use, so an install without a
// feature downloads neither its module nor its behaviour.
//
// An extension is `{name, serves, structure, runSelected}`:
//
//   serves(job) -> bool
//       Whether this extension owns the run. `runSelected` is called only for a run an extension serves.
//   structure: {isCoarseGrained?, inStage?, rank?}
//       Optional overrides for `run-view-structure.js`'s rules. Each is asked before the engine's own answer and
//       returns `undefined` to leave the decision to the engine. `isCoarseGrained(path, runType)`,
//       `inStage(path)` and `rank(path)` have the same contracts as the functions they override.
//   runSelected({job, answer, nodes, isCurrent})
//       Called when a monitor selects `job`, with the `/api/jobs/<id>/trajectory` answer already fetched. The
//       extension writes the stage-chain table into `nodes` (`wrap`, `table`, `body`, `note`); `isCurrent()`
//       answers false once the monitor has moved to another run, so a late answer writes nothing.
const extensions = [];

export function registerRunViewExtension(extension) {
  if (!extension || typeof extension !== 'object' || typeof extension.serves !== 'function') {
    throw new TypeError('registerRunViewExtension needs an object with a serves(job) function');
  }
  if (!extensions.includes(extension)) extensions.push(extension);
}

/** The extension that serves this run, or null. */
export function runViewExtensionFor(job) {
  return extensions.find(extension => extension.serves(job)) || null;
}

/** One `structure` override, in registration order; `undefined` when no extension has an opinion. */
export function runViewStructureRule(name, ...args) {
  for (const extension of extensions) {
    const rule = extension.structure && extension.structure[name];
    if (typeof rule !== 'function') continue;
    const answer = rule(...args);
    if (answer !== undefined && answer !== null) return answer;
  }
  return undefined;
}
