import { $, cachedApi } from './shared.js';

export function createPdc() {
  const template = $('#pdc-template'), protein = $('#pdc-protein');
  const status = $('#pdc-panel-status'), limitation = $('#pdc-template-limitation');
  let catalog = null;

  function fill(select, values, label) {
    select.replaceChildren(...values.map(item => new Option(label(item), item.id)));
  }

  function describe() {
    // The catalogue reports what a template *is*, not only its name: the shipped one is a skeleton, and a panel
    // that hid that would be offering a fitted detergent model the repository does not have.
    const chosen = (catalog?.templates || []).find(item => item.id === template.value);
    if (limitation) limitation.textContent = chosen ? chosen.limitations.join(' · ') : '';
    if (status) status.textContent = chosen && !chosen.files_present
      ? 'This template names files the repository does not have; a build would stop at validation rather than later.'
      : 'Setup only: this panel lists what can be built; the pipeline stages follow.';
  }

  async function load() {
    if (catalog) return;
    catalog = await cachedApi('/api/pdc/catalog', {maxAge: 60000});
    fill(template, catalog.templates, item => `${item.name} · ${item.registered_type || 'unregistered'}`);
    // An empty micelle is in scope, so the protein list leads with the absence of one.
    fill(protein, [{id: '', name: 'No protein (empty micelle)'}, ...catalog.proteins], item => item.name);
    describe();
  }

  template?.addEventListener('change', describe);
  return { mount: async () => { await load(); return $('#pdc'); } };
}
