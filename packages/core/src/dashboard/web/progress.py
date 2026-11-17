"""How far a running stage has got, for the stages a log can be counted rather than timed.

The runs a reader watches longest are the ones whose stages are **scripts**: `cg_simulation.sh` runs three mdrun legs
in a row (minimisation, equilibration, production), and `assess.sh` runs a tool that prints no step at all. GROMACS'
own "remaining wall clock time" is an estimate for *one* leg at a time, so on the first two legs of a three-leg stage
the run card has nothing to say, and the third says nothing about how much of the stage is left.

What a script log does carry is *structure*: each leg announces itself (`gmx mdrun -deffnm min`, then `eq`, then `md`),
and each leg's length is the `nsteps` of the mdp it was grompp'd from. Counting legs plus steps within the current leg
gives a fraction of the whole stage -- two of three legs done is 66%, and half of the third is 83% -- which is what a
progress bar needs and what GROMACS' ETA cannot provide.

The reader streams the file once rather than reading a tail: the leg markers stand at the *start* of legs, so on a long
production they are megabytes above the end, and a tail would see a step counter belonging to a leg it cannot name.
"""
import re
import threading
from pathlib import Path

#: A leg, as the stage script announces it. `-deffnm` is the leg's own name and the stem of its files.
LEG = re.compile(r'^\+ gmx mdrun\b.*?-deffnm\s+(\S+)')
#: The mdp a leg was built from, from the `grompp` line that built it: `-f <mdp>` and `-o <tpr>`.
GROMPP = re.compile(r'^\+ gmx grompp\b')
MDP_PATH = re.compile(r'-f\s+(\S+\.mdp)')
TPR_PATH = re.compile(r'-o\s+(\S+\.tpr)')
#: GROMACS' own step counter, one per line of the progress block.
STEP = re.compile(r'\bstep\s+(\d+)\b')
#: `nsteps` and `dt` as the mdp states them; the latter turns a step counter into simulated nanoseconds.
NSTEPS = re.compile(r'^\s*nsteps\s*=\s*(\d+)\s*$', re.M | re.I)
DT = re.compile(r'^\s*dt\s*=\s*([0-9.eE+-]+)\s*$', re.M | re.I)
#: Energy minimisation has no simulated time, so its `dt` must not be counted as nanoseconds.
INTEGRATOR = re.compile(r'^\s*integrator\s*=\s*([A-Za-z]+)\s*$', re.M | re.I)


def _chunks(line):
    """One physical line as its progress pieces: mdrun rewrites its block with `\\r`, not `\\n`."""
    return line.split('\r')


def scan(lines, *, legs=None, grompp=None):
    """(legs, grompp lines) from a stage log: `[[name, last step or None], ...]`, in the order the script ran them.

    `legs` and `grompp` may be passed an accumulator already holding an earlier part of the same log: the caller
    then feeds only the new lines and gets exactly the arrays a single pass over the whole file would have produced.
    """
    if legs is None:
        legs = []
    if grompp is None:
        grompp = []
    for line in lines:
        for chunk in _chunks(line):
            if chunk.startswith('+ gmx mdrun'):
                found = LEG.match(chunk)
                if found:
                    legs.append([found.group(1), None])
            elif GROMPP.match(chunk):
                grompp.append(chunk)
            elif legs:
                found = STEP.search(chunk)
                if found:
                    legs[-1][1] = int(found.group(1))
    return legs, grompp


def _leg_parameters(grompp, stage_dir):
    """`({leg name: nsteps}, {leg name: dt_ps})` for the legs whose mdp this reader can find and parse.

    A leg whose mdp is missing or unreadable is absent rather than zero: an unknown length is not a finished leg,
    and an unknown timestep cannot turn its step counter into simulated time.
    """
    pairs = {}
    for line in grompp:
        mdp, tpr = MDP_PATH.search(line), TPR_PATH.search(line)
        if mdp and tpr:
            # The leg is named by `-deffnm`, which may carry a directory (`-deffnm prod/run` in the extension stage), so the
            # key drops only the `.tpr` suffix: `Path(...).stem` would answer `run` and miss the leg it describes.
            pairs[tpr.group(1).removesuffix('.tpr')] = mdp.group(1)
    lengths, timesteps = {}, {}
    if stage_dir is None:
        return lengths, timesteps
    for leg, mdp in pairs.items():
        try:
            text = (Path(stage_dir) / mdp).read_text()
        except OSError:
            continue
        found = NSTEPS.search(text)
        if found:
            lengths[leg] = int(found.group(1))
        integrator = INTEGRATOR.search(text)
        if integrator and integrator.group(1).lower() in ('steep', 'cg'):
            timesteps[leg] = 0.0
            continue
        found = DT.search(text)
        if found:
            try:
                timesteps[leg] = float(found.group(1))
            except ValueError:
                pass
    return lengths, timesteps


def reading(stage_name, stage_dir, legs, grompp):
    """The progress record from a scanned log. `{}` when the stage declared no legs to count.

    `percent` is `None` when the stage has legs but none of them can be measured yet -- the first leg's first step has
    not printed, or no leg's mdp was readable. That is a state the panel states as "running", never as 0%: a bar at
    zero is indistinguishable from a bar that is not moving.
    """
    if not legs:
        return {}
    lengths, timesteps = _leg_parameters(grompp, stage_dir)
    current, step = legs[-1]
    total = lengths.get(current)
    done = len(legs) - 1
    if step is not None and total:
        percent = round(100 * (done + min(1.0, step / total)) / len(legs))
    else:
        percent = round(100 * done / len(legs)) if done else None
    ns_done = _ns_done(legs, lengths, timesteps)
    return {'stage': stage_name, 'leg': current, 'legs': len(legs), 'leg_index': len(legs),
            'step': step, 'steps': total, 'percent': percent, 'ns_done': ns_done,
            'measured': bool(step is not None and total)}


def _ns_done(legs, lengths, timesteps):
    """Simulated nanoseconds completed in the stage, or None when a leg's length or timestep is unknown.

    A leg followed by another one ran its mdp's full `nsteps`; the step counter may only have printed `step 0` before
    the next leg began. The current leg is counted by its latest printed step.
    """
    total = 0.0
    for index, (name, last_step) in enumerate(legs):
        dt = timesteps.get(name)
        if index == len(legs) - 1:
            steps = last_step if last_step is not None else 0
        else:
            steps = lengths.get(name)
        if dt is None or steps is None:
            return None
        total += steps * dt / 1000
    return round(total, 6)


class _Scan:
    """What one pass over a log has consumed: its identity, and the accumulator that pass produced.

    `offset` is the start of the first *incomplete* line -- bytes before it have been fed to `scan()`, and `pending`
    is the bytes from there to the end of the file. A reader that appends re-reads that one partial line with the new
    bytes, so a line split across two polls is still counted once and exactly as a full pass would count it.
    """
    __slots__ = ('inode', 'mtime_ns', 'size', 'offset', 'pending', 'legs', 'grompp')

    def __init__(self, inode, mtime_ns, size, offset, pending, legs, grompp):
        self.inode = inode
        self.mtime_ns = mtime_ns
        self.size = size
        self.offset = offset
        self.pending = pending
        self.legs = legs
        self.grompp = grompp


# A running log is appended while a reader polls it, and a stage log can be tens of megabytes: rescanning the whole
# file on every poll is what made one poll cost ~1 s. The state below is keyed by (resolved path, inode, mtime_ns,
# size) and only ever resumed when the same inode grew; anything else replaces the entry with a full rescan. The cap
# bounds a long-lived dashboard's memory and clearing wholesale is safe because each entry is a pure function of a
# file prefix. A global lock lets an incremental pass and the reading built from it be seen as one snapshot: no caller
# can observe the legs list between a new line being counted and the reading that reports it.
_SCAN_CACHE = {}
_SCAN_CACHE_MAX = 4096
_SCAN_LOCK = threading.Lock()


def _complete_lines(data, pending):
    """The lines `data` completes, decoded as text mode would; the trailing partial line is appended to `pending`.

    Text mode's universal newlines make `\\r`, `\\n` and `\\r\\n` all end a line and translate the ending to `\\n`,
    and its iterator still yields a final line with no newline. The parser's carriage-return handling depends on that
    translation, so doing it in bytes keeps an incremental pass byte-for-byte the file a full pass would read.
    Splitting at C speed matters here: a production log is millions of carriage-return progress lines.
    """
    parts = data.split(b'\n')
    if data.endswith(b'\n'):
        parts.pop()  # the split's trailing empty is the terminator, not a line
        pending.append(b'')
    else:
        tail = parts.pop() if parts else b''
        fragments = tail.split(b'\r')
        pending.append(fragments.pop())
        for fragment in fragments:
            yield fragment.decode('utf-8', errors='replace') + '\n'
    for part in parts:
        # A `\r\n` ending leaves one empty fragment here; an empty line changes nothing the parser counts.
        for fragment in (part.split(b'\r') if b'\r' in part else (part,)):
            yield fragment.decode('utf-8', errors='replace') + '\n'


def _complete_file_lines(handle, has_partial):
    """The file's lines with its trailing partial line withheld, so the cold scan feeds the same accumulator."""
    held = None
    for line in handle:
        if held is not None:
            yield held
        held = line
    if held is not None and not has_partial:
        yield held


def _trailing_bytes(path, size, block=65536):
    """`path`'s bytes after its last universal newline, read from the end rather than parsing the file again."""
    if size <= 0:
        return b''
    suffix = b''
    position = size
    with open(path, 'rb') as handle:
        while position > 0:
            start = max(0, position - block)
            handle.seek(start)
            data = handle.read(position - start) + suffix
            found = max(data.rfind(b'\n'), data.rfind(b'\r'))
            if found >= 0:
                return data[found + 1:]
            suffix = data
            position = start
    return suffix


def progress_from_file(stage_name, stage_dir, path):
    """Progress for a stage whose log is on disk. `{}` when the file cannot be read at all.

    Only bytes appended since the previous poll are parsed; a file that shrank, changed inode or vanished is scanned
    from zero again. `reading()` is still recomputed every call, so a changed mdp is seen even when the log is not.
    """
    path = Path(path)
    resolved = str(path.resolve())
    try:
        stat = path.stat()
    except OSError:
        with _SCAN_LOCK:
            _SCAN_CACHE.pop(resolved, None)
        return {}
    with _SCAN_LOCK:
        entry = _SCAN_CACHE.get(resolved)
        if (entry is not None and entry.inode == stat.st_ino
                and entry.size == stat.st_size and entry.mtime_ns == stat.st_mtime_ns):
            legs, grompp, pending = entry.legs, entry.grompp, entry.pending
        else:
            try:
                if (entry is not None and entry.inode == stat.st_ino
                        and stat.st_size >= entry.size and stat.st_mtime_ns >= entry.mtime_ns):
                    # The file only grew: parse its new tail into the accumulator we already have.
                    with open(resolved, 'rb') as handle:
                        handle.seek(entry.offset)
                        data = handle.read()
                    legs, grompp = entry.legs, entry.grompp
                    consumed = entry.offset
                    found = []
                    scan(_complete_lines(data, found), legs=legs, grompp=grompp)
                    pending = found[0]
                    consumed += len(data) - len(pending)
                    size = entry.offset + len(data)
                else:
                    # A cold scan streams the file in text mode, the way this reader always read it; only the trailing
                    # partial line's bytes are needed to resume later, and those are found from the end.
                    legs, grompp = [], []
                    pending = _trailing_bytes(resolved, stat.st_size)
                    with open(resolved, encoding='utf-8', errors='replace') as handle:
                        scan(_complete_file_lines(handle, bool(pending)), legs=legs, grompp=grompp)
                    consumed = stat.st_size - len(pending)
                    size = stat.st_size
                    if len(_SCAN_CACHE) >= _SCAN_CACHE_MAX:
                        _SCAN_CACHE.clear()
                _SCAN_CACHE[resolved] = _Scan(stat.st_ino, stat.st_mtime_ns, size,
                                              consumed, pending, legs, grompp)
            except OSError:
                _SCAN_CACHE.pop(resolved, None)
                return {}
        # The trailing partial line has not been fed to the accumulator (it may be completed by a later append), but a
        # full pass over the file as it stands now would yield it: apply it to a copy so the two readings agree.
        view_legs = [list(leg) for leg in legs]
        view_grompp = list(grompp)
        if pending:
            scan((pending.decode('utf-8', errors='replace'),), legs=view_legs, grompp=view_grompp)
        return reading(stage_name, stage_dir, view_legs, view_grompp)

