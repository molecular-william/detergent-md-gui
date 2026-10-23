#!/bin/bash
# Back-mapping (CG2AT2) for a protein-detergent complex: the coarse-grained system becomes atomistic again.
#
# The tool is vendored from source under `tools/` (gitignored, like the other vendored tools) and the commit the
# clone came from is recorded in the run's manifest. The invocation is design spec §10's decision: the **align**
# method with the **martini_3-0_charmm36** fragment library.
#
# `-silent` is not enough to keep the tool from asking: it suppresses the banner, not the questions. Every flag below is
# therefore chosen from the database's own contents (measured, one prompt per missing flag), and stdin is `/dev/null` so a
# prompt that still appears fails at once instead of hanging a stage nobody can answer.
#
# CG2AT2: Vickery & Stansfeld, J. Chem. Theory Comput. 2021, 17 (10), 6472-6482, DOI 10.1021/acs.jctc.1c00295.
#
# Measured limit: `DDM` is not in the fragment database, so the detergent is not converted -- the tool stops with
# "DDM is not in the fragment database!" on any complex whose CG input still carries it.
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

CG2AT="${CG2AT:-$PROJECT_ROOT/tools/cg2at/cg2at}"
if [ ! -e "$CG2AT" ]; then
  echo "back-mapping needs CG2AT2 under tools/; $CG2AT is not there (override with CG2AT=/path/to/cg2at)" >&2
  exit 3
fi

# The atomistic reference the conversion aligns to. The prepared protein when the run built one: `1_system/protein.pdb`
# carries heavy atoms only, and CG2AT2 runs pdb2gmx on what it is handed -- measured, that answers "the supplied protein
# structure contains incorrectly named or missing atoms", while the protonated `0_prepare/protein_prepared.pdb` completes.
ATOMISTIC=../0_prepare/protein_prepared.pdb
[ -f "$ATOMISTIC" ] || ATOMISTIC=../1_system/protein.pdb
cp -f "$ATOMISTIC" cg2at_atomistic.pdb

# The stage's declared input: the extension's structure as a PDB, which is what CG2AT2 takes for -c. The tool reads the
# periodic box from the PDB's CRYST1 record, and `gmx editconf` writes that record only when it is given a box -- without
# `-box` the conversion stops at "The input file is missing the Box vectors". The gro's own box line is in nm and `-box`
# takes nm, so it is passed through unconverted (measured: 8.26492 7.92381 17.01660 -> CRYST1 82.649 79.238 170.166).
BOX=$(tail -1 ../4_extension/prod/run.gro | awk '{printf "%.5f %.5f %.5f", $1, $2, $3}')
gmx editconf -f ../4_extension/prod/run.gro -o cg2at_input.pdb -box $BOX

# Every one of these flags is named because leaving it out does not fail, it *prompts*: `-silent` suppresses the banner, not
# the questions, so a stage with no terminal answers "Oops! That was a invalid choice" three times and dies.
#
#   -ff charmm36-mar2019-updated   the only copies of the tool's database that carry `merged.rtp` -- the file its residue
#                                  lookup reads, and the only one with `CYSD`, the disulphide cysteine this protein needs.
#                                  `charmm36-jul2022` here has no `merged.rtp` at all, and `charmm36` is not a name in the
#                                  list: measured, each of those ends in a prompt.
#   -fg martini_3-0_charmm36       the fragment library the design names.
#   -w tip3p                       the water the all-atom half uses (`charmm36-jul2022.ff/tip3p.itp` in the reference
#                                  topology), and a prompt without it.
#   -loc FINAL                     the directory the last line of this script tests for.
#
# stdin is `/dev/null` so any prompt still to come fails at once instead of waiting on nobody. Measured limit, not a
# guess: the tool stops at "DDM is not in the fragment database!" -- this detergent has no fragments in
# `martini_3-0_charmm36`, so a protein-detergent complex cannot be converted whole, and what this stage can produce is the
# protein's atoms.
python "$CG2AT" -c cg2at_input.pdb -a cg2at_atomistic.pdb -o align -fg martini_3-0_charmm36 -ff charmm36-mar2019-updated -w tip3p \
  -silent -loc FINAL < /dev/null 2>&1 | tee backmap.log

test -f FINAL/final_cg2at_aligned.pdb
