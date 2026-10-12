export function createEditor(context, candidate = null) {
  if (!context || typeof context.molecule_id !== 'string' || !context.snapshot?.snapshot_sha256) {
    throw new Error('Mapping context is unavailable; reload the page or pick a molecule.');
  }
  return {
    context,
    candidate: structuredClone(candidate || {
      schema_version: 3,
      molecule_id: context.molecule_id,
      molecule_snapshot: context.snapshot,
      name: 'New mapping',
      beads: [],
      rings: [],
      connections: [],
      provenance: {origin: 'manual', references: []},
    }),
    selectedAtoms: new Set(),
    dirty: false,
  };
}

export function toggleAtom(editor, id) {
  const atom = editor.context.atoms.find(item => item.id === id);
  if (!atom?.heavy) return editor;
  if (editor.selectedAtoms.has(id)) editor.selectedAtoms.delete(id); else editor.selectedAtoms.add(id);
  editor.dirty = true;
  return editor;
}

export function clearSelection(editor) { editor.selectedAtoms.clear(); return editor; }

export function clearMapping(editor) {
  editor.candidate = {...editor.candidate, beads: [], rings: [], connections: [], bonded_options: {}, bonded_overrides: []};
  clearSelection(editor);
  editor.dirty = true;
  return editor;
}

export function groupAtoms(editor, atomIds, bead, {confirmed = false} = {}) {
  const ids = new Set(atomIds);
  if (!ids.size) throw new Error('Select one or more heavy atoms first.');
  const known = new Map(editor.context.atoms.map(atom => [atom.id, atom]));
  if ([...ids].some(id => !known.get(id)?.heavy)) throw new Error('Only known heavy atoms can be assigned.');
  const next = structuredClone(editor.candidate);
  const prior = next.beads.filter(item => !item.virtual_site && item.atoms.some(id => ids.has(id)));
  if (prior.length && !confirmed) return {requiresConfirmation: true, prior: prior.map(item => item.name), candidate: next};
  for (const item of next.beads) if (!item.virtual_site) item.atoms = item.atoms.filter(id => !ids.has(id));
  const created = {...bead, atoms: [...ids].sort((a, b) => a - b)};
  next.beads = next.beads.filter(item => item.virtual_site || item.atoms.length || prior.length === 0);
  next.beads.push(created);
  editor.candidate = next; clearSelection(editor); editor.dirty = true; return editor;
}

export function renameBead(editor, oldName, newName) {
  const name = String(newName || '').trim(); if (!name) throw new Error('Bead name is required.');
  const next = structuredClone(editor.candidate); const bead = next.beads.find(item => item.name === oldName); if (!bead) throw new Error('Unknown bead.');
  bead.name = name;
  for (const item of next.beads) if (item.virtual_site) item.virtual_site.parents = item.virtual_site.parents.map(parent => parent === oldName ? name : parent);
  for (const ring of next.rings || []) { ring.beads = ring.beads.map(parent => parent === oldName ? name : parent); if (ring.virtual_site === oldName) ring.virtual_site = name; }
  next.connections = (next.connections || []).map(pair => pair.map(item => item === oldName ? name : item));
  editor.candidate = next; editor.dirty = true; return editor;
}

export function removeBead(editor, name) {
  const next = structuredClone(editor.candidate); if (next.beads.some(item => item.virtual_site?.parents.includes(name))) throw new Error('Remove dependent interaction site first.');
  next.beads = next.beads.filter(item => item.name !== name); next.rings = (next.rings || []).filter(ring => ring.virtual_site !== name && !ring.beads.includes(name)); next.connections = (next.connections || []).filter(pair => !pair.includes(name));
  editor.candidate = next; editor.dirty = true; return editor;
}
