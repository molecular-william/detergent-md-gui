import { $ } from './shared.js';

export function createPdc() {
  // The setup controls and the viewer arrive with the pipeline they drive. Until then the tab exists so the
  // workspace shows where the second workflow will live, and its hint says so rather than offering dead controls.
  return { mount: async () => $('#pdc') };
}
