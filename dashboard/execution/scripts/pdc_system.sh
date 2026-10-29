#!/bin/bash
# System preparation for a protein-detergent complex run: the box, the placement, and the report.
#
# Shared by every run: the adapter records this file by path and digest in `stage_scripts`, and the executor runs it
# with the stage directory as the working directory. The data it reads was synthesized by `prepare` and lives in the
# run's `inputs/`; nothing here is a per-run generated script.
#
# The work is `pdc_build`'s, and every rule it applies comes from an adapter whose own tests cover it -- the box from
# `pdc_box`, the placement and its gates from `pdc_placement`, the CG protein command from `pdc_protein`. This script
# only hands it the files it reads from the stage directory.
set -euxo pipefail

# The interpreter the application runs under, and the repository it imports from. `python` on the stage PATH is this
# workspace's virtualenv (`tools.search_path` puts it first); a caller that exports PYTHON/PROJECT_ROOT wins.
PYTHON="${PYTHON:-python}"
REPO_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

cp -f ../../inputs/pdc-settings.json ../../inputs/system_EMPTY.top .
# The detergent's derived model exists only for a run prepared with a mapping; a build without one stops at exit 3 and
# says so, exactly as it did when the adapter copied these in.
for name in detergent_CG.itp detergent_CG.json; do
  if [ -f "../../inputs/$name" ]; then
    cp -f "../../inputs/$name" .
  fi
done
# The empty-micelle build is the only case with a protein file in `inputs/`; a real protein is referenced where it
# lives, so it is resolved from the settings and copied into the stage the build reads it from.
if [ -f ../../inputs/protein.pdb ]; then
  cp -f ../../inputs/protein.pdb .
else
  PROTEIN=$("$PYTHON" -c 'import json,pathlib
settings = json.load(open("../../inputs/pdc-settings.json"))
value = str(settings.get("protein") or "")
if value:
    path = pathlib.Path(value)
    print(path if path.is_absolute() else pathlib.Path(settings["project_root"]) / path)' )
  if [ -n "$PROTEIN" ]; then
    cp -f "$PROTEIN" protein.pdb
  fi
fi

"$PYTHON" -m dashboard.execution.scripts.pdc_build --stage .
