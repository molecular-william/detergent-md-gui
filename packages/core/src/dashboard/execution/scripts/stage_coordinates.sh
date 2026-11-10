#!/bin/bash
# Stage 2 for a CG run that starts from the coordinates its parameterization recorded.
#
# A fit keeps the mapped starting frame beside its revision (`mapped.gro`, `mapped.xtc` and a `coordinates.json`
# record). A `stored` run copies that frame into `2_mapping/` instead of reading the AA trajectory again, so no
# re-mapping is paid and the simulation starts exactly where the fit measured. The files were copied into the run's
# `inputs/coordinates/` at prepare and are hashed in its `inputs` record, which the executor verifies before this
# stage starts; this script only places them.
#
# The stage keeps the name "trajectory mapping" and declares `mapped.gro` and `mapped.xtc`, so stage 3 and every
# analysis that reads `2_mapping/mapped.*` keep their declared inputs.
set -euo pipefail

for name in mapped.gro mapped.xtc; do
    cp -- "../../inputs/coordinates/$name" "$name"
done
