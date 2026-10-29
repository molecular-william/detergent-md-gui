// How a run's own structure file is handed to the viewer: which loader, and whether the distance guess runs.
//
// One rule, in one place, for the reason the panel exists: NGL's `inferBonds` defaults to `'all'`, so any file
// without the model's own records is *guessed* at. On real chemistry the guess reproduces the molecule; on a
// coarse-grained bead, which is a radius stand-in rather than an atom, it is wrong by construction -- measured on
// this repository's own DDM placement, a frame the model bonds 60 ways was drawn 90 ways, head beads onto tail
// beads. And a file that *does* carry `CONECT` is drawn from those records **and** guessed at as well, which is
// the same defect with a different cause.
//
// So there are three branches and no fourth:
//
//   1. a file that carries `CONECT` -> `inferBonds: 'none'`, and the bonds drawn are the model's;
//   2. a coarse-grained structure (a CG run type, or a `2_mapping`/`4_CG_sim`/`3_initial_CG` path) ->
//      `inferBonds: 'none'` too, even when the distances look plausible;
//   3. an all-atom file with no `CONECT` -> the viewer's own inference is left on, because that is the one case
//      it is right about. A `.gro` belongs to this branch whenever the run is all-atom: the format carries no bond
//      records and this build's parser guesses from distances whatever the flag says, so the guess that is wrong
//      for a bead is the guess that is right for chemistry -- and drawing it bondless, as an earlier version of
//      this rule did for every `.gro`, left the atomistic half of a comparison with no bonds at all.
//
// A `.gro` carries no bond records, and this vendored build's GRO parser guesses bonds from distances whatever
// `inferBonds` says -- measured: the eight mapped beads of a `.gro` came back with four bonds under either flag. So
// the caller clears the store on branch 2, and the caption names the run's own topology rather than implying a
// connectivity the coordinates hold.

//: The run types whose structures are coarse-grained. A `pdc` run's files are beads and its own CONECT records;
//: it is listed here so the rule agrees with itself even where the path does not say so.
export const CG_RUN_TYPES = ('aa_cg cg_composition pdc').split(' ');

//: The stage directories whose contents are beads rather than atoms.
const CG_PATH_HINTS = ('2_mapping 4_CG_sim 3_initial_CG').split(' ');

export function structureExtension(path) {
  const match = /\.(gro|pdb)$/i.exec(String(path || ''));
  return match ? match[1].toLowerCase() : null;
}

export function isStructurePath(path) {
  return structureExtension(path) !== null;
}

export function isCoarseGrainedPath(path) {
  const text = String(path || '');
  return CG_PATH_HINTS.some(hint => text.includes(hint));
}

export function isCoarseGrained(path, runType) {
  return CG_RUN_TYPES.includes(String(runType || '')) || isCoarseGrainedPath(path);
}

//: The number of `CONECT` records in the file text. `^CONECT` in multiline mode is the test `pdc.js` uses, and the
//: count is what the panel's readout compares with the bonds the renderer actually resolved.
export function conectCount(text) {
  return (String(text || '').match(/^CONECT/gm) || []).length;
}

export function loadParameters(text, {path, runType} = {}) {
  const ext = structureExtension(path);
  if (ext === null) {
    throw new Error(`${path || 'that file'} is not a .gro or .pdb this viewer can open`);
  }
  if (/^CONECT/m.test(String(text || ''))) {
    return {ext, inferBonds: 'none',
            reason: 'the file carries CONECT — drawn from its own records, the distance guess is off'};
  }
  if (ext === 'gro' && isCoarseGrained(path, runType)) {
    // This vendored build's GRO parser guesses from distances whatever the flag, and a `.gro` carries no bond
    // records of its own, so the picture is bondless once the caller clears the store: the caption says so rather
    // than implying a connectivity, and says where the model's own bonds are without naming a directory -- a
    // single-molecule CG build keeps its moleculetype in `3_initial_CG/` and a protein-detergent run keeps its
    // detergent's in `1_system/`, and this module has no run directory to look in.
    return {ext, inferBonds: 'none',
            reason: 'a .gro carries coordinates and no bond records, so this viewer draws no bond of its own'
                    + ", so a coarse-grained model is drawn as loose beads and its own [ bonds ] and "
                    + '[ constraints ] are in the run\'s topology file for the molecule it holds'};
  }
  if (isCoarseGrained(path, runType)) {
    return {ext, inferBonds: 'none',
            reason: 'coarse-grained — a bead is a radius stand-in, so the distance guess is off by construction'};
  }
  return {ext, inferBonds: 'all',
          reason: ext === 'gro'
            ? 'all-atom, and a .gro carries no bond records of its own — the bonds drawn are this viewer\'s '
              + 'distance guess over the coordinates'
            : "all-atom with no CONECT — the viewer's own distance guess reproduces the chemistry"};
}

//: Empty a structure's bond store. `inferBonds: 'none'` is not enough on its own for every format: this build's
//: `PdbParser` passes the flag through to `calculateBonds`, but its `GroParser` calls `calculateBonds(structure)`
//: with no argument at all -- measured, the eight mapped beads of a `.gro` came back with four guessed bonds
//: whatever the flag said. So the caller empties the store as well, and **only** where the file carries no
//: `CONECT` of its own, so a file that states its bonds keeps every one.
export function dropBonds(structure) {
  if (structure && structure.bondStore) structure.bondStore.count = 0;
}

//: The order the panel lists a run's structure files in, lowest first: the file a run exists to publish before the
//: boxes it passed through. Guards that matter are the run's own solute (`07_reference/lig.gro` for an AA run, the
//: mapped model for a CG one) and, for anything else, the deeper stage first, so the reader reads the run
//: backwards from what it produced.
export function structureRank(path) {
  const text = String(path || '');
  if (text.includes('07_reference/lig.gro')) return 0;
  if (text.includes('2_mapping/mapped.')) return 1;
  if (text.includes('3_initial_CG/')) return 2;
  if (text.includes('4_CG_sim/')) return 3;
  // A protein-detergent run keeps its stages under names of their own, and the system it publishes is the
  // extension's: the legs before it are the boxes the run passed through, which is why they rank after it. A run
  // written in the numbered layout spells the same stages `08_extension`, `09_final_assessment`, `06_assessment`,
  // `05_npt` and `02_system`; both spellings are listed because two legacy runs are still live.
  if (text.includes('08_extension/prod/run.gro') || text.includes('4_extension/prod/run.gro')) return 0;
  if (text.includes('09_final_assessment/prod/run.gro') || text.includes('5_assessment/prod/run.gro')) return 1;
  if (text.includes('06_assessment/prod/run.gro') || text.includes('2_assessment/prod/run.gro')) return 2;
  if (text.includes('05_npt/system.gro') || text.includes('4_npt/system.gro')) return 3;
  if (text.includes('04_nvt/system.gro') || text.includes('03_minimisation/system.gro')) return 4;
  if (text.includes('02_system/system.gro') || text.includes('1_system/system.gro')) return 4;
  // The micelle assessment's kept system and the back-map's atomistic product are not a system the run simulated;
  // they rank after the boxes it passed through.
  return 5;
}

//: The directories a run's own stages live in: `stages/` for a run written in the current layout, the numbered pdc
//: stage names (`01_prepare/` …) or -- for a protein-detergent run written before the numbering -- the stage names
//: its own scripts use. Measured on `00b9ae6db23f`: that run's directory holds `1_system/`, `4_extension/` and no
//: `stages/` at all, so `/api/jobs/<id>/artifacts` answers `1_system/system.gro` and the entries after `stages/` are
//: what make its structures reachable.
// An array, not a parenthesised list: `('a/', 'b/')` is a comma expression that evaluates to the last string, so
// `.some()` on it throws and every caller of `inStage` dies where it is called.
export const STAGE_DIRECTORIES = ['stages/',
                                  // The numbered pdc layout: one directory per stage, in execution order.
                                  '01_prepare/', '02_system/', '03_minimisation/', '04_nvt/', '05_npt/', '06_assessment/',
                                  '07_micelle_assessment/', '08_extension/', '09_final_assessment/', '10_backmap/',
                                  // The legacy pdc spelling, kept for the runs written before the numbering.
                                  '0_prepare/', '1_system/', '2_minimisation/', '3_nvt/', '4_npt/',
                                  '2_assessment/', '3_assessment/', '4_extension/', '5_assessment/', '6_backmap/'];

export function inStage(path) {
  const text = String(path || '');
  return STAGE_DIRECTORIES.some(directory => text.startsWith(directory));
}
