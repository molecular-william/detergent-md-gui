// The theme control in the header. The page boots dark -- <html> carries `data-theme="dark"` and an inline head script
// swaps in a stored light choice before the first paint -- so this module only flips the attribute and remembers the
// answer. Plotly is the one canvas CSS cannot repaint: its own layout states the text colour, so plots already drawn are
// relaid out here, and the modules that draw later take their layout from `plotTheme()` in `shared.js`.
import { storage } from './shared.js';

const THEME_KEY = 'theme';
const root = document.documentElement;
const isDark = () => root.dataset.theme === 'dark';

function paint() {
  const dark = isDark();
  const button = document.querySelector('#theme-toggle');
  if (button) {
    button.setAttribute('aria-pressed', String(dark));
    button.title = dark ? 'Switch to the light theme' : 'Switch to the dark theme';
    const glyph = button.querySelector('.theme-glyph');
    if (glyph) glyph.textContent = dark ? '☾' : '☀';
  }
  const plotly = window.Plotly;
  if (!plotly) return;
  const ink = getComputedStyle(root).getPropertyValue('--ink').trim() || '#1c2940';
  for (const host of document.querySelectorAll('.js-plotly-plot')) {
    if (host._fullLayout) plotly.relayout(host, {'font.color': ink}).catch(() => {});
  }
}

export function initTheme() {
  const button = document.querySelector('#theme-toggle');
  if (!button) return;
  paint();
  button.addEventListener('click', () => {
    root.dataset.theme = isDark() ? 'light' : 'dark';
    storage.set(THEME_KEY, root.dataset.theme);
    paint();
  });
}
