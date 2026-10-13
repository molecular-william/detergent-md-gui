// A 3D view of a mapped molecule: the atoms where they are, and every bead as a translucent sphere at the centre
// of the atoms it maps. Mounted like the 2D diagram, so the editor can keep both and they cannot disagree -- the
// spheres come from the same server-side function that the panel's 2D circles do.
//
// Everything here rests on primitives measured in this vendored build rather than on what the API is called:
//
//   picking    stage.pickingControls.pick(x, y) takes CANVAS-relative coordinates and returns the atom under them.
//              The stage's own `clicked` signal fires but carries no payload here, so the pick is called directly.
//   selection  a bare word is parsed as a residue name, which is why the bead file puts each bead's size class in
//              its residue column; atoms are addressed by position (`@0` is the first).
//   spheres    a representation's opacity is one of its parameters, which is why beads arrive as a file of one
//              atom each instead of as shapes -- the shape primitive in this build builds nothing renderable.
const VDW_CARBON = 1.70;                        // NGL's van der Waals radius for carbon, the bead atoms' element
const SIZE_RADII = {R: 2.64, S: 2.30, T: 1.91}; // Martini's molecular-volume classes, as the composition panel draws
const BEAD_COLOURS = {R: 0x4a5568, S: 0x2b6cb0, T: 0xb7791f};
const BEAD_OPACITY = 0.35;                      // translucent enough to read the atoms through a sphere
// Every atom carries its mapping id. The PDB's serials ARE those ids -- serials() reads them back for picking --
// so a label of `serial` prints the same number a table row's `atoms` field lists, which is the whole point of
// drawing them. `atomindex` would print the structure's own 0-based order and send a reader to the wrong atom.
// The parameters live here rather than inline because the panel can add this representation again after removing
// it: two spellings of it would drift, and the drift would be in what the numbers mean.
const LABEL_PARAMETERS = {sele: 'all', labelType: 'serial', labelSize: 2, labelColor: 'black',
                          labelZOffset: 1.5, fixedSize: true, showBackground: true,
                          backgroundColor: 'white', backgroundOpacity: 0.75};

function serials(pdb) {
  // The written serials, in file order, so a structure index can be turned back into a mapping atom id.
  return [...pdb.matchAll(/^HETATM(.{5})/gm)].map(match => Number(match[1]));
}

export function mountOverlay3d(host, context, onAtom) {
  // NGL appends its canvas to the host and dispose() does not take it away again, so the container is emptied
  // here and in destroy(). Without that, switching molecules leaves one canvas per mount behind.
  host.replaceChildren();
  const stage = new NGL.Stage(host, {backgroundColor: 'white'});
  // The stage lives in this closure, so the container carries it for the test seam, as the composition panel's
  // workspace carries its own stages. A browser test can then ask the viewer what it actually holds rather than
  // what the code intended to hand it.
  host.overlayStage = stage;
  let signature = null;          // the bead assignment currently drawn, so an unchanged one costs no request
  let atomIds = [];              // structure index -> mapping atom id
  let beads = [];                // the spheres as the server described them, in file order
  let labelsWanted = true;       // whether every atom is numbered; the panel's default, and what a toggle sets
  let labelComponent = null;     // the component the numbers are drawn on, null until a structure is loaded
  let labelRepresentation = null; // the numbers themselves, held so they can be taken away without a refetch

  function applyLabels() {
    // Safe at any point in the panel's life, including before the first structure arrives: with no component here
    // the wanted state is simply kept, and update() applies it when it next builds the components. That is what
    // lets the panel restore the reader's choice at mount, ahead of the request that draws the molecule.
    if (!labelComponent) return;
    if (labelsWanted && !labelRepresentation) {
      labelRepresentation = labelComponent.addRepresentation('label', LABEL_PARAMETERS);
    } else if (!labelsWanted && labelRepresentation) {
      // The representation goes, not the component: the molecule and the beads stay where they are, so a toggle
      // costs no request and moves nothing.
      labelComponent.removeRepresentation(labelRepresentation);
      labelRepresentation = null;
    } else return;
    // This build renders on demand, so a change nothing asks it to redraw is a change nobody sees.
    stage.viewer.requestRender();
  }

  function note(message) {
    if (message) host.dataset.overlayStatus = message;
    else delete host.dataset.overlayStatus;
  }

  async function request(beadsToDraw) {
    const response = await fetch('/api/mappings/overlay3d', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({molecule_id: context.molecule_id,
                            beads: beadsToDraw.map(bead => ({name: bead.name, size: bead.size,
                                                             type: bead.type, atoms: bead.atoms}))}),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error || `Overlay unavailable (${response.status})`);
    }
    return response.json();
  }

  async function update(candidate) {
    const wanted = (candidate?.beads || []).map(bead => ({name: bead.name, size: bead.size, type: bead.type,
                                                          atoms: bead.atoms || []}));
    const key = JSON.stringify(wanted.map(bead => [bead.name, bead.size, bead.atoms]));
    if (key === signature) return;                     // same assignment: nothing to redraw
    signature = key;
    let payload;
    try {
      payload = await request(wanted);
    } catch (error) { note(error.message); return; }
    note('');
    stage.removeAllComponents();
    // Everything that pointed at the old components points at nothing now: removeAllComponents() disposed them.
    labelComponent = null; labelRepresentation = null;
    atomIds = serials(payload.pdb);
    beads = payload.spheres || [];
    try {
      const molecule = await stage.loadFile(new Blob([payload.pdb], {type: 'text/plain'}), {ext: 'pdb'});
      const beadFile = await stage.loadFile(new Blob([payload.bead_pdb], {type: 'text/plain'}), {ext: 'pdb'});
      if (molecule && molecule.structure) {
        labelComponent = molecule;
        molecule.addRepresentation('ball+stick', {sele: 'all', colorScheme: 'element', radiusScale: 0.9});
        applyLabels();
      }
      // One representation per size class: a representation has a single radius scale, so beads of different sizes
      // cannot share one. The class is the residue name, which is the form this build's selections resolve.
      const beadStructure = beadFile && beadFile.structure;
      if (beadStructure && beadStructure.atomCount) {
        for (const [size, radius] of Object.entries(SIZE_RADII)) {
          if (!beadStructure.getAtomIndices(new NGL.Selection(size)).length) continue;
          beadFile.addRepresentation('spacefill', {sele: size, color: BEAD_COLOURS[size], opacity: BEAD_OPACITY,
                                                   radiusScale: radius / VDW_CARBON});
        }
      }
      stage.autoView();
    } catch (error) {
      note(`Could not draw the overlay: ${error.message}`);
    }
    if (!atomIds.length) note('This molecule has no heavy atoms to draw.');
  }

  function pickAt(event) {
    const canvas = stage.viewer.renderer.domElement;
    const rect = canvas.getBoundingClientRect();
    return stage.pickingControls.pick(event.clientX - rect.left, event.clientY - rect.top);
  }

  // The listeners capture: the viewer handles these same events on its own canvas, and a listener on an ancestor
  // never sees them if the viewer stops them there -- which is why a click on a sphere did nothing at all.
  let pressed = null;
  host.addEventListener('mousedown', event => { pressed = {x: event.clientX, y: event.clientY}; }, true);
  host.addEventListener('click', event => {
    // A click that moved is a rotation, not a selection.
    if (pressed && (Math.abs(event.clientX - pressed.x) > 4 || Math.abs(event.clientY - pressed.y) > 4)) return;
    const pick = pickAt(event);
    if (!pick || !pick.atom) return;
    const beadAtom = ['R', 'S', 'T'].includes(String(pick.atom.resname || '').trim());
    // The picked atom carries its own index. This build's pick object has no atomIndex, so looking the sphere up by
    // that name found nothing and a click on a sphere selected nothing -- measured, not assumed.
    const index = pick.atom.index ?? pick.atomIndex;
    if (beadAtom) {
      // A sphere covers its atoms: clicking it is clicking the bead, which selects every atom it maps.
      const sphere = beads[index];
      if (sphere) for (const atomId of sphere.atoms) onAtom(atomId);
      return;
    }
    const atomId = atomIds[index];
    if (atomId) onAtom(atomId);
  }, true);
  host.addEventListener('mouseleave', () => { pressed = null; }, true);

  return {
    update,
    // The panel's toggle. `true` numbers every heavy atom by its mapping id, `false` takes the numbers away; both
    // act on the structure already loaded, so flipping it is instant and costs no request. Before anything is
    // drawn it only records the choice, which update() applies.
    setLabels(visible) { labelsWanted = !!visible; applyLabels(); },
    destroy() {
      labelComponent = null; labelRepresentation = null;
      try { stage.dispose(); } catch (error) { /* a disposed stage is not an error worth showing */ }
      host.replaceChildren();
    },
  };
}
