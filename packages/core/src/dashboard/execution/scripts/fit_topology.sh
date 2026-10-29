#!/bin/bash
set -euxo pipefail
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
# The interpreter the application runs under, and the checkout it imports from. A stage runs with the stage directory
# as its working directory, so the two helpers are repository modules reached through `-m`, not files beside the
# script: the run records their paths and digests instead of carrying copies.
PYTHON="${PYTHON:-python}"
REPO_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
# The ring pass runs for every mapping: a mapping with no rings has nothing to expand (`ring_targets.json` is absent
# and `prepare_ring_constraints.py` returns), and the refinement does nothing without a torsion model in the mapping
# (`bonded_options.torsion_model`, the mapping's own switch -- D4a). The `BOND_STATE.itp` path that used to
# short-circuit this script is gone with the run control that staged one: nothing hands a run a pre-fitted topology
# any more (D1).
"$PYTHON" -m dashboard.execution.scripts.prepare_ring_constraints
gmx grompp -f initial.mdp -p topol.top -c ../2_mapping/mapped.gro -o mapped.tpr
# This bundled FF version has no -itp-only switch. Use the AA temperature, rounded: this version's
# -temperature argument is an int, and it feeds a Boltzmann inversion, so a fractional run temperature (303.15 K)
# is rounded for this one argument while the manifest and the MDPs keep the value as written. The number is the
# run's own setting, arriving as environment: this file is the same file for every run.
FIT_TEMPERATURE=$(printf '%.0f' "${RUN_SETTING_TEMPERATURE_K:-300}")
# `-constraints` is the fitted force constant above which ff_inter writes a bond as a constraint instead of a
# bond. FF's own default is 10000; this file used to pass 1000000000, which disables the conversion for every
# bond -- so the DDM link FF fitted at k=12964.8 stayed harmonic at a 20 fs timestep and the run died at ~200 ps
# (ring arms 860eb013a82c and e08dc53410f9). Keep FF's own default.
ff_inter -f ../2_mapping/mapped.xtc -s ../2_mapping/mapped.gro -i "$INITIAL_ITP" -temperature "$FIT_TEMPERATURE" -constraints 10000 -dists -plots -dist-matrix
"$PYTHON" -m dashboard.execution.scripts.refine_bonded
