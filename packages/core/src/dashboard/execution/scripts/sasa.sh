#!/bin/bash
set -euxo pipefail
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
# The run's own probe radius, as environment rather than a line prepended to a per-run copy of this script.
PROBE="${RUN_SETTING_SASA_PROBE_NM:-0.191}"
# ponytail: 48 dots/atom (was 4800). Measured 2026-11-17: the trajectory mean and the AA-vs-CG comparison match within
# 0.1% for ~10-20x less time, at the cost of ~1% per-frame error, so frame-level spread is numerical noise here. Raise
# it if that spread becomes a decision input.
NDOTS=48
# GROMACS looks the radii up as `vdwradii.dat` in the working directory, so the published AA table is copied into the
# AA stage directory here, at run time. The prepared run keeps no copy of it: layout 4 names the published repository
# file as its `sasa_radii_aa` input. Without this the AA pass silently guesses radii from atom names, which shifts the
# AA surface ~2% and breaks the AA-vs-CG comparison the stage exists to publish.
REPO_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
cd AA
cp "$REPO_ROOT/resources/templates/small_mols_fast_forward/5_SASA/vdwradii_AA.dat" vdwradii.dat
printf 'System\n' | gmx sasa -f "${AA_REFERENCE_DIR:-../../1_AA-reference/prod}/lig.xtc" -s "${AA_REFERENCE_DIR:-../../1_AA-reference/prod}/lig.tpr" -ndots "$NDOTS" -probe "$PROBE" -o SASA-AA.xvg
cd ../CG
printf 'System\n' | gmx sasa -f ../../4_CG_sim/prod/lig_CG.xtc -s ../../4_CG_sim/prod/lig_CG.tpr -ndots "$NDOTS" -probe "$PROBE" -o SASA-CG.xvg
