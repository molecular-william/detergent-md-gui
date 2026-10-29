#!/bin/bash
set -euxo pipefail
AA_REFERENCE_DIR="${AA_REFERENCE_DIR:-../1_AA-reference/prod}"
# The run's own probe radius, as environment rather than a line prepended to a per-run copy of this script.
PROBE="${RUN_SETTING_SASA_PROBE_NM:-0.191}"
cd AA
printf 'System\n' | gmx sasa -f "${AA_REFERENCE_DIR:-../../1_AA-reference/prod}/lig.xtc" -s "${AA_REFERENCE_DIR:-../../1_AA-reference/prod}/lig.tpr" -ndots 4800 -probe "$PROBE" -o SASA-AA.xvg
cd ../CG
printf 'System\n' | gmx sasa -f ../../4_CG_sim/prod/lig_CG.xtc -s ../../4_CG_sim/prod/lig_CG.tpr -ndots 4800 -probe "$PROBE" -o SASA-CG.xvg
