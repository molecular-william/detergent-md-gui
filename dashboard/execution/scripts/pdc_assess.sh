#!/bin/bash
# Micelle assessment for a protein-detergent complex phase (stages 3 and 5).
#
# The criterion, the tail beads and the aggregation number are not restated here: pdc_assess.py reads the run's own
# settings and calls pdc_assessment, which is the one implementation of the design spec's §7. This stage writes
# assessment.json (the numbers behind the verdict), kept.gro (what stays if the rest is removed) and removed.json
# (what a removal decision would act on).
set -euxo pipefail

python pdc_assess.py --settings ../1_system/pdc-settings.json --structure prod/run.gro
