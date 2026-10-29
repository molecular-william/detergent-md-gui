#!/bin/bash
# One equilibration leg of a protein-detergent complex run: energy minimisation (03), NVT (04), or NPT (05).
#
# Shared by the three legs and recorded in `stage_scripts` by path and digest; the stage directory it is run in names
# the leg, and `inputs/<that directory>.json` carries the run's own numbers for it -- its mdp, the phase whose system
# it copies in, whether its opening act is solvation, and the checkpoint it continues from. The physics is the
# template mdp's, untouched except for the run's step count and (NVT) its velocity seed.
#
# The mdrun budget, the device and the scheme choices arrive as environment -- MDRUN_LAUNCHER is an mpirun prefix or
# empty, MDRUN_FLAGS the flags -- because this stage is a script rather than a generated command. No -ntmpi appears in
# the executed lines: this host's `gmx` is an MPI-only build where that flag aborts mdrun before the first step, while
# -ntomp is valid for every build.
set -euxo pipefail

# The interpreter the application runs under, and the repository it imports from. `python` on the stage PATH is this
# workspace's virtualenv (`tools.search_path` puts it first); a caller that exports PYTHON/PROJECT_ROOT wins.
PYTHON="${PYTHON:-python}"
REPO_ROOT="${PROJECT_ROOT:-$("$PYTHON" -c 'from dashboard import paths; print(paths.PROJECT_ROOT)')}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

STAGE=$(basename "$(pwd)")
LEG="../../inputs/${STAGE}.json"
field() {
  "$PYTHON" -c 'import json,sys;value=json.load(open(sys.argv[1]))[sys.argv[2]];print("" if value is None else value)' \
    "$LEG" "$1"
}
setting() {
  "$PYTHON" -c 'import json,sys
value = json.load(open(sys.argv[1]))
for key in sys.argv[2].split("."):
    value = value[key]
print(value)' ../../inputs/pdc-settings.json "$1"
}

MDP=$(field mdp)
FROM=$(field from)

# The phase before this one stays immutable, so its system is copied in rather than edited where it lies. Only the
# writable working copy moves -- this leg solvates and rewrites `system.top`. The topology it copies names the
# detergent's, the protein's `cg/` tree and the installed Martini 3 set where they already are, by paths relative to
# this stage, so no stage copies any of them.
cp -f "$FROM/system.gro" "$FROM/system.top" .
cp -f "../../inputs/$MDP" .

# The checkpoint the leg before this one left, when it left one: those are the velocities the thermostat equilibrated.
CHECKPOINT_FILE=$(field checkpoint)
CHECKPOINT=""
if [ -n "$CHECKPOINT_FILE" ] && [ -f "$CHECKPOINT_FILE" ]; then CHECKPOINT="-t $CHECKPOINT_FILE"; fi

if [ "$(field solvate)" = "True" ]; then
  # The built system is dry, so solvation and ions are this leg's opening act -- through `pdc_solvation`, the tested
  # place that decides the water bead radius, the ion names and the group genion may replace.
  cp -f ../../inputs/ions.mdp .
  mkdir -p inputs
  cp -f ../../inputs/water.gro inputs/water.gro
  "$PYTHON" -m detergent_pdc.execution.scripts.pdc_solvate --topology system.top --structure system.gro \
    --salt-molar "$(setting salt_molar)"
fi

gmx grompp -f "$MDP" -p system.top -c system.gro $CHECKPOINT -o system.tpr -maxwarn 1
${MDRUN_LAUNCHER:-}gmx mdrun -deffnm system ${MDRUN_FLAGS:--ntomp 8} -v
