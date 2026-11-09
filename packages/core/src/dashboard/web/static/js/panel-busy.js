// One visible status line for a panel that is still waiting. It is the section's first child, never inside a table or
// a list, and it is removed when the wait ends so the panel's own content is all that remains. No state: the line in
// the DOM is the state, and calling this twice with the same text writes the same line twice.
const NOT_A_HOST = new Set(['TABLE', 'TBODY', 'THEAD', 'TFOOT', 'TR', 'UL', 'OL']);

export function setPanelBusy(element, text) {
  if (!element) return;
  const line = element.querySelector(':scope > .panel-loading');
  if (!text) {
    if (line) line.remove();
    element.setAttribute('aria-busy', 'false');
    return;
  }
  element.setAttribute('aria-busy', 'true');
  if (!line && !NOT_A_HOST.has(element.tagName)) {
    const added = document.createElement('p');
    added.className = 'panel-loading';
    added.setAttribute('role', 'status');
    added.textContent = text;
    element.prepend(added);
  } else if (line) line.textContent = text;
}
