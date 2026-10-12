// Stateless DOM, HTTP and browser-persistence helpers shared by the dashboard modules.
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const storage = {
  get(key, fallback = null) { try { return JSON.parse(localStorage.getItem('ddm.' + key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem('ddm.' + key, JSON.stringify(value)); } catch {} }
};
const setText = (node, value) => { const text = String(value ?? ''); if (node.textContent !== text) node.textContent = text; };
function notice(message) { setText($('#notice'), message); $('#notice').hidden = !message; }
async function api(path, options = {}) {
  const timeout=AbortSignal.timeout(10000);
  const response = await fetch(path, {...options, signal:options.signal?AbortSignal.any([timeout,options.signal]):timeout});
  if (response.status === 304) return null;
  const type = response.headers.get('content-type') || '';
  const data = type.includes('json') ? await response.json() : {error: `Request failed (${response.status})`};
  if (!response.ok) { const error=new Error(data.error || `Request failed (${response.status})`); error.status=response.status; throw error; }
  return data;
}
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const post = (path, data) => api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});

// Share in-flight loads, keep successful GETs briefly, and never retain failures.
const resources = new Map();
function loadOnce(key, loader, {maxAge=Infinity}={}) {
  const cached=resources.get(key);
  if(cached && (!cached.settled || Date.now()-cached.updated < maxAge))return cached.promise;
  const entry={settled:false,updated:0};
  entry.promise=Promise.resolve().then(loader).then(value=>{
    entry.settled=true;entry.updated=Date.now();return value;
  }, error=>{if(resources.get(key)===entry)resources.delete(key);throw error;});
  resources.set(key,entry);
  return entry.promise;
}
function cachedApi(path, options={}) { return loadOnce(path,()=>api(path),options); }
// Latest-wins loader: one generation per key. A superseded answer comes back as DROP rather
// than as a never-settling promise, because callers await these loaders -- the poll loops and
// the tests do -- and a promise that never settles hangs them. A superseded failure is
// dropped with it, instead of raising an error about an answer the caller has replaced.
// Callers keep their own checks for conditions that are not generations (a paused console).
const DROP = Symbol('superseded');
const generations = new Map();
function guarded(key, loader) {
  const token = (generations.get(key) || 0) + 1;
  generations.set(key, token);
  const current = () => generations.get(key) === token;
  return Promise.resolve().then(loader).then(
    value => (current() ? value : DROP),
    error => { if (current()) throw error; return DROP; }
  );
}
function invalidateResource(prefix) {
  for(const key of resources.keys())if(key.startsWith(prefix))resources.delete(key);
  document.dispatchEvent(new CustomEvent('dashboard:resources-changed',{detail:{prefix}}));
}

// The DOM id each panel's section carries, written by the template from the registry (`web/sections.py`). A module
// reads its own id from here instead of repeating the literal, so renaming a panel in the registry reaches every
// module that addresses it: the vocabulary has one owner, and the modules follow it rather than restating it.
// Read per call rather than cached: it is a `getElementById` and a nine-key parse, and a latched lookup has a way to
// be wrong that a fresh one does not.
const panelIds = () => {
  const block = document.getElementById('panel-ids');
  try { return block ? (JSON.parse(block.textContent) || {}) : {}; } catch { return {}; }
};

export { loadOnce, cachedApi, invalidateResource, guarded, DROP, $,  $$, storage, setText, notice, api, post, downloadBlob, panelIds };
