# Choosing the mdrun GPU device, and recording which one ran

> **For Hermes:** one new module, a setting in four adapters, one route, one control in New run. Tests fail on today's
> code because the device is a literal. Draft: `docs/design/drafts/new-run-mdrun-and-placement.html`.

**Goal:** every run type can name the GPU its mdrun uses, the choice is validated against the devices that actually
exist on this host, and the device's name is in the run's metadata and visible in the panel.

**Measured state (2026-10-21):**

* The device is hard-coded in two places. `dashboard/execution/adapters/aa.py:41-42`:
  `MDRUN_GPU_NONBONDED_FLAGS = '-gpu_id 0 -nb gpu -pin on'` and `MDRUN_GPU_PME_FLAGS = f'{…} -pme gpu -pmefft gpu'`.
  `dashboard/execution/adapters/pdc.py:524` (the generated `mdrun` line in `pdc_assessment.sh`'s catalogue):
  `${MDRUN_LAUNCHER:-}gmx mdrun -deffnm system ${MDRUN_FLAGS:--ntomp 8 -gpu_id 0 -nb gpu -pin on} -v`.
* `aa.mdrun_command_flags(settings, stage, flavour)` is the one place the flag set is built; `workflow.py:329-342`
  calls it per stage and passes the result as `MDRUN_LAUNCHER` / `MDRUN_FLAGS` in the stage environment, which is what
  the `pdc` scripts consume. `pdc` and `osmotic` therefore inherit the AA half's flags — one literal to change, not
  four, as long as the setting reaches `workflow.py`.
* `workflow.py:332` records `resource_usage = {wall_seconds, openmp_threads, mpi_ranks, gromacs_flavour,
  output_bytes}` — no device, so a run report cannot say which GPU it used.
* Threads and rank count are already settings with specs (`mdrun_ntomp`, `mdrun_ranks`,
  `SETTING_SPECS` in `aa.py:181-187`, `osmotic.py:254`); the device belongs beside them.
* GROMACS here is the MPI-only build (`/usr/local/gromacs/2026.3/bin/gmx`): `-gpu_id` is accepted and names the device
  per rank; `-ntmpi` is not (the manifest records `gromacs_flavour` for exactly this reason).

---

### Task 1: ask the host which devices exist (`dashboard/execution/devices.py`)

```python
"""The GPUs this host offers mdrun, and the record a run keeps of the one it used."""
import subprocess, shutil

QUERY = 'index,name,uuid,memory.total'

def detect(timeout=20) -> list[dict]:
    """[{'index': 0, 'name': 'NVIDIA GeForce RTX 4090', 'uuid': 'GPU-…', 'memory_mib': 24564}, …]

    `[]` is an answer, not an error: a host without a GPU (or without `nvidia-smi`) is a host whose runs must not be
    told to use one. The panel offers no device then, and a run asking for one is refused with the sentence below
    rather than by mdrun three stages later.
    """
```

Rules: parse `nvidia-smi --query-gpu=index,name,uuid,memory.total --format=csv,noheader,nounits`, split on commas
(the name itself may contain one, so split from the right: `index, name, uuid, memory`), and cache the result per
process for 30 s — New run asks once per page load, and a run's prepare asks once.

```python
def in_use(timeout=10) -> dict[int, int]:
    """{device index: compute process count} for the devices that have one.

    `nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name --format=csv,noheader`, mapped through the UUIDs
    `detect()` returned. `{}` when nothing is running or nothing can be asked -- the readiness note says "none
    reported" rather than "idle", because a device with no processes at this instant is not a device that will be free
    when mdrun starts.
    """
```

**Test:** `tests/dashboard/unit/test_devices.py` feeds a recorded `nvidia-smi` line and a two-GPU line; a missing
binary returns `[]`; a line that does not parse is skipped, not raised; `in_use` maps a UUID to its index and ignores a
process on a device that is not in `detect()`.

**Commit** `feat(execution): the host's GPU devices, as a record`.

---

### Task 2: the setting, validated before the run exists

**Files:** `dashboard/execution/adapters/aa.py` (specs + flags), `pdc.py` (script default), `cg.py`/`osmotic.py` (specs
inherit or restate), `tests/dashboard/unit/test_aa_settings.py` (or the existing settings test file).

**Step 1 — the failing test.**

```python
def test_the_chosen_device_reaches_the_command():
    launcher, flags = aa.mdrun_command_flags({'mdrun_gpu': 1, 'mdrun_ntomp': 8, 'mdrun_ranks': 1}, 'nvt')
    assert '-gpu_id 1' in flags and '-gpu_id 0' not in flags
```

**Step 2 — the flag.** In `aa.py`, build the bracket from the setting instead of the literal:

```python
def _gpu_flags(settings) -> str:
    choice = settings.get('mdrun_gpu', 0)
    return ' -nb gpu -pin on' if choice in (None, 'auto') else f'-gpu_id {int(choice)} -nb gpu -pin on'

MDRUN_GPU_NONBONDED_FLAGS = _gpu_flags({'mdrun_gpu': 0})   # kept for the callers that read the constant
```

Careful: the constant is read by `pdc.py`'s script default and by `workflow.py`; the *command* path must use the
setting. Leave the constants as the default (device 0, byte-identical to today) and thread the setting through
`mdrun_command_flags`.

**Step 3 — validation.** `mdrun_gpu` is integral, `>= 0`, default `0`. At prepare (both the generated-command path and
the script path) check it against `devices.detect()`: an index that is not present is refused with the sentence
`f'GPU {index} is not present on this host; available: 0 (NVIDIA GeForce RTX 4090), 1 (…)`. No device detected and a
non-zero index asked for is the same refusal with `available: none`. `0` with no devices keeps today's behaviour (the
`-gpu_id 0 -nb gpu` bracket), because that is what every existing run does and changing it would silently move the work
to the CPU.

**Step 4 — the pdc script** loses its literal: `${MDRUN_FLAGS:--ntomp 8}` only, since `workflow.py` always sets
`MDRUN_FLAGS`. Its `default` is then the no-GPU case rather than a second opinion about the device.

**Step 5 — run** the AA/CG/pdc stage-command tests (`-k "mdrun or flags or command"`), then fast tier.

**Commit** `feat(execution): mdrun's device is a setting, not a literal`.

---

### Task 3: metadata — the device name travels with the run

**Files:** `dashboard/execution/workflow.py:329-350`; the manifest writer (`execution/manifest.py` or wherever
`environment` is assembled); `tests/dashboard/unit/test_workflow_metadata.py`.

* At prepare, once per run: `environment['devices'] = devices.detect()` — every device present, so a report written
  later can still say what the host had.
* Per stage, in `resource_usage`: `'gpu': {'index': …, 'name': …, 'uuid': …}` taken from the chosen setting resolved
  against that list, or `None` when the run asked for none.
* The run report (`analysis/runs/observability.py`) surfaces `environment.devices[chosen]` as `gpu_name`, so the Runs
  table and the run view can show it without parsing flags.

**Test:** a stubbed `devices.detect()` of two devices, `mdrun_gpu = 1`, one stage run → the manifest's `resource_usage`
carries device 1's name and `environment.devices` carries both; a run with the setting absent records device 0 and says
so.

**Commit** `feat(execution): a run records which GPU it used`.

---

### Task 4: the control in New run

Both workspaces' New run panels (`dashboard/web/templates/dashboard.html` run form, `new-run.js`) gain, in the
execution row beside threads and ranks:

```html
<label>GPU device<select id="run-gpu-device" aria-describedby="run-gpu-note"></select>
  <span class="hint" id="run-gpu-note"></span></label>
```

* Source: `GET /api/run/devices` → `{devices: [{index, name, memory_mib}], default: 0}`. The panel does not probe the
  host and does not restate the validation — the same rule as the mapping pickers reading `validation.can_reuse`.
* Options: `0 · NVIDIA GeForce RTX 4090 · 24 GB` one per device; when the list is empty the select is replaced by the
  sentence "No GPU detected; mdrun will not be told which device to use."
* The chosen name is shown in the run's summary card once the run exists (from the manifest, not from the form).
* **A readiness note, not a gate.** Under the select, when `devices.in_use()` reports processes on the chosen device:
  "Device 1 is already running 2 compute processes; mdrun will share it." Same for `mdrun_ranks > 1` with a single
  device: "one device is shared by all 3 ranks". Both are checks that are recorded (`environment.devices[].compute_processes`)
  and shown, never a refusal — the project's record-and-warn rule, and the honest form of the convenience `auto` would
  have promised without measuring anything.

**Browser test:** stub `/api/run/devices` with two devices, assert both options and that the posted settings carry
`mdrun_gpu: 1` (the existing create-path tests already intercept the POST body).

**Commit** `feat(new-run): the GPU device is a choice, and the panel names it`.

---

### Acceptance

* `mdrun_gpu = 1` produces `-gpu_id 1` in the AA stages, in the CG stages and in the `pdc` scripts' environment.
* An index that does not exist is refused at prepare with a sentence naming the devices present, not by mdrun.
* Every run's manifest carries `environment.devices` and `resource_usage.gpu`; the run view shows the device name.
* With the setting untouched, the generated command is byte-for-byte what it was before this change (device 0).
* Fast tier, browser tier and the stage-command tests green.

**Decisions recorded (2026-10-21, by the user):**

1. **`0` remains the default**, not `auto`: `auto` would let GROMACS choose a different device than the one every
   existing run used, and the point is to make the device visible and choosable, not to move work silently.
2. **Readiness instead of auto-selection.** The convenience `auto` seems to offer — "give me a free device" — is served
   by a note that reports what is running on the chosen device, measured at the moment it is shown. Resolving `auto` to
   the emptiest device at prepare was considered and rejected: the answer can be stale by the time mdrun starts, and two
   runs preparing together resolve to the same device. A guess with a name attached is worse than a default with one.
3. **A single index for now.** `-gpu_id 0,1` (a list, spread over ranks) is a follow-up; today the setting takes one
   index and the panel states when several ranks will share it.
