#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
set -euxo pipefail
# The interpreter the application runs under, and the checkout it imports from. A stage runs with the stage directory
# as its working directory, so the two helpers are repository modules reached through `-m`, not files beside the
# script: the run records their paths and digests instead of carrying copies.
PYTHON="${PYTHON:-python}"
REPO_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
#
# Stage 3 of a run that consumes its CG model's own parameterization (D5 of
# docs/design/2026-10-16-parameterization-and-new-run.md). Nothing here fits anything: the terms are
# `parameterization.json`, the mapping's current revision, staged by the run's prepare. The fit path
# is `fit_topology.sh`, which this script replaces for such a run -- and a script named for fitting
# must not be the one that pretends to have fitted.
#
# The ring pass stays, because it belongs to the mapping and not to the fit: `ring_targets.json` is
# the mapper's own AA-derived constraint lengths, and `prepare_ring_constraints.py` returns without
# touching anything when the mapping has no rings. `gmx grompp` then builds `mapped.tpr` from the
# same seeded topology the fit path builds it from -- the model's own terms are not in that tpr in
# either case, so nothing about this stage's inputs changes with the model.
"$PYTHON" -m dashboard.execution.scripts.use_parameterization
"$PYTHON" -m dashboard.execution.scripts.prepare_ring_constraints
gmx grompp -f initial.mdp -p topol.top -c ../2_mapping/mapped.gro -o mapped.tpr
