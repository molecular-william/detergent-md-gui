#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
set -euxo pipefail
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
# Both helpers below are staged into every AA-to-CG run, so they are called rather than probed for with
# `[ -f ... ]`: a mapping with no rings has nothing to expand (`ring_targets.json` is absent and
# `prepare_ring_constraints.py` returns), and the refinement does nothing without a torsion model in the mapping
# (`bonded_options.torsion_model`, the mapping's own switch -- D4a). The file tests described a profile that
# staged no mapping at all, and that profile is gone. The `BOND_STATE.itp` path that used to short-circuit this
# script is gone with the run control that staged one: nothing hands a run a pre-fitted topology any more (D1).
python prepare_ring_constraints.py
gmx grompp -f initial.mdp -p topol.top -c ../2_mapping/mapped.gro -o mapped.tpr
# This bundled FF version has no -itp-only switch. Use the AA temperature, rounded: this version's
# -temperature argument is an int, and it feeds a Boltzmann inversion.
# `-constraints` is the fitted force constant above which ff_inter writes a bond as a constraint instead of a
# bond. FF's own default is 10000; this file used to pass 1000000000, which disables the conversion for every
# bond -- so the DDM link FF fitted at k=12964.8 stayed harmonic at a 20 fs timestep and the run died at ~200 ps
# (ring arms 860eb013a82c and e08dc53410f9). Keep FF's own default.
ff_inter -f ../2_mapping/mapped.xtc -s ../2_mapping/mapped.gro -i $INITIAL_ITP -temperature 300 -constraints 10000 -dists -plots -dist-matrix
python refine_bonded.py
