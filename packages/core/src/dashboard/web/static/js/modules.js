/**
 * The installed-module switch in the header.
 *
 * A feature's module is installed, not loaded on demand, so switching it off is a saved view decision: this module
 * writes the set to `/api/modules` and offers a reload, which is when the server rebuilds the navigation and the New
 * run form from the filtered registry. Nothing here hides a workspace in the current page: the reader may be halfway
 * through one.
 */
import { api, notice } from './shared.js';

export function initModules() {
  const button = document.querySelector('#modules-button');
  const popover = document.querySelector('#modules-popover');
  if (!button || !popover) return;
  const inputs = [...popover.querySelectorAll('input[data-module]')];
  const dirty = document.querySelector('#modules-dirty');
  const reload = document.querySelector('#modules-reload');

  const open = () => { button.setAttribute('aria-expanded', 'true'); popover.hidden = false; };
  const close = () => { button.setAttribute('aria-expanded', 'false'); popover.hidden = true; };
  button.addEventListener('click', () => (popover.hidden ? open() : close()));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !popover.hidden) { close(); button.focus(); }
  });
  document.addEventListener('click', event => {
    if (popover.hidden) return;
    if (event.target.closest('#modules-popover') || event.target.closest('#modules-button')) return;
    close();
  });

  async function restore() {
    const state = await api('/api/modules');
    for (const row of state.modules || []) {
      const input = inputs.find(item => item.dataset.module === row.name);
      if (input) input.checked = row.enabled;
    }
  }

  async function save() {
    const enabled = inputs.filter(input => input.checked).map(input => input.dataset.module);
    try {
      await api('/api/modules', {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled}),
      });
      dirty.hidden = false;
    } catch (error) {
      notice(`The module switch could not be saved: ${error.message}`);
      await restore();
    }
  }

  inputs.forEach(input => input.addEventListener('change', () => {
    save().catch(error => notice(error.message));
    // The row's own state follows the switch, so the popover reads correctly before the reload.
    input.closest('.module-row').classList.toggle('is-off', !input.checked);
  }));
  if (reload) reload.addEventListener('click', () => location.reload());
}
