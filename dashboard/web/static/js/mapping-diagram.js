const SVG_NS = 'http://www.w3.org/2000/svg';
export function mountDiagram(host, scene, context, onAtom) {
  let root = new DOMParser().parseFromString(scene.svg, 'image/svg+xml').documentElement;
  host.replaceChildren(document.importNode(root, true));
  const svg = host.querySelector('svg');
  const handlers = [];
  for (const atom of svg.querySelectorAll('[data-atom-id]')) {
    const id = Number(atom.dataset.atomId);
    if (atom.dataset.heavy !== 'true') continue;
    const handler = event => { event.preventDefault(); onAtom(id, event); };
    atom.addEventListener('click', handler); atom.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') handler(event); }); handlers.push([atom, handler]);
  }
  function update(candidate, selectedAtoms = new Set(), selectedBeads = new Set()) {
    for (const atom of svg.querySelectorAll('[data-atom-id]')) {
      const id = Number(atom.dataset.atomId); const selected = selectedAtoms.has(id); const assigned = (candidate.beads || []).find(bead => bead.atoms?.includes(id));
      atom.setAttribute('aria-pressed', String(selected)); atom.classList.toggle('selected', selected); atom.classList.toggle('assigned', !!assigned);
      if (assigned) atom.dataset.beadName = assigned.name; else delete atom.dataset.beadName;
    }
    let overlay = svg.querySelector('.mapping-overlays'); if (!overlay) { overlay = document.createElementNS(SVG_NS, 'g'); overlay.setAttribute('class', 'mapping-overlays'); svg.append(overlay); }
    overlay.replaceChildren();
    const positions = scene.positions || {};
    (candidate.beads || []).forEach((bead, index) => { const points = (bead.atoms || []).map(id => positions[id]).filter(Boolean); if (!points.length) return; const x = points.reduce((sum, point) => sum + point[0], 0) / points.length; const y = points.reduce((sum, point) => sum + point[1], 0) / points.length; const circle = document.createElementNS(SVG_NS, 'circle'); circle.setAttribute('class', 'bead-overlay'); circle.setAttribute('cx', x); circle.setAttribute('cy', y); circle.setAttribute('r', Math.max(20, ...points.map(point => Math.hypot(point[0] - x, point[1] - y) + 18))); circle.dataset.beadName = bead.name; circle.dataset.beadIndex = index; circle.setAttribute('aria-label', `Bead ${bead.name}`); circle.setAttribute('tabindex', '0'); circle.style.pointerEvents = 'auto'; circle.classList.toggle('selected', selectedBeads.has(bead.name)); overlay.append(circle); });
  }
  return {update, destroy() { for (const [node, handler] of handlers) node.removeEventListener('click', handler); host.replaceChildren(); }};
}
