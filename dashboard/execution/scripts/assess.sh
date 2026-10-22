#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
set -euxo pipefail
# `ff_assess` does not measure the reference. It scores the CG trajectory against the AA reference's own histograms,
# which it reads out of `-d ../3_initial_CG` and never computes. A run that fits leaves them there as a by-product of
# `ff_inter -dists -dist-matrix`; a run that consumes a model carries them in `distributions.json`.
#
# What it scores *pairs* with is one `<resid>_<a>_<resid>_<b>_distances_distr.dat` per bead pair, and that family is
# the one whose absence is silent: `fast_forward/score.py` `continue`s past a pair whose reference file is missing and
# leaves the cell at its 0.00 default, so a run holding only bond and angle histograms prints a matrix of 0.00 -- a
# perfect score for a comparison that never happened. So this stage asks the directory it hands `-d` how many pair
# histograms are there, and a stage with none records that it had nothing to do (exit 4, reason in `skip.json`) instead
# of printing that matrix. The run carries on and says `skipped`: a score it cannot take is not a reason to discard the
# simulation.
shopt -s nullglob
PAIR_HISTOGRAMS=(../3_initial_CG/*_distances_distr.dat)
if [ ${#PAIR_HISTOGRAMS[@]} -eq 0 ]; then
    # The inventory lives in stage 3, beside the histograms it lists and beside the directory `-d` is handed: an
    # inventory read from this stage's own directory is one a run never writes, so the reason would never be reachable.
    # It is read for the run's own words where they exist; an inventory written before the pairwise family was counted
    # carries none for this case, so the count of what it did stage is said instead of nothing.
    python - <<'PY' > skip.json
import json
from pathlib import Path
inventory = Path('../3_initial_CG/distributions.json')
if inventory.is_file():
    recorded = json.loads(inventory.read_text())
    staged = recorded.get('files') or []
    reason = recorded.get('reason') or (
        f"this run staged {len(staged)} AA reference histogram(s) and none of the pairwise distance histograms "
        '`ff_assess` scores (`<resid>_<a>_<resid>_<b>_distances_distr.dat`), so there is nothing to score it against'
        if staged else 'no pairwise AA reference histograms were staged to score this run against')
else:
    reason = ('stage 3 wrote no pairwise reference histograms '
              '(`<resid>_<a>_<resid>_<b>_distances_distr.dat`), so the pairwise score has nothing to score this run '
              'against')
print(json.dumps({'reason': reason}))
PY
    exit 4
fi
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
# Use the annotated seed to keep reference group labels identical after fitting.
ff_assess -f ../4_CG_sim/prod/lig_CG.xtc -s ../4_CG_sim/prod/lig_CG.gro -i ../3_initial_CG/$INITIAL_ITP -d ../3_initial_CG -plots -plot-data -dists
python validate_run.py
if [ -f distance_diagnostics.py ]; then python distance_diagnostics.py; fi
