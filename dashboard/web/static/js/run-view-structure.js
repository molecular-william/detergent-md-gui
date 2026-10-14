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
//      it is right about.
//
// A `.gro` in this vendored build infers no bonds whatever `inferBonds` says -- its GRO parser has no bond
// inference and the files carry none -- which is why branch 2's caption names the run's own topology rather than
// implying a connectivity the coordinates do not have.

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
  if (ext === 'gro') {
    // This vendored build's GRO parser has no bond inference and a `.gro` carries none, so the picture is bondless
    // whatever `inferBonds` says. The caption says so rather than implying a connectivity, and names where the
    // model's own bonds actually are.
    return {ext, inferBonds: 'none',
            reason: 'a .gro carries coordinates and no bond records, and this viewer\'s GRO parser infers none'
                    + (isCoarseGrained(path, runType)
                        ? ", so a coarse-grained model is drawn as loose beads and its own [ bonds ] and "
                          + '[ constraints ] are in the run\'s topology file under stages/3_initial_CG/'
                        : '')};
  }
  if (isCoarseGrained(path, runType)) {
    return {ext, inferBonds: 'none',
            reason: 'coarse-grained — a bead is a radius stand-in, so the distance guess is off by construction'};
  }
  return {ext, inferBonds: 'all',
          reason: "all-atom with no CONECT — the viewer's own distance guess reproduces the chemistry"};
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
  return 4;
}
