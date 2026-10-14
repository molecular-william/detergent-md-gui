// Coarse-grained beads, drawn at the radius the model's own size class gives them.
//
// A bead has no element and no van der Waals radius, so NGL cannot size one from chemistry: that is why every bead
// in these files is written with a neutral stand-in element, and why a viewer handed only that stand-in draws a
// ranking of sizes rather than the model's. The model does state a size class per bead -- R, S or T, Martini 3's
// molecular-volume classes -- and `dashboard/models/sugars/recognition.py`'s `RADII_NM` is this repository's one
// table of the nanometres each class means. This module is that table and the one call that puts it on a loaded
// structure, so the Complexes panel and the two other views that draw beads (the mapping's 3D overlay and the
// composition preview) cannot disagree about how big a bead is.
//
// Truth and scale are separate knobs on purpose. `BEAD_RADIUS_SCALE` multiplies the model's radius for reading --
// the system preview draws its beads twice the run view's -- and it never changes the radii the table states, so a
// caller can move one without lying about the other.

//: `recognition.RADII_NM`, in nanometres, by Martini 3 size class. The fast tier compares this table with the
//: Python one, because a second copy of these numbers would be a second model.
export const BEAD_RADII_NM = {R: 0.264, S: 0.230, T: 0.191};

//: The stand-in element each class' beads are written with (`models/compositions/topology.py`), read back here so a
//: file that states only elements can still say which class its beads are.
export const SIZE_ELEMENTS = {C: 'R', N: 'S', H: 'T'};

//: The one scale knob. `1` draws the model's own radius; `2` draws it twice as large, which is what the new-run
//: panel's preview wants. Set it through `setBeadRadiusScale`, or per call through `applyBeadRadii`'s `scale`.
export let BEAD_RADIUS_SCALE = 1;

export function setBeadRadiusScale(value) {
  const scale = Number(value);
  BEAD_RADIUS_SCALE = Number.isFinite(scale) && scale > 0 ? scale : 1;
}

//: `ball+stick` draws the ball at `atomRadius x radiusScale x aspectRatio` and the stick at
//: `atomRadius x radiusScale` (measured in the vendored build), so folding the aspect ratio into the radius scale
//: is what makes the drawn ball's radius the model's radius. The aspect ratio stays the app's 2 for the sticks,
//: and a structure's radii stay the model's -- the correction is in the representation, not in the data.
export const BEAD_ASPECT_RATIO = 2;
export const BEAD_RADIUS_PARAMETERS = {radiusType: 'explicit', radiusScale: 1 / BEAD_ASPECT_RATIO,
                                       aspectRatio: BEAD_ASPECT_RATIO};

const ANGSTROM_PER_NANOMETRE = 10;

export function beadRadiusNm(size, scale = BEAD_RADIUS_SCALE) {
  const radius = BEAD_RADII_NM[String(size || '').trim().toUpperCase()];
  return radius === undefined ? null : radius * scale;
}

export function sizeClassOf(atom) {
  // A file may carry the class either way: the mapping overlay writes it as the residue (`bead_pdb_text`), and a
  // composition PDB writes it as the stand-in element. The residue is asked first because these files also write
  // real elements for real atoms -- the mapping overlay's molecule PDB is C/O/N/H -- and a molecule's own carbon is
  // not a bead class. A file that states neither yields `null` rather than a guessed class.
  const residue = String(atom.resname || '').trim().toUpperCase();
  if (BEAD_RADII_NM[residue]) return residue;
  return SIZE_ELEMENTS[String(atom.element || '').trim().toUpperCase()] || null;
}

export function applyBeadRadii(structure, {sizeOf = sizeClassOf, scale = BEAD_RADIUS_SCALE} = {}) {
  // The radii go on the structure, which is what a representation resolves per atom: with `radiusType: 'explicit'`
  // it reads `atom.radius`, so this one call sizes every representation drawn from the structure. A bead whose file
  // states no class keeps the radius NGL gave it rather than being handed one the file did not state. The count
  // comes back so a caller can say how many beads it sized.
  if (!structure) return 0;
  if (!structure.atomStore.radius) structure.atomStore.addField('radius', 1, 'float32');
  let applied = 0;
  structure.eachAtom(atom => {
    const radius = beadRadiusNm(sizeOf(atom), scale);
    if (radius === null) return;
    structure.atomStore.radius[atom.index] = radius * ANGSTROM_PER_NANOMETRE;
    applied += 1;
  });
  return applied;
}
