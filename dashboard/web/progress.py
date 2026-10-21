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
#: `nsteps` as the mdp states it.
NSTEPS = re.compile(r'^\s*nsteps\s*=\s*(\d+)\s*$', re.M | re.I)


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


def _leg_lengths(grompp, stage_dir):
    """`{leg name: nsteps}` for the legs whose mdp this reader can find and parse.

    A leg whose mdp is missing or unreadable is absent rather than zero: an unknown length is not a finished leg.
    """
    pairs = {}
    for line in grompp:
        mdp, tpr = MDP_PATH.search(line), TPR_PATH.search(line)
        if mdp and tpr:
            pairs[Path(tpr.group(1)).stem] = mdp.group(1)
    lengths = {}
    if stage_dir is None:
        return lengths
    for leg, mdp in pairs.items():
        try:
            found = NSTEPS.search((Path(stage_dir) / mdp).read_text())
        except OSError:
            continue
        if found:
            lengths[leg] = int(found.group(1))
    return lengths


def reading(stage_name, stage_dir, legs, grompp):
    """The progress record from a scanned log. `{}` when the stage declared no legs to count.

    `percent` is `None` when the stage has legs but none of them can be measured yet -- the first leg's first step has
    not printed, or no leg's mdp was readable. That is a state the panel states as "running", never as 0%: a bar at
    zero is indistinguishable from a bar that is not moving.
    """
    if not legs:
        return {}
    lengths = _leg_lengths(grompp, stage_dir)
    current, step = legs[-1]
    total = lengths.get(current)
    done = len(legs) - 1
    if step is not None and total:
        percent = round(100 * (done + min(1.0, step / total)) / len(legs))
    else:
        percent = round(100 * done / len(legs)) if done else None
    return {'stage': stage_name, 'leg': current, 'legs': len(legs), 'leg_index': len(legs),
            'step': step, 'steps': total, 'percent': percent,
            'measured': bool(step is not None and total)}


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
