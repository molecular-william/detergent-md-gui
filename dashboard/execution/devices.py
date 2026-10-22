"""The GPUs this host offers mdrun, and the record a run keeps of the one it used.

Nothing here decides *which* device a run uses -- `mdrun_gpu` does, and the one builder that writes
the flag reads it (`adapters/aa.py:mdrun_command_flags`). This module answers three questions
about the host: which devices exist, how many compute processes are on each right now, and what the
record for one index says. The panel, the refusal at prepare and a run's own metadata then answer
from the same reading rather than from a second probe of their own.

Every answer has an honest empty form -- no `nvidia-smi`, no devices, nothing running -- and none of
them raises. A host without a GPU is a host whose runs must not be refused for it: the command these
runs produce has always named a device, and mdrun is the thing that speaks when one is asked for and
cannot be had. What *is* refused is naming a device this host reported and does not have, and that
refusal belongs at prepare (`require`), where a run that would have failed three stages in is not yet
built.
"""
import shutil
import subprocess
import time

from .environment import environment

#: The tool, resolved on the search path. Absent on a CPU-only host, which is an answer and not an error.
BINARY = 'nvidia-smi'
DEVICE_QUERY = ('--query-gpu=index,name,memory.total,uuid', '--format=csv,noheader,nounits')
#: `gpu_uuid,pid,process_name`: the UUID is what ties a process to the device `detect` reported, and the
#: process name is free text, so it is read last and never split further.
PROCESS_QUERY = ('--query-compute-apps=gpu_uuid,pid,process_name', '--format=csv,noheader')
#: New run asks once per page load and a run's prepare asks once; the device list does not change under
#: either of them. `in_use` is deliberately *not* cached: it is a statement about this instant.
CACHE_SECONDS = 30
_CACHE = {}


def _executable():
    """The probe, or None when this host does not have one."""
    return shutil.which(BINARY)


def _run(arguments, timeout):
    """The text one query answers with, or None when it cannot be asked at all.

    The caller's environment is not inherited as-is: `environment()` is the one the stage probes use, and
    it drops the interpreter variables a wrapper sets for its own reasons (`PYTHONPATH`, `PYTHONHOME`).
    A query that fails, times out or exits non-zero is None rather than an exception -- the caller's next
    question is still worth answering.
    """
    executable = _executable()
    if not executable:
        return None
    try:
        answer = subprocess.run([executable, *arguments], capture_output=True, text=True,
                                timeout=timeout, env=environment())
    except (OSError, subprocess.SubprocessError):
        return None
    return answer.stdout if answer.returncode == 0 else None


def _lines(text):
    return [line.strip() for line in (text or '').splitlines() if line.strip()]


def _device(line):
    """One device record from one line, or None when the line is not that.

    `memory.total` and the UUID are the last two fields and the name is free text that may itself carry a
    comma, so the split is from the right: index, name on the front; memory, uuid on the back. A line whose
    index is not a number, or that carries no UUID, is skipped rather than raising -- one unreadable row is
    one device nobody can address, not a probe that failed.
    """
    try:
        head, memory, uuid = line.rsplit(',', 2)
        index_text, name = head.split(',', 1)
        index = int(index_text.strip())
    except ValueError:
        return None
    uuid = uuid.strip()
    if not uuid:
        return None
    memory = memory.strip()
    if memory.lower() in ('n/a', '[n/a]'):
        # A MIG device reports no total. It is real and selectable; its memory is simply not a number.
        memory_mib = None
    else:
        try:
            memory_mib = int(float(memory))
        except ValueError:
            return None
    return {'index': index, 'name': name.strip(), 'memory_mib': memory_mib, 'uuid': uuid}


def clear_cache():
    """Forget the remembered device list: a test's seam, and what an operator asks for after changing a host."""
    _CACHE.clear()


def detect(timeout=10):
    """`[{'index', 'name', 'memory_mib', 'uuid'}]` for the devices this host reports.

    `[]` is an answer, not an error: a host without a GPU (or without `nvidia-smi`) is a host whose runs
    must not be told which device to use. The panel offers no device then, and a run that names none keeps
    the default device the command has always carried.
    """
    now = time.monotonic()
    remembered = _CACHE.get('devices')
    if remembered and remembered[0] > now:
        return [dict(device) for device in remembered[1]]
    found = [record for record in (_device(line) for line in _lines(_run(DEVICE_QUERY, timeout)))
             if record is not None]
    _CACHE['devices'] = (now + CACHE_SECONDS, found)
    return [dict(device) for device in found]


def in_use(timeout=10):
    """`{device index: compute process count}` for the devices that have one.

    Mapped through the UUIDs `detect()` returned, so a process on a device this host no longer reports is
    skipped rather than counted against an index that means something else. `{}` when nothing is running or
    nothing can be asked -- the readiness note says "none reported" rather than "idle", because a device with
    no processes at this instant is not a device that will be free when mdrun starts.
    """
    known = {device['uuid']: device['index'] for device in detect(timeout)}
    counts = {}
    for line in _lines(_run(PROCESS_QUERY, timeout)):
        parts = line.rsplit(',', 2)
        if len(parts) != 3:
            continue
        uuid = parts[0].strip()
        index = known.get(uuid)
        if index is None:
            continue
        counts[index] = counts.get(index, 0) + 1
    return counts


def describe(index, timeout=10):
    """The record for one device index, or None when this host does not report it."""
    try:
        wanted = int(index)
    except (TypeError, ValueError):
        return None
    return next((device for device in detect(timeout) if device['index'] == wanted), None)


def usage(index, timeout=10):
    """What a run's stage records about the device it used.

    The one shape both the manifest and a reader compare: the index the run chose, the name and UUID the host
    reported for it, and the compute processes measured now. A host that reported no devices leaves the name
    and UUID empty rather than inventing them -- the index is still what the command was written with.
    """
    record = describe(index, timeout) or {}
    return {'index': int(index), 'name': record.get('name'), 'uuid': record.get('uuid'),
            'compute_processes': in_use(timeout).get(int(index), 0)}


def environment_record(environment=None):
    """`environment` with this host's devices recorded beside it -- the form a prepared manifest keeps.

    Every device present is recorded, not only the chosen one, so a report written later can still say what
    the host had when the run was prepared.
    """
    return {**(environment or {}), 'devices': detect()}


def require(index):
    """The device a run asked for, or a `ValueError` naming the ones this host has.

    A host that reports no devices is **not** a refusal: headless and CPU-only hosts exist, the command
    already assumed a GPU before this setting did, and mdrun is the thing that says so if it cannot run.
    What is refused is naming a device the host reported and does not have -- before the run is prepared
    rather than three stages in.
    """
    try:
        wanted = int(index)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'mdrun_gpu must be a device index, not {index!r}') from exc
    found = detect()
    if not found:
        return None
    match = next((device for device in found if device['index'] == wanted), None)
    if match is None:
        available = ', '.join(f"{device['index']} ({device['name']})" for device in found)
        raise ValueError(f'GPU {wanted} is not present on this host; available: {available}')
    return match
