// The protein-detergent feature's Run view extension: the file conventions and stage chain of a pdc run.
//
// The panel is shared shell; this module is the part a pdc run needs and no other run does. It is registered with
// `/static/js/run-view.js` at load (`Feature.extension_modules` in `feature.py`), and the shell imports it only when
// this distribution is installed.
//
// Two things live here:
//
//   * the structure rules -- which of a pdc run's files are coarse-grained, which directories hold its stages, and
//     the order its structure files are listed in. The engine has no stage names of its own for this run type; the
//     stage table is this feature's (`layout.py`), and so is the directory spelling its scripts write.
//   * the stage-chain table under a monitor: `/api/jobs/<id>/trajectory` says which legs are one system and where
//     the system is rebuilt, and the table prints that answer. The panel fetches the answer; this module renders it.
import { registerRunViewExtension } from '/static/js/run-view.js';

//: The run type this extension serves.
const RUN_TYPE = 'pdc';

//: The numbered stage layout (`01_prepare/` … `10_backmap/`) and the stage names pdc wrote before the numbering.
//: Both spellings are listed because runs written before the numbering are still live.
const STAGE_DIRECTORIES = [
  '01_prepare/', '02_system/', '03_minimisation/', '04_nvt/', '05_npt/', '06_assessment/',
  '07_micelle_assessment/', '08_extension/', '09_final_assessment/', '10_backmap/',
  '0_prepare/', '1_system/', '2_minimisation/', '3_nvt/', '4_npt/',
  '2_assessment/', '3_assessment/', '4_extension/', '5_assessment/', '6_backmap/',
];

//: The system a pdc run publishes is the extension's; the legs before it are the boxes it passed through, which is
//: why they rank after it. The micelle assessment's kept system and the back-map's atomistic product are not a
//: system the run simulated, so they rank last.
const RANKS = [
  [/(?:08_extension|4_extension)\/prod\/run\.gro/, 0],
  [/(?:09_final_assessment|5_assessment)\/prod\/run\.gro/, 1],
  [/(?:06_assessment|2_assessment)\/prod\/run\.gro/, 2],
  [/(?:05_npt|4_npt)\/system\.gro/, 3],
  [/(?:04_nvt|03_minimisation)\/system\.gro/, 4],
  [/(?:02_system|1_system)\/system\.gro/, 4],
];

function structureRank(path) {
  const text = String(path || '');
  for (const [pattern, rank] of RANKS) if (pattern.test(text)) return rank;
  // A path outside this layout has no opinion; anything this run placed after its boxes ranks last, as it did when
  // the whole table lived in the engine.
  return STAGE_DIRECTORIES.some(directory => text.startsWith(directory)) ? 5 : undefined;
}

//: The run's stage chain, drawn into the sub-panel the shell owns. `isCurrent()` is false once the monitor has
//: moved to another run, so an answer that arrived late writes nothing into the run the reader now holds.
async function runSelected({answer, nodes, isCurrent}) {
  if (!isCurrent()) return;
  const rows = (answer && answer.segments) || [];
  const why = (answer && answer.why) || '';
  nodes.table.hidden = false;
  nodes.wrap.hidden = false;
  if (!rows.length) {
    nodes.note.textContent = why;
    return;
  }
  const boundaries = new Map(((answer.boundaries) || []).map(entry => [entry.at, entry]));
  nodes.body.replaceChildren(...rows.map(entry => {
    const line = document.createElement('tr');
    // `== null` rather than a falsy test: a merge group of 0 is a group, and a stage that has none is idle for one
    // of two reasons, which the value names instead of folding them into `true`.
    if (entry.group == null) line.dataset.idle = entry.duplicate_of ? 'duplicate' : 'no-trajectory';
    if (boundaries.has(entry.name)) line.dataset.boundary = 'true';
    const note = boundaries.has(entry.name)
      ? `system rebuilt here: ${entry.atoms} atoms, from ${boundaries.get(entry.name).atoms_from}`
      : (entry.duplicate_of ? `the same trajectory as ${entry.duplicate_of}` : (entry.note || ''));
    const texts = [entry.name,
                   entry.atoms == null ? '—' : String(entry.atoms),
                   entry.trajectory ? entry.trajectory.split('/').pop() : 'none',
                   note];
    texts.forEach((text, index) => {
      const cell = document.createElement(index === 0 ? 'th' : 'td');
      if (index === 0) cell.setAttribute('scope', 'row');
      cell.textContent = text;
      line.append(cell);
    });
    return line;
  }));
  // A `group` is a system, not a trajectory: group 1 on the measured run holds four distinct `.xtc` files, so
  // calling it a trajectory contradicts the table under this sentence.
  const systems = new Set(rows.filter(entry => entry.group != null).map(entry => entry.group)).size;
  nodes.note.textContent = `${rows.length} stage${rows.length === 1 ? '' : 's'} in `
    + `${systems} system${systems === 1 ? '' : 's'}: stages in the same group share one system; `
    + 'a change of group is where the system is rebuilt.';
}

registerRunViewExtension({
  name: RUN_TYPE,
  serves: job => String((job && job.run_type) || '') === RUN_TYPE,
  structure: {
    // A pdc run's structures are beads and its own CONECT records, whichever stage file they came from.
    isCoarseGrained: (path, runType) => String(runType || '') === RUN_TYPE ? true : undefined,
    inStage: path => STAGE_DIRECTORIES.some(directory => String(path || '').startsWith(directory)) ? true : undefined,
    rank: structureRank,
  },
  runSelected,
});
