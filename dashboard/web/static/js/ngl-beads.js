// Coarse-grained beads, drawn at the radius the model's own size class gives them.
//
// A bead has no element and no van der Waals radius, so NGL cannot size one from chemistry: that is why every bead
// in these files is written with a neutral stand-in element, and why a viewer handed only that stand-in draws a
// ranking of sizes rather than the model's. The model does state a size class per bead -- R, S or T, Martini 3's
// molecular-volume classes -- and `dashboard/models/sugars/recognition.py`'s `RADII_NM` is this repository's one
// table of the nanometres each class means. This module is that table and the one call that puts it on a loaded
// structure, so the four views that draw beads (the Complexes panel, the run view, the mapping's 3D overlay and the
// composition preview) and the New Run panel's system preview cannot disagree about how big a bead is.
//
// Truth and scale are separate knobs on purpose. `BEAD_RADIUS_SCALE` multiplies the model's radius for reading --
// the composition preview reads its beads larger than life, the run view and the system preview read the model's own
// -- and it never changes the radii the table states, so a caller can move one without lying about the other.

//: `recognition.RADII_NM`, in nanometres, by Martini 3 size class. The fast tier compares this table with the
//: Python one, because a second copy of these numbers would be a second model.
export const BEAD_RADII_NM = {R: 0.264, S: 0.230, T: 0.191};

// What size cannot say: a bead's Martini 3 *polarity family*, in the code order `pdc_view.bead_family_code` writes
// into the file. The size class is one axis and the family is the other -- two beads of the same class can be a
// sugar's polar head and a charged group -- so the family is what colour carries, and this is the one table of it.
//
// The family is read from the bead's *type* (the moleculetype's `[ atoms ]` type column, and a mapping's `type`
// field): Martini 3 spells a small bead `SP1r` and a tiny one `TC4`, and the family letter is the first of
// `Q`/`P`/`N`/`C` after that one-letter class prefix. A type that names none of them -- a protein bead, a bead no
// moleculetype names -- states no family and is drawn the neutral `unstated` colour rather than being guessed into
// one of the four.
//
// `unstated` is code 0 on purpose: a file that carries no family column (a `.gro` this build's parser fills with
// b-factors of zero, a file written before this convention) then draws every bead as unstated rather than as
// whichever family happens to be code zero. The palette is five control colours over the domain `[0, 4]`, so each
// code lands on its own colour instead of on an interpolation between two: measured on this vendored build, a
// five-colour scale over that domain resolves 0..4 to exactly these five hexes.
export const BEAD_FAMILY_ORDER = ['unstated', 'C', 'N', 'P', 'Q'];
export const BEAD_FAMILY_COLOURS = {unstated: '#cccccc', C: '#7048e8', N: '#e8590c', P: '#2f9e44', Q: '#2b6cb0'};
export const BEAD_FAMILY_LABELS = {unstated: 'family not stated', C: 'apolar', N: 'nonpolar', P: 'polar',
                                   Q: 'charged'};
//: The five control colours, in the order of the codes -- the scale a representation is handed.
export const BEAD_FAMILY_PALETTE = BEAD_FAMILY_ORDER.map(family => BEAD_FAMILY_COLOURS[family]);

//: The colour parameters every bead view adds to `BEAD_RADIUS_PARAMETERS`: the representation colours each atom
//: from the family code the file carries in its b-factor column, over a domain fixed at `[0, 4]` so a bead's colour
//: is the family's and never the frame's own spread of codes.
export const BEAD_FAMILY_PARAMETERS = {colorScheme: 'bfactor', colorScale: BEAD_FAMILY_PALETTE, colorDomain: [0, 4]};

export function beadFamily(type) {
  // Leading `S`/`T` is the size class, not the family: `SP1r` is small *and* polar, `TC4` tiny *and* apolar.
  const code = String(type || '').trim().toUpperCase();
  const rest = /^[ST]/.test(code) ? code.slice(1) : code;
  const family = rest.slice(0, 1);
  return family in BEAD_FAMILY_COLOURS && family !== 'unstated' ? family : 'unstated';
}

export function beadFamilyCode(type) {
  return BEAD_FAMILY_ORDER.indexOf(beadFamily(type));
}

export function renderBeadLegend(host) {
  // The legend and the colouring are one table: the swatch a reader decodes a bead with is the colour the
  // representation above it resolved, because both come from `BEAD_FAMILY_COLOURS` and neither is written out by
  // hand. `host` is wherever a view draws its beads; the panels call this at mount, and the element it fills is the
  // one the tests read back.
  if (!host) return null;
  const list = document.createElement('ul');
  list.className = 'bead-legend-list';
  for (const family of BEAD_FAMILY_ORDER) {
    const item = document.createElement('li');
    item.className = 'bead-legend-item';
    item.dataset.family = family;
    const swatch = document.createElement('span');
    swatch.className = 'bead-legend-swatch';
    swatch.dataset.colour = BEAD_FAMILY_COLOURS[family];
    swatch.style.backgroundColor = BEAD_FAMILY_COLOURS[family];
    const label = document.createElement('span');
    label.className = 'bead-legend-label';
    label.textContent = family === 'unstated'
      ? BEAD_FAMILY_LABELS[family]
      : `${BEAD_FAMILY_LABELS[family]} (${family})`;
    item.append(swatch, label);
    list.append(item);
  }
  host.replaceChildren(list);
  return list;
}

//: The stand-in element each class' beads are written with (`models/compositions/topology.py`'s `render_pdb` and
//: `execution/adapters/pdc_view.py`'s `system_pdb` both choose it), read back here so a file that states only
//: elements can still say which class its beads are.
export const SIZE_ELEMENTS = {C: 'R', N: 'S', H: 'T'};

//: The one scale knob. `1` draws the model's own radius, which is what the run view and the system preview want;
//: `3.75` is what the composition preview reads its beads at, and it never changes what the table above states. Set
//: it through `setBeadRadiusScale`, or per call through `applyBeadRadii`'s `scale`.
export let BEAD_RADIUS_SCALE = 1;

export function setBeadRadiusScale(value) {
  const scale = Number(value);
  BEAD_RADIUS_SCALE = Number.isFinite(scale) && scale > 0 ? scale : 1;
}

//: `ball+stick` draws the ball at `atomRadius x radiusScale x aspectRatio` and the stick at
//: `atomRadius x radiusScale` -- measured in this vendored build by reading the two buffers the representation
//: draws from, the sphere's and the cylinder's own `radius` attribute, in Angstroms, which is what the impostor
//: shaders take. So the aspect ratio is what the ball buys back and the radius scale is the one number the ball and
//: the stick share: holding `radiusScale x aspectRatio = 1` draws the ball at the model's own radius while the
//: radius scale -- and with it every bond -- stays free to thin. A structure's radii stay the model's; the
//: correction is in the representation, not in the data.
//:
//: The sticks are drawn at a quarter of the bead, which is half of the half they were drawn at before: measured
//: on a run-shaped frame (every bead written with the `C` stand-in, so every bead an R at 2.64 A), the ball was
//: 2.64 A and the stick 1.32 A, and the bonds read as chunky beside the balls. `BEAD_STICK_FRACTION` is the one
//: number to move to thin or thicken every bond a bead view draws, and the aspect ratio has to move with it -- its
//: reciprocal -- for the ball to stay the model's size. NGL takes an aspect ratio from 1 to 10, so the fraction's
//: floor is 0.1; `radiusScale` itself may be anything above 0.001.
export const BEAD_ASPECT_RATIO = 4;
//: The drawn stick's radius, as a fraction of the bead's own radius.
export const BEAD_STICK_FRACTION = 1 / BEAD_ASPECT_RATIO;
export const BEAD_RADIUS_PARAMETERS = {radiusType: 'explicit', radiusScale: BEAD_STICK_FRACTION,
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
