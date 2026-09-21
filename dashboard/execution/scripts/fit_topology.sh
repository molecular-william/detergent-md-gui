#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
set -euxo pipefail
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
if [ -f prepare_ring_constraints.py ]; then python prepare_ring_constraints.py; fi
if [ -f BOND_STATE.itp ]; then
  cp BOND_STATE.itp $FINAL_ITP
  gmx grompp -f initial.mdp -p topol.top -c ../2_mapping/mapped.gro -o mapped.tpr
  test -n "$(find . -maxdepth 1 -name '*_distr.dat' -size +0c -print -quit)"
  exit 0
fi
gmx grompp -f initial.mdp -p topol.top -c ../2_mapping/mapped.gro -o mapped.tpr
# This bundled FF version has no -itp-only switch. Explicitly use the AA temperature.
ff_inter -f ../2_mapping/mapped.xtc -s ../2_mapping/mapped.gro -i $INITIAL_ITP -temperature 300 -constraints 1000000000 -dists -plots -dist-matrix
if [ -f refine_bonded.py ]; then python refine_bonded.py; fi
