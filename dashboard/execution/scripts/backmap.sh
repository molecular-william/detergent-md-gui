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
