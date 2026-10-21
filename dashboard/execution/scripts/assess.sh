#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
set -euxo pipefail
# `ff_assess` does not measure the reference. It scores the CG trajectory against the AA reference's own histograms,
# which `ff_assess` reads out of `-d ../3_initial_CG` and never computes. A run that fits leaves them there as a
# by-product of `refine_bonded`; a run that consumes a model carries them in `distributions.json`. When that inventory is
# empty -- BARTENDER measures none, and its own analysis is unbuilt (D6a) -- there is nothing to score, so this stage
# records that it had nothing to do (exit 4, reason in `skip.json`) rather than averaging no interactions into `nan` or
# scoring every unbaselined distance 0.00. The run carries on and says `skipped`.
if [ -f distributions.json ] && ! python -c 'import json,sys; sys.exit(0 if (json.load(open("distributions.json")).get("files") or []) else 1)'; then
    python -c 'import json; print(json.dumps({"reason": json.load(open("distributions.json")).get("reason") or "no AA reference histograms to score this run against"}))' > skip.json
    exit 4
fi
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
# Use the annotated seed to keep reference group labels identical after fitting.
ff_assess -f ../4_CG_sim/prod/lig_CG.xtc -s ../4_CG_sim/prod/lig_CG.gro -i ../3_initial_CG/$INITIAL_ITP -d ../3_initial_CG -plots -plot-data -dists
python validate_run.py
if [ -f distance_diagnostics.py ]; then python distance_diagnostics.py; fi
