#!/bin/bash
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
set -euxo pipefail
# GRO supplies ligand atom order/residue names; TPR 138 is unsupported by MDAnalysis 2.10.
# XTC positions are molecule-whole from GROMACS. ITP supplies interaction connectivity.
#
# One mapper. sugar_mapping.py computes heavy-atom COGs -- the definition `ff_map -mode COG` used, which the script
# that checked ff_map's output verified against the AA coordinates to 0 nm on every run it saw -- restores each
# frame's own time and box, refuses to overwrite an earlier mapping, and records what it did.
#
# The `ff_map` branch this replaces never executed. Across all 18 CG runs in this workspace `sugar_mapping.py` was
# present, so the test that used to select a branch always took this side, and no run ever wrote `mapped_raw.xtc`.
python sugar_mapping.py
