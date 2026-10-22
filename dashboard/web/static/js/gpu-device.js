// The mdrun GPU device: one control, filled from the host's own answer, and the readiness note under it.
//
// The panel does not probe the host and does not restate the refusal. `GET /api/run/devices` is the one source
// for which devices exist (`devices.detect()`) and what is running on each (`devices.in_use()`), and an index
// this host does not have is refused where the run is built, not here. What this module adds is the
// measurement a reader cannot make themselves -- how many compute processes are already on the device they are
// choosing, and whether several ranks will share it -- and it is a note, never a gate: a busy device is a fact
// to see, not a reason to stop a run.
//
// The option text is `index - name - memory MiB`, because the index is what the run records and the name is
// what a reader recognises; a device whose memory the driver does not report (a MIG slice) states no memory
// rather than a zero.
import { api, setText } from './shared.js';

export function createGpuDevice({ select, note, ranks = () => 1, saved = () => undefined }) {
  let state = {devices: [], in_use: {}};

  const rankCount = () => Math.max(1, Number(ranks()) || 1);
  const chosen = () => Number(select.value);

  function paint() {
    if (!note) return;
    if (!state.devices.length) {
      setText(note, 'No GPU detected on this host; the command keeps device 0.');
      return;
    }
    const index = chosen();
    const busy = state.in_use[index] || 0;
    const parts = [];
    if (busy > 0) parts.push(`Device ${index} is already running ${busy} compute processes; mdrun will share it.`);
    if (rankCount() > 1) parts.push(`One device is shared by all ${rankCount()} ranks.`);
    setText(note, parts.join(' '));
  }

  function fill(wanted) {
    const indices = state.devices.map(device => String(device.index));
    select.replaceChildren(...(state.devices.length
      ? state.devices.map(device => new Option(
          [device.index, device.name, device.memory_mib == null ? '' : `${device.memory_mib} MiB`]
            .filter(part => part !== '' && part != null).join(' - '),
          String(device.index)))
      : [new Option('No GPU detected', '')]));
    select.disabled = !state.devices.length;
    const keep = String(wanted ?? '');
    select.value = indices.includes(keep) ? keep : (indices.includes('0') ? '0' : (indices[0] || ''));
    paint();
  }

  async function load() {
    let wanted = saved();
    if (wanted === undefined || wanted === null || wanted === '') wanted = select.value;
    try {
      const answer = await api('/api/run/devices');
      state = {devices: answer.devices || [], in_use: answer.in_use || {}};
    } catch (error) {
      // The host could not be asked. The form keeps a device control with nothing in it, the run keeps the
      // default device the command has always carried, and the note says which of those happened.
      state = {devices: [], in_use: {}};
      fill(wanted);
      setText(note, 'The GPU devices could not be read; the command keeps device 0.');
      return state;
    }
    fill(wanted);
    return state;
  }

  select.addEventListener('change', () => {
    paint();
    select.dispatchEvent(new Event('input', {bubbles: true}));
  });

  return {load, refresh: paint, state: () => state};
}
