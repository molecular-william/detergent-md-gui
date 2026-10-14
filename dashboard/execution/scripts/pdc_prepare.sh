#!/bin/bash
# Protein preparation for a protein-detergent complex run: the plan's step 1, and MemProtMD's Energy Minimise route
# down to the part the coarse-grained half needs.
#
# PDB2PQR rebuilds the residues a deposited structure left incomplete and adds the hydrogens its own protonation
# states need; the prepared structure is what every stage after this one coarse-grains (`pdc_build` hands it to
# martinize2). A structure whose file is missing side-chain atoms otherwise coarse-grains into beads with no
# position at all, and the placement refuses the whole build rather than placing a belt against a protein no
# distance can be measured to -- measured on 4iar: 20 of 928 beads, the side chains of 9 lysines, 6 arginines and
# one tryptophan.
#
# The step is optional, and both of its outcomes are recorded rather than implied. A run that does not ask for it
# records `skipped` (exit 4) with its reason in `skip.json` beside this script, and the run carries on. A run that
# does ask and cannot be answered -- the tool is not resolvable, or it exited non-zero -- records `prepare_protein.json`
# naming the tool, its command and its log, and exits 2.
#
# The minimisation the plan's step also names is not here: that route is atomistic, where this pipeline is
# coarse-grained, and the chain already carries a CG `Energy minimisation` leg in front of its assessment leg. The
# rebuild and the protonation are the half the CG path needs, and they cost seconds: measured on 4iar's 379-residue
# chain, 1.5 s.
set -euxo pipefail

python pdc_prepare.py --stage .
