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


def scan(lines):
    """(legs, grompp lines) from a stage log: `[[name, last step or None], ...]`, in the order the script ran them."""
    legs, grompp = [], []
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


def progress_from_file(stage_name, stage_dir, path):
    """Progress for a stage whose log is on disk. `{}` when the file cannot be read at all."""
    try:
        with open(path, errors='replace') as handle:
            legs, grompp = scan(handle)
    except OSError:
        return {}
    return reading(stage_name, stage_dir, legs, grompp)


def progress_from_log(stage_name, stage_dir, text):
    """Progress for a log already in hand, as one string."""
    legs, grompp = scan(text.splitlines())
    return reading(stage_name, stage_dir, legs, grompp)
