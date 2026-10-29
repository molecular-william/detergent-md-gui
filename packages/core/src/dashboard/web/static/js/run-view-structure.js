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

import { runViewStructureRule } from './run-view-extension.js';

//: The engine's own run types whose structures are coarse-grained. A feature's run type is added by its extension's
//: `structure.isCoarseGrained` rule rather than listed here, so this table is the engine's vocabulary alone.
export const CG_RUN_TYPES = ('aa_cg cg_composition').split(' ');

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
  // A feature's run type or file convention is asked first; `undefined` leaves the engine's own answer standing.
  const registered = runViewStructureRule('isCoarseGrained', path, runType);
  if (registered !== undefined) return registered;
  return CG_RUN_TYPES.includes(String(runType || '')) || isCoarseGrainedPath(path);
}

//: The number of `CONECT` records in the file text. `^CONECT` in multiline mode is the test the bead viewer uses, and
//: the count is what the panel's readout compares with the bonds the renderer actually resolved.
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
    // single-molecule CG build keeps its moleculetype under its own stage, a feature's run layout keeps it under
    // one of its own, and this module has no run directory to look in.
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
  // A feature's own stage names rank through its extension; the engine's own layout is the fallback.
  const registered = runViewStructureRule('rank', path);
  if (registered !== undefined) return registered;
  if (text.includes('07_reference/lig.gro')) return 0;
  if (text.includes('2_mapping/mapped.')) return 1;
  if (text.includes('3_initial_CG/')) return 2;
  if (text.includes('4_CG_sim/')) return 3;
  return 5;
}

//: The directories the engine's own runs keep their stages in: `stages/` for a run written in the current layout.
//: A feature's run layout adds its own names through its extension's `structure.inStage` rule.
export const STAGE_DIRECTORIES = ['stages/'];

export function inStage(path) {
  const text = String(path || '');
  if (STAGE_DIRECTORIES.some(directory => text.startsWith(directory))) return true;
  return runViewStructureRule('inStage', path) === true;
}
