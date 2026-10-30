import { $, $$, storage } from './shared.js';

// The two-level navigation is server-rendered: the big tabs are workspace links, the sub-tab row holds the active
// workspace's panels, and the server has already marked which panel is open. So this module no longer decides what a
// page contains -- it keeps switching instant once the page is here, and it remembers where the person was.
//
// The panels are resolved by `data-tab`, which the template writes from the registry's DOM ids. Those ids are
// deliberately not the URL slugs; dashboard/web/sections.py carries the reason.

function subTabs() {
  return $$('nav.subtabs [role=tab][data-tab]');
}

// /detergent-validation/new-run -> ['detergent-validation', 'new-run']
function pathParts() {
  return location.pathname.split('/').filter(Boolean);
}

// The previous navigation named a panel only in the fragment, so a real bookmark looks like `/#bonded` -- and every
// browser test did too. A fragment is never sent to a server, so answering it is the client's job: the shell carries
// a map from the old name to its address, and this follows it. `replace`, not `assign`, so the old URL does not sit
// in the history for a person to walk back into.
function redirectLegacyFragment() {
  if (!location.hash) return false;
  const block = document.getElementById('legacy-tabs');
  if (!block) return false;
  let targets;
  try { targets = JSON.parse(block.textContent); } catch (error) { return false; }
  const target = targets[location.hash.slice(1)];
  if (!target) return false;
  location.replace(target);
  return true;
}

export function selectTab(id, { push = true } = {}) {
  const tabs = subTabs();
  if (!tabs.length) return;
  const wanted = tabs.find(tab => tab.dataset.tab === id) || tabs[0];
  tabs.forEach(tab => {
    const active = tab === wanted;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    const panel = document.getElementById(tab.dataset.tab);
    // A tab whose panel is missing would otherwise hide every panel on the page and read as a blank workspace.
    if (panel) panel.hidden = !active;
  });
  const href = wanted.getAttribute('href');
  if (push && href && location.pathname !== href) history.pushState(null, '', href);
  const section = pathParts()[0];
  if (section) storage.set('tab:' + section, wanted.dataset.tab);
  document.dispatchEvent(new CustomEvent('dashboard:tab', { detail: { id: wanted.dataset.tab } }));
}

function showPanelForPath() {
  const slug = pathParts()[1];
  const tab = subTabs().find(candidate => (candidate.getAttribute('href') || '').endsWith('/' + slug));
  if (tab) selectTab(tab.dataset.tab, { push: false });
}

// Both lists are horizontal whatever the window width, so assistive technology is told that once rather than being
// tracked against a breakpoint. The stylesheet wraps the big tabs on a narrow window; wrapping does not make a
// tablist vertical.
function syncOrientation() {
  $$('nav.section-tabs[role=tablist], nav.subtabs[role=tablist]')
    .forEach(list => list.setAttribute('aria-orientation', 'horizontal'));
}

// Arrow keys move within a list, which is what a tablist promises whatever its orientation.
function wireKeyboard(list) {
  const tabs = $$('[role=tab]', list);
  tabs.forEach((tab, i) => {
    tab.addEventListener('keydown', event => {
      let target;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') target = (i + 1) % tabs.length;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') target = (i + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') target = 0;
      if (event.key === 'End') target = tabs.length - 1;
      if (target === undefined) return;
      event.preventDefault();
      const destination = tabs[target];
      if (destination.dataset.tab) selectTab(destination.dataset.tab);
      else if (destination.getAttribute('href')) location.assign(destination.getAttribute('href'));
      destination.focus();
    });
  });
}

export function initializeTabs() {
  if (redirectLegacyFragment()) return;
  // A fragment-only navigation -- someone following `/#bonded`, or a test doing the same -- does not reload the
  // page, so nothing above runs again. Without this listener the old links work on a cold load and do nothing on a
  // same-page one, which is the difference between a bookmark and a click.
  window.addEventListener('hashchange', () => {
    if (!redirectLegacyFragment()) showPanelForPath();
  });
  subTabs().forEach(tab => {
    tab.addEventListener('click', event => {
      // The href is real, so a cold request works and the URL means something; intercepting it only spares a
      // page load for someone already here.
      event.preventDefault();
      selectTab(tab.dataset.tab);
    });
  });
  $$('[data-go]').forEach(button => button.onclick = () => selectTab(button.dataset.go));

  const parts = pathParts();
  const here = parts[0];
  const remembered = storage.get('workspace', '');
  if (!here) {
    // The front door answers with one workspace. A browser that was last in another one is sent onward -- but only
    // when that workspace is still shown. A remembered workspace a module switch hid would otherwise bounce through
    // `/` forever: its URL redirects back here, and this line sent it there again.
    const shown = new Set($$('nav.section-tabs [data-section]').map(tab => tab.dataset.section));
    if (remembered && shown.has(remembered)) location.replace('/' + remembered);
  } else {
    storage.set('workspace', here);
    // With no fragment in the URL any more, a remembered panel is what decides -- unless the URL already names one.
    if (!parts[1] && storage.get('tab:' + here, '')) showPanelForPath();
  }

  wireKeyboard(document.querySelector('nav.section-tabs[role=tablist]'));
  wireKeyboard(document.querySelector('nav.subtabs[role=tablist]'));
  syncOrientation();
  // Announce the open panel once, whatever the URL says. Every panel is mounted by a `dashboard:tab` listener in
  // main.js, and that event fires only from selectTab -- so a page whose URL names no panel (the root, which is the
  // front door and the common case) must still announce the one that is open, or nothing mounts and every panel on
  // the page stays empty. The server has already marked it with aria-selected, so this reads it back rather than
  // deciding again; the first tab is the fallback for a page that somehow marked none.
  const openPanel = subTabs().find(tab => tab.getAttribute('aria-selected') === 'true') || subTabs()[0];
  if (openPanel) selectTab(openPanel.dataset.tab, { push: false });
  window.addEventListener('popstate', showPanelForPath);
}
