import { $, $$, storage, setText, api, post, downloadBlob, invalidateResource } from './shared.js';

// Shared colour palette for bead swatches and rows. Kept in this module
// because only MappingPanel uses it.
const COLORS = ['#2864b5','#169186','#aa6920','#8762b6','#ba4775','#347844','#a74b32','#536697','#8b751b','#6754ac','#287d93','#ae5486'];

/**
 * One candidate editor: bead table, name field, validation, exports.
 *
 * The panel operates on a shared `mappingData` object (with `candidates` and
 * `bead_types`) and a shared `panels` array so that any candidate-list change
 * refreshes every open panel. `loadMapping(file)` is the async accessor for a
 * saved candidate.
 */
export class MappingPanel {
  constructor({index, mappingData, loadMapping, panels}) {
    this.index = index;
    this.mappingData = mappingData;
    this.loadMapping = loadMapping;
    this.panels = panels;
    this.generation = 0;
    this.card = $('#mapping-template').content.firstElementChild.cloneNode(true);
    const nameLabel = $('.candidate-name', this.card)?.parentElement;
    const table = $('.table-scroll', this.card);
    const add = $('.bead-add-controls', this.card);
    const validation = $('.validation', this.card);
    const left = document.createElement('div'); left.className = 'mapping-left';
    [nameLabel, table, add, $('.ring-summary', this.card), $('.bonded-editor', this.card), validation]
      .forEach(node => { if (node) left.append(node); });
    const columns = document.createElement('div'); columns.className = 'mapping-columns';
    columns.append(left);
    this.card.insertBefore(columns, $('.save-candidate', this.card).parentElement);
    $('#comparison').append(this.card);
    this.select = $('.candidate-select', this.card);
    this.fillOptions();
    this.select.addEventListener('change', () => this.load(this.select.value));
    const deleteButton = $('.delete-selected', this.card);
    if (deleteButton) deleteButton.onclick = async () => {
      const file = this.data?.file;
      if (!file || !/^mapping_candidate_[A-Za-z0-9_.-]+\.json$/.test(file)) { setText($('.mapping-message', this.card), 'Only dashboard-created draft candidates can be deleted.'); return; }
      try {
        await api('/api/mappings/drafts/' + encodeURIComponent(file), {method: 'DELETE'});
        invalidateResource('/api/mappings');
        this.mappingData.candidates = this.mappingData.candidates.filter(c => c.file !== file);
        this.panels.forEach(p => p.fillOptions());
        setText($('.mapping-message', this.card), 'Selected draft deleted. Reload mappings to refresh the candidate list.');
      } catch (error) { setText($('.mapping-message', this.card), error.message); }
    };
    $('.candidate-name', this.card).addEventListener('input', () => { if (!this.data) return; this.data.name = $('.candidate-name', this.card).value; this.edited(); });
    $('.add-virtual-site', this.card).onclick = () => {
      const parents = this.data.beads.filter(b => !b.virtual_site).slice(0, 3).map(b => b.name);
      if (parents.length !== 3) { setText($('.mapping-message', this.card), 'Create three massive ring beads first.'); return; }
      const name = `VS${this.data.beads.length + 1}`;
      this.data.beads.push({name, size: 'T', type: 'TC4', atoms: [], virtual_site: {parents, function: 1}});
      this.data.rings = this.data.rings || [];
      this.data.rings.push({beads: parents, virtual_site: name, scale: 1.15});
      this.rows(); this.edited();
    };
    $('.add-bead', this.card).onclick = () => { this.data.beads.push({name: `BEAD${this.data.beads.length + 1}`, size: 'S', atoms: []}); this.rows(); this.edited(); };
    const saveButton = $('.save-candidate', this.card);
    if (saveButton) saveButton.onclick = async () => {
      try {
        if (!this.data.name?.trim()) this.data.name = `DDM candidate ${String(this.mappingData.candidates.length + 1).padStart(2, '0')}`;
        $('.candidate-name', this.card).value = this.data.name;
        const saved = await post('/api/mappings/drafts', this.data);
        invalidateResource('/api/mappings');
        this.mappingData.candidates.push(saved);
        this.panels.forEach(panel => panel.fillOptions());
        this.load(saved.file);
        setText($('.mapping-message', this.card), 'Saved as a new unvalidated draft. The source candidate is preserved.');
      } catch (error) { setText($('.mapping-message', this.card), error.message); }
    };
    const approveButton = $('.approve-candidate', this.card);
    if (approveButton) approveButton.onclick = async () => {
      try {
        await post('/api/mappings/review', {...this.data, state: 'approved', reviewer: 'dashboard user', notes: 'Approved after dashboard structural validation.'});
        setText($('.mapping-message', this.card), 'Mapping approved. Scientific validation is still required before production.');
      } catch (error) { setText($('.mapping-message', this.card), error.message); }
    };
    const exportButton = $('.export-candidate', this.card);
    if (exportButton) exportButton.onclick = () => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(this.data, null, 2)], {type: 'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = 'ddm-mapping-draft.json'; link.click(); URL.revokeObjectURL(url);
    };
    const exportDiagram = $('.export-diagram', this.card);
    if (exportDiagram) exportDiagram.onclick = async () => {
      try {
        const result = await post('/api/mappings/diagram', this.data);
        downloadBlob(new Blob([result.svg], {type: 'image/svg+xml'}), 'ddm-mapping-diagram.svg');
      } catch (error) { setText($('.mapping-message', this.card), error.message); }
    };
    $$('.export-mapping', this.card).forEach(button => button.onclick = async () => {
      button.disabled = true;
      try {
        const response = await fetch('/api/mappings/export/' + button.dataset.format, {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(this.data), signal: AbortSignal.timeout(10000)
        });
        if (!response.ok) throw new Error((await response.json()).error || 'Export failed');
        const names = {ndx: 'mapping.ndx', map: 'mapping.map', gro: 'mapped.gro', bundle: 'ddm-mapping-candidate.zip'};
        downloadBlob(await response.blob(), names[button.dataset.format]);
        setText($('.mapping-message', this.card), 'Exported for review. Structural findings and model validation still apply.');
      } catch (error) { setText($('.mapping-message', this.card), error.message); }
      finally { button.disabled = false; }
    });
    const persisted = storage.get('mapping.' + index);
    this.load(persisted?.file || this.mappingData.candidates[index % this.mappingData.candidates.length]?.file, persisted);
  }

  fillOptions() {
    const value = this.select.value;
    this.select.replaceChildren();
    for (const candidate of this.mappingData.candidates) {
      const option = document.createElement('option');
      option.value = candidate.file;
      option.textContent = candidate.name + (candidate.error ? ' · unavailable' : '');
      option.disabled = !!candidate.error;
      this.select.append(option);
    }
    if (value) this.select.value = value;
  }

  async load(file, persisted) {
    const generation = ++this.generation;
    $('.save-candidate', this.card).disabled = true;
    $('.approve-candidate', this.card).disabled = true;
    let source;
    try { source = await this.loadMapping(file); }
    catch (error) { if (generation === this.generation) setText($('.mapping-message', this.card), error.message); return; }
    if (generation !== this.generation) return;
    if (!source) { setText($('.mapping-message', this.card), 'Candidate unavailable'); return; }
    this.data = structuredClone(persisted?.beads ? persisted : source);
    delete this.data.validation;
    this.data.status = 'candidate-unvalidated';
    this.select.value = file;
    $('.candidate-name', this.card).value = this.data.name;
    setText($('.mapping-status', this.card), 'Candidate · unvalidated · Martini 3 · DDM SwissParam atom order');
    this.rows(); this.edited();
  }

  loadData(data) {
    this.data = structuredClone(data);
    this.data.status = 'candidate-unvalidated';
    $('.candidate-name', this.card).value = '';
    this.rows(); this.edited();
  }

  rows() {
    this.syncBondedEditor();
    const editor = $('.bonded-settings', this.card);
    editor.oninput = () => {
      this.generation++; clearTimeout(this.timer);
      $('.save-candidate', this.card).disabled = true;
      $('.approve-candidate', this.card).disabled = true;
      try {
        const value = JSON.parse(editor.value);
        if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).some(k => !['connections', 'bonded_options', 'bonded_overrides'].includes(k))) throw new Error('Use only connections, bonded_options and bonded_overrides');
        if (!Array.isArray(value.connections) || !Array.isArray(value.bonded_overrides) || !value.bonded_options || typeof value.bonded_options !== 'object') throw new Error('Keep all three fields: connections, bonded_options and bonded_overrides');
        Object.assign(this.data, value); this.bondedInvalid = false;
        setText($('.bonded-message', this.card), 'Bonded edits applied locally; save a new candidate to use them in a run.');
        this.edited();
      } catch (error) { this.bondedInvalid = true; setText($('.bonded-message', this.card), 'Invalid bonded JSON: ' + error.message); }
    };
    const table = $('.bead-rows', this.card); table.replaceChildren();
    this.data.beads.forEach((bead, i) => {
      const row = document.createElement('tr'); row.style.setProperty('--bead-color', COLORS[i % COLORS.length]);
      for (const field of ['name', 'size', 'type', 'atoms']) {
        const cell = document.createElement('td');
        const input = document.createElement(field === 'size' || field === 'type' ? 'select' : 'input');
        input.setAttribute('aria-label', `Bead ${i+1} ${field}`);
        if (field === 'size') for (const size of ['R', 'S', 'T']) { const opt = document.createElement('option'); opt.value = size; opt.textContent = size; input.append(opt); }
        if (field === 'type') {
          input.append(new Option('Choose type', ''));
          for (const item of this.mappingData.bead_types || []) input.append(new Option(`${item.type} · ${item.description}`, item.type));
          if (bead.type && !Array.from(input.options).some(o => o.value === bead.type)) input.append(new Option(`${bead.type} · unsupported`, bead.type));
        }
        if (field === 'atoms') input.className = 'atoms-input';
        input.value = field === 'atoms' ? (bead.virtual_site ? bead.virtual_site.parents.join(' ') : bead.atoms.join(' ')) : (bead[field] || '');
        if (field === 'atoms' && bead.virtual_site) { input.setAttribute('aria-label', `Virtual site ${bead.name} parents`); input.title = 'Three parent bead names, separated by spaces'; }
        if (bead.virtual_site && ['size', 'type'].includes(field)) input.disabled = true;
        input.addEventListener('input', () => {
          if (field === 'atoms' && bead.virtual_site) {
            bead.virtual_site.parents = input.value.trim().split(/[\s,]+/);
            for (const r of this.data.rings || []) if (r.virtual_site === bead.name) r.beads = [...bead.virtual_site.parents];
          } else if (field === 'atoms') {
            const parts = input.value.trim() ? input.value.trim().split(/[\s,]+/) : [];
            input.setCustomValidity(parts.every(x => /^\d+$/.test(x)) ? '' : 'Use atom indices separated by spaces');
            bead.atoms = parts.map(Number);
          } else {
            if (field === 'name') {
              const old = bead.name;
              for (const b of this.data.beads) if (b.virtual_site) b.virtual_site.parents = b.virtual_site.parents.map(n => n === old ? input.value : n);
              for (const r of this.data.rings || []) { r.beads = r.beads.map(n => n === old ? input.value : n); if (r.virtual_site === old) r.virtual_site = input.value; }
              this.data.connections = (this.data.connections || []).map(pair => pair.map(n => n === bead.name ? input.value : n));
              for (const term of this.data.bonded_overrides || []) term.beads = term.beads.map(n => n === bead.name ? input.value : n);
            }
            bead[field] = input.value;
            if (field === 'type') {
              const chosen = (this.mappingData.bead_types || []).find(t => t.type === input.value);
              if (chosen) { bead.size = chosen.size; row.querySelector('[aria-label$=" size"]').value = chosen.size; }
            }
          }
          this.syncBondedEditor(); this.edited();
        });
        cell.append(input); row.append(cell);
      }
      const cell = document.createElement('td'), remove = document.createElement('button');
      remove.type = 'button'; remove.className = 'secondary'; remove.textContent = '×'; remove.setAttribute('aria-label', `Remove bead ${bead.name}`);
      remove.onclick = () => {
        if (this.data.beads.some(b => b.virtual_site?.parents.includes(bead.name))) { setText($('.mapping-message', this.card), 'Remove or reassign the dependent interaction site before removing its parent bead.'); return; }
        this.data.rings = (this.data.rings || []).filter(r => r.virtual_site !== bead.name && !r.beads.includes(bead.name));
        this.data.connections = (this.data.connections || []).filter(pair => !pair.includes(bead.name));
        this.data.beads.splice(i, 1); this.rows(); this.edited();
      };
      cell.append(remove); row.append(cell); table.append(row);
    });
  }

  syncBondedEditor() {
    const editor = $('.bonded-settings', this.card);
    if (editor) editor.value = JSON.stringify({connections: this.data.connections || [], bonded_options: this.data.bonded_options || {}, bonded_overrides: this.data.bonded_overrides || []}, null, 2);
    this.bondedInvalid = false;
  }

  edited() {
    this.generation++;
    setText($('.ring-summary', this.card), `${(this.data.rings || []).length} recognized sugar rings · ${this.data.beads.filter(b => b.virtual_site).length} massless interaction sites. Ring constraints scale ×1.15; connecting bonds are fitted unscaled.`);
    $('.approve-candidate', this.card).disabled = true;
    storage.set('mapping.' + this.index, this.data);
    $('.save-candidate', this.card).disabled = true;
    clearTimeout(this.timer);
    if (!this.bondedInvalid) this.timer = setTimeout(() => this.validate(), 250);
  }

  async validate() {
    const generation = this.generation;
    try {
      const result = await post('/api/mappings/validate', this.data);
      if (generation !== this.generation) return;
      setText($('.validation-summary', this.card), `${result.covered}/${result.heavy_atoms} heavy atoms · ${result.bead_count} beads · nominal ${result.represented_atoms} atoms · difference ${result.mismatch > 0 ? '+' : ''}${result.mismatch} · 2D overlap ${result.overlap_crowding ?? 'n/a'} (${result.overlap_pairs ?? 0} pairs)`);
      const issues = $('.validation-issues', this.card); issues.replaceChildren();
      for (const item of result.issues) { const li = document.createElement('li'); li.textContent = item.message; issues.append(li); }
      if (!result.issues.length) { const li = document.createElement('li'); li.textContent = 'Structural checks passed. Bead chemistry, shape, symmetry and physical behaviour still need review.'; issues.append(li); }
      $$('.bead-rows tr', this.card).forEach((row, i) => row.classList.toggle('invalid-bead', result.issues.some(item => item.bead === i)));
      $('.save-candidate', this.card).disabled = false;
      $('.approve-candidate', this.card).disabled = !result.checks_passed;
      setText($('.mapping-message', this.card), 'Edits are saved in this browser. Save a new draft to keep a version on disk.');
    } catch (error) {
      if (generation !== this.generation) return;
      setText($('.validation-summary', this.card), error.message);
      $('.validation-issues', this.card).replaceChildren();
    }
  }
}