// The CG-only sugar run's Run view extension: one rule the engine must not guess.
//
// A sugar run's structure is beads, even though the file is a `.gro` and the run type is not in the engine's own CG
// table. `isCoarseGrained` is the only override: the shared monitor, trajectory reader and structure endpoint then
// treat the run's own topology as the bond source rather than inferring chemistry from bead distances.

import { registerRunViewExtension } from '/static/js/run-view.js';

const isSugarRun = job => job?.run_type === 'sugar_cg';

registerRunViewExtension({
  name: 'sugar-cg',
  serves: isSugarRun,
  structure: {
    // The rule is asked for every run, not only the ones this extension serves; `undefined` leaves the engine's own
    // answer standing, which is what every non-sugar run must get.
    isCoarseGrained: (path, runType) => (runType === 'sugar_cg' ? true : undefined),
  },
});
