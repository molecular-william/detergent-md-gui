import { $, $$, storage } from './shared.js';

// The document is the tab list: the buttons carry role=tab and data-tab, so a tab that is
// added to dashboard.html works without a second list to keep in step.
function tabIds() {
  return $$('[role=tab][data-tab]').map(tab => tab.dataset.tab);
}

export function selectTab(id) {
  const ids = tabIds();
  if (!ids.includes(id)) id = ids[0] || 'runs';
  $$('[role=tab][data-tab]').forEach(tab => {
    const active = tab.dataset.tab === id;
    tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
    $('#' + tab.dataset.tab).hidden = !active;
  });
  storage.set('tab', id);
  history.replaceState(null, '', location.pathname + location.search + '#' + id);
  document.dispatchEvent(new CustomEvent('dashboard:tab',{detail:{id}}));
}

export function initializeTabs() {
  $$('[role=tab][data-tab]').forEach((tab, i, tabs) => {
    tab.addEventListener('click', () => selectTab(tab.dataset.tab));
    tab.addEventListener('keydown', event => {
      let target;
      if (event.key === 'ArrowRight') target = (i + 1) % tabs.length;
      if (event.key === 'ArrowLeft') target = (i + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') target = 0;
      if (event.key === 'End') target = tabs.length - 1;
      if (target !== undefined) { event.preventDefault(); selectTab(tabs[target].dataset.tab); tabs[target].focus(); }
    });
  });
  $$('[data-go]').forEach(button => button.onclick = () => selectTab(button.dataset.go));
  selectTab(location.hash.slice(1) || storage.get('tab', 'runs'));
  window.addEventListener('hashchange', () => selectTab(location.hash.slice(1)));

}
