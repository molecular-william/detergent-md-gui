#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
set -euxo pipefail
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
if [ -f sugar_mapping.py ]; then
    python sugar_mapping.py
else
ff_map -f "${AA_REFERENCE_DIR:-../1_AA-reference/prod}/lig.xtc" -s "${AA_REFERENCE_DIR:-../1_AA-reference/prod}/lig.gro" -m mapping.map -o mapped_raw.xtc -mols LIG1 -mode COG
python finalize_mapping.py
fi
