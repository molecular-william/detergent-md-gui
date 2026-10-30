/**
 * The installed-module switch in the header.
 *
 * A feature's module is installed, not loaded on demand, so switching it off is a saved view decision: this module
 * writes the set to `/api/modules` and offers a reload, which is when the server rebuilds the navigation and the New
 * run form from the filtered registry. Nothing here hides a workspace in the current page: the reader may be halfway
 * through one.
 */
export function initModules() {
  const button = document.querySelector('#modules-button');
  const popover = document.querySelector('#modules-popover');
  if (!button || !popover) return;
  const inputs = [...popover.querySelectorAll('input[data-module]')];
  const dirty = document.querySelector('#modules-dirty');
  const reload = document.querySelector('#modules-reload');
  const notice = document.querySelector('#notice');

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

  function say(message) {
    if (!notice) return;
    notice.textContent = message;
    notice.hidden = false;
  }

  async function restore() {
    const response = await fetch('/api/modules');
    if (!response.ok) return;
    const state = await response.json();
    for (const row of state.modules || []) {
      const input = inputs.find(item => item.dataset.module === row.name);
      if (input) input.checked = row.enabled;
    }
  }

  async function save() {
    const enabled = inputs.filter(input => input.checked).map(input => input.dataset.module);
    const response = await fetch('/api/modules', {
      method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled}),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      say(body.error || `The module switch could not be saved (${response.status}).`);
      await restore();
      return;
    }
    dirty.hidden = false;
  }

  inputs.forEach(input => input.addEventListener('change', () => {
    save().catch(error => say(error.message));
    // The row's own state follows the switch, so the popover reads correctly before the reload.
    input.closest('.module-row').classList.toggle('is-off', !input.checked);
  }));
  if (reload) reload.addEventListener('click', () => location.reload());
}
