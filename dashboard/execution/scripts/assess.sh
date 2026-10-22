#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
# The two directories this stage reads, named rather than written into the command below, because a *re-score*
# (`dashboard/execution/assessment_rescore.py`) hands it a different pair: the run's own stage 3 for the initial ITP,
# and a later parameterization revision's histograms staged into its own attempt directory. A run as it executes
# passes neither, both default to stage 3, and nothing about that run changes.
#
# `INITIAL_DIR` is where the run's own initial ITP is read (`-i $INITIAL_DIR/$INITIAL_ITP`); `REFERENCES` is the
# directory the pairwise gate counts and the one `-d` is handed. They are separate variables because they answer
# separate questions, and a caller may hand the same directory to both.
INITIAL_DIR="${INITIAL_DIR:-../3_initial_CG}"
REFERENCES="${REFERENCES:-$INITIAL_DIR}"
set -euxo pipefail
# `ff_assess` does not measure the reference. It scores the CG trajectory against the AA reference's own histograms,
# which it reads out of `-d $REFERENCES` and never computes. A run that fits leaves them in `3_initial_CG` as a
# by-product of `ff_inter -dists -dist-matrix`; a run that consumes a model carries them in `distributions.json`, and
# stages them there; a re-score stages its revision's into its own attempt directory instead.
#
# What it scores *pairs* with is one `<resid>_<a>_<resid>_<b>_distances_distr.dat` per bead pair, and that family is
# the one whose absence is silent: `fast_forward/score.py` `continue`s past a pair whose reference file is missing and
# leaves the cell at its 0.00 default, so a run holding only bond and angle histograms prints a matrix of 0.00 -- a
# perfect score for a comparison that never happened. So this stage asks the directory it hands `-d` how many pair
# histograms are there, and a stage with none records that it had nothing to do (exit 4, reason in `skip.json`) instead
# of printing that matrix. The run carries on and says `skipped`: a score it cannot take is not a reason to discard the
# simulation.
shopt -s nullglob
PAIR_HISTOGRAMS=("$REFERENCES"/*_distances_distr.dat)
if [ ${#PAIR_HISTOGRAMS[@]} -eq 0 ]; then
    # The inventory lives beside the histograms it lists and beside the directory `-d` is handed: a stage-3 inventory
    # is read for the run's own words where they exist, and an inventory written before the pairwise family was
    # counted carries none for this case, so the count of what it did stage is said instead of nothing. A re-score's
    # own reference directory carries no such inventory -- it is not stage 3, and it was staged by the re-score --
    # so the reason names the directory it actually checked rather than claiming stage 3 wrote it.
    python - "$REFERENCES" "$INITIAL_DIR" <<'PY' > skip.json
import json
import sys
from pathlib import Path
references, initial = Path(sys.argv[1]), Path(sys.argv[2])
inventory = references / 'distributions.json'
if inventory.is_file():
    recorded = json.loads(inventory.read_text())
    staged = recorded.get('files') or []
    reason = recorded.get('reason') or (
        f"this run staged {len(staged)} AA reference histogram(s) and none of the pairwise distance histograms "
        '`ff_assess` scores (`<resid>_<a>_<resid>_<b>_distances_distr.dat`), so there is nothing to score it against'
        if staged else 'no pairwise AA reference histograms were staged to score this run against')
else:
    # Accurate whether or not the two directories differ: the run's own stage 3 where they are the same directory,
    # and the reference directory this assessment was handed where a re-score gave it another.
    where = ("this run's own stage 3" if references.resolve() == initial.resolve()
             else f'the reference directory this assessment was handed ({references})')
    reason = (f'{where} holds no pairwise reference histograms '
              '(`<resid>_<a>_<resid>_<b>_distances_distr.dat`), so the pairwise score has nothing to score this run '
              'against')
print(json.dumps({'reason': reason}))
PY
    exit 4
fi
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
# Use the annotated seed to keep reference group labels identical after fitting.
ff_assess -f ../4_CG_sim/prod/lig_CG.xtc -s ../4_CG_sim/prod/lig_CG.gro -i "$INITIAL_DIR/$INITIAL_ITP" -d "$REFERENCES" -plots -plot-data -dists
python validate_run.py
if [ -f distance_diagnostics.py ]; then python distance_diagnostics.py; fi
