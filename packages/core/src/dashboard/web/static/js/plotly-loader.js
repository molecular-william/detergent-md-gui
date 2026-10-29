// The Plotly bundle is 4.8 MB and only two panels draw with it, so the shell no longer loads it with the
// page: the template writes the bundle's URL into a `<meta name="plotly-src">`, which keeps the route the
// single definition of where it lives, and a panel that needs to draw asks for it here.
//
// One request per page: panels render on their own schedules (and the bonded panel re-renders on every bead
// selection), so concurrent callers share one promise rather than inject one script each. That promise lives in
// this module instance, which is why the element in the document is the record two copies of it share.
let loading = null;

export function ensurePlotly() {
  if (window.Plotly) return Promise.resolve(window.Plotly);
  if (loading) return loading;
  const src = document.querySelector('meta[name="plotly-src"]')?.content;
  if (!src) {
    return Promise.reject(new Error('The page states no Plotly bundle URL (no meta[name="plotly-src"]).'));
  }
  // `loading` is per copy of this module, and a page can hold two -- a panel importing it, and anything else
  // importing it by its own URL. The element is the record they share: one already in the document is waited on,
  // and only when there is none is a script appended.
  let script = document.querySelector('script[data-plotly]');
  const created = !script;
  if (!script) {
    script = document.createElement('script');
    script.dataset.plotly = 'true';
    script.src = src;
  }
  loading = new Promise((resolve, reject) => {
    script.addEventListener('load', () => {
      if (window.Plotly) resolve(window.Plotly);
      else reject(new Error(`the bundle at ${src} loaded without defining window.Plotly`));
    });
    script.addEventListener('error', () => reject(new Error(`the bundle at ${src} could not be fetched`)));
  }).catch(error => {
    // Nothing is left behind for a later attempt to reuse, and the element is taken out of the document: its load
    // and error events have already fired and will not fire again, so leaving it would make every retry a wait on
    // a script that will never speak. A failure is not a load, so the next panel asks again.
    loading = null;
    script.remove();
    throw error;
  });
  if (created) document.head.append(script);
  return loading;
}
