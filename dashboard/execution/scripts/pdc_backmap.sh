#!/bin/bash
# Back-mapping (CG2AT2) for a protein-detergent complex: the coarse-grained system becomes atomistic again.
#
# The tool is vendored from source under `tools/` (gitignored, like the other vendored tools) and the commit the
# clone came from is recorded in the run's manifest. The invocation is design spec §10's decision: the **align**
# method, the **martini_3-0_charmm36** fragment library, and `-silent`, which is load-bearing — the tool asks its
# questions on stdin otherwise (`-info` prompts for a library choice, and a stage that prompts is a stage that hangs
# instead of failing).
#
# CG2AT2: Vickery & Stansfeld, J. Chem. Theory Comput. 2021, 17 (10), 6472-6482, DOI 10.1021/acs.jctc.1c00295.
#
# Not yet exercised: no conversion has been run here, because it needs a completed system. The detergent's fragment
# coverage in CG2AT2's database is therefore unverified, and this script says so rather than implying otherwise.
set -euxo pipefail

# Back-mapping is a toggle now, on by default. A run that switched it off records the contract's fourth outcome --
# `skipped` (exit 4) with its reason in `skip.json` beside the script -- and the run still terminates `complete`,
# because nothing was attempted and nothing is owed. The setting arrives in the same settings file this stage already
# reads for the protein; the interpreter is the one the pdc adapter stamps into this line at prepare time, so a bare
# `python` never appears in a copied stage script.
BACKMAP=$(python -c "import json;print(json.load(open('../1_system/pdc-settings.json')).get('backmap', True))")
if [ "$BACKMAP" != "True" ]; then
  echo '{"skipped": true, "reason": "the run switched back-mapping off, so this stage has nothing to do"}' > skip.json
  echo "skipped: the run switched back-mapping off, so this stage has nothing to do" >&2
  exit 4
fi

# A protein-free complex run has nothing to align: this stage exists to put the protein's atoms back, and there are
# none. That is not a failure and not a blocked run -- nothing was attempted -- so the stage skips, says why, and the
# run carries on. The contract's fourth outcome, `skipped` (exit 4).
python -c "import json;print(json.load(open('../1_system/pdc-settings.json')).get('protein') or '')" > protein.txt
PROTEIN=$(cat protein.txt)
rm -f protein.txt
if [ -z "$PROTEIN" ]; then
  echo '{"skipped": true, "reason": "the run has no protein, so there is nothing to align"}' > skip.json
  echo "skipped: the run has no protein, so there is nothing to align" >&2
  exit 4
fi

CG2AT="${CG2AT:-tools/cg2at/cg2at}"
if [ ! -e "$CG2AT" ]; then
  echo "back-mapping needs CG2AT2 under tools/ (task D1); $CG2AT is not there" >&2
  exit 3
fi

# The stage's declared input: the extension's structure as a PDB, which is what CG2AT2 takes for -c.
gmx editconf -f ../4_extension/prod/run.gro -o cg2at_input.pdb

python "$CG2AT" -c cg2at_input.pdb -a protein.pdb -o align -fg martini_3-0_charmm36 -ff charmm36 \
  -silent -loc FINAL 2>&1 | tee backmap.log

test -f FINAL/final_cg2at_aligned.pdb
