// NGL is 1.28 MB and only the panels that draw a 3D stage need it, so the shell no longer loads it with the page:
// the template writes the bundle's URL into a `<meta name="ngl-src">`, which keeps the route the single definition
// of where it lives, and a panel that needs to draw asks for it here.
//
// One request per page: monitors, previews and the bead editor mount on their own schedules, so concurrent callers
// share one promise rather than inject one script each. That promise lives in this module instance, which is why the
// element in the document is the record two copies of it share.
let loading = null;

export function ensureNgl() {
  if (window.NGL) return Promise.resolve(window.NGL);
  if (loading) return loading;
  const src = document.querySelector('meta[name="ngl-src"]')?.content;
  if (!src) {
    return Promise.reject(new Error('The page states no NGL bundle URL (no meta[name="ngl-src"]).'));
  }
  // `loading` is per copy of this module, and a page can hold two -- a panel importing it, and anything else
  // importing it by its own URL. The element is the record they share: one already in the document is waited on,
  // and only when there is none is a script appended.
  let script = document.querySelector('script[data-ngl]');
  const created = !script;
  if (!script) {
    script = document.createElement('script');
    script.dataset.ngl = 'true';
    script.src = src;
  }
  loading = new Promise((resolve, reject) => {
    script.addEventListener('load', () => {
      if (window.NGL) resolve(window.NGL);
      else reject(new Error(`the bundle at ${src} loaded without defining window.NGL`));
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
