#!/bin/bash
# Back-mapping (CG2AT2) for a protein-detergent complex: not built yet, and it says why.
#
# Design spec §10 decides this stage: CG2AT2 run from source under tools/, with its align method and the
# martini_3-0_charmm36 fragment database, so the atomistic output is the same product at higher resolution. It
# needs the vendored tool (task D1 in the pdc plan) and an invocation pinned by a test of its own; until that
# exists, this stage stops the run with the reason instead of writing a file nothing produced.
set -euxo pipefail

CG2AT="${CG2AT:-tools/cg2at/cg2at.py}"
if [ ! -f "$CG2AT" ]; then
  echo "back-mapping needs CG2AT2 under tools/ (task D1); $CG2AT is not there" >&2
  exit 3
fi
echo "CG2AT2 is present at $CG2AT, but its invocation is task D1: it must be pinned by a test before it runs" >&2
exit 3
