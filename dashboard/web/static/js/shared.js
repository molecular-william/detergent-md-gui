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
function invalidateResource(prefix) {
  for(const key of resources.keys())if(key.startsWith(prefix))resources.delete(key);
  document.dispatchEvent(new CustomEvent('dashboard:resources-changed',{detail:{prefix}}));
}

export { loadOnce, cachedApi, invalidateResource, $,  $$, storage, setText, notice, api, post, downloadBlob };
