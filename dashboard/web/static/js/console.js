import { $, storage, setText, api } from './shared.js';

// Console selection, byte offsets and pause state belong to this viewer.
export function createConsoleViewer({ getCards }) {
  let selectedRun = new URLSearchParams(location.search).get('run') || storage.get('console', '');
  let consolePaused = storage.get('consolePaused', false), logOffset = 0, logGeneration = 0, logSource = '';
  const consoleOutput = $('#console-output');
  function selectConsole(id) {
    selectedRun = id; logOffset = 0; logSource = ''; logGeneration++;
    if (!id) $('#console-parking').append($('#console-panel'));
    storage.set('console', id); $('#console-run').value = id;
    setText(consoleOutput, id ? '' : 'Choose a run to inspect its console.');
    $('#download-console').hidden = !id;
    $('#download-console').href = `/api/jobs/${encodeURIComponent(id)}/log?download=1`;
    setText($('#console-status'), consolePaused ? 'Display paused' : '');
  }
  function mountConsole(card) {
    const host = $('.console-host', card), panel = $('#console-panel');
    for (const other of getCards()) if (other !== card) $('.job-console', other).open = false;
    if (selectedRun !== card.dataset.id || $('#console-run').value !== card.dataset.id) selectConsole(card.dataset.id);
    if (panel.parentElement !== host) host.append(panel);
    refreshConsole().catch(error => setText($('#console-status'), error.message));
  }
  $('#console-run').addEventListener('change', event => selectConsole(event.target.value));
  function updatePause() {
    setText($('#pause-console'), consolePaused ? 'Resume updates' : 'Pause updates');
    $('#pause-console').setAttribute('aria-pressed', String(consolePaused));
    setText($('#console-status'), consolePaused ? 'Display paused' : '');
  }
  $('#pause-console').onclick = () => { consolePaused = !consolePaused; storage.set('consolePaused', consolePaused); updatePause(); };
  updatePause();
  $('#copy-console').onclick = async () => {
    try { await navigator.clipboard.writeText(consoleOutput.textContent); setText($('#console-status'), 'Visible log copied'); }
    catch { setText($('#console-status'), 'Copy unavailable. Select the log text or download the full log.'); }
  };
  async function refreshConsole() {
    if (!selectedRun || consolePaused || $('#runs').hidden || !$('#console-panel').closest('details[open]')) return;
    const id = selectedRun, generation = logGeneration;
    let result;
    try { result = await api(`/api/jobs/${encodeURIComponent(id)}/log?offset=${logOffset}&source=${encodeURIComponent(logSource)}`); }
    catch(error) {
      if(error.status===404 && selectedRun===id && generation===logGeneration) { selectConsole(''); setText($('#console-status'),'Previously selected run is no longer available.'); return; }
      throw error;
    }
    if (selectedRun !== id || generation !== logGeneration || consolePaused) return;
    const atBottom = consoleOutput.scrollTop + consoleOutput.clientHeight >= consoleOutput.scrollHeight - 30;
    const oldTop = consoleOutput.scrollTop;
    if (result.reset) setText(consoleOutput, '');
    if (result.text) {
      let combined = consoleOutput.textContent + result.text;
      let removedLines = 0;
      if (combined.length > 262144) {
        const excess = combined.length - 262144;
        const cut = combined.indexOf('\n', excess) + 1 || excess;
        removedLines = combined.slice(0, cut).split('\n').length - 1;
        combined = combined.slice(cut);
      }
      setText(consoleOutput, combined);
      if (atBottom) consoleOutput.scrollTop = consoleOutput.scrollHeight;
      else consoleOutput.scrollTop = Math.max(0, oldTop - removedLines * parseFloat(getComputedStyle(consoleOutput).lineHeight));
    }
    logOffset = result.offset; logSource = result.source || '';
    setText($('#console-status'), result.offset ? 'Console up to date' : 'No console output yet');
  }

  function detach() { $('#console-parking').append($('#console-panel')); logGeneration++; }

  return { get selectedRun() { return selectedRun; }, select: selectConsole, mount: mountConsole, refresh: refreshConsole, detach };
}
