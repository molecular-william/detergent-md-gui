#!/bin/bash
set -euxo pipefail
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
# The run's own probe radius, as environment rather than a line prepended to a per-run copy of this script.
PROBE="${RUN_SETTING_SASA_PROBE_NM:-0.191}"
# ponytail: 48 dots/atom (was 4800). Measured 2026-11-17: the trajectory mean and the AA-vs-CG comparison match within
# 0.1% for ~10-20x less time, at the cost of ~1% per-frame error, so frame-level spread is numerical noise here. Raise
# it if that spread becomes a decision input.
NDOTS=48
cd AA
printf 'System\n' | gmx sasa -f "${AA_REFERENCE_DIR:-../../1_AA-reference/prod}/lig.xtc" -s "${AA_REFERENCE_DIR:-../../1_AA-reference/prod}/lig.tpr" -ndots "$NDOTS" -probe "$PROBE" -o SASA-AA.xvg
cd ../CG
printf 'System\n' | gmx sasa -f ../../4_CG_sim/prod/lig_CG.xtc -s ../../4_CG_sim/prod/lig_CG.tpr -ndots "$NDOTS" -probe "$PROBE" -o SASA-CG.xvg
