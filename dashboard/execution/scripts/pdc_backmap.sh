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
# Measured limit: `DDM` is not in the tool's own fragment database, so this stage cannot convert the detergent until the
# run's mapping writes one (`cg2at_fragment.py`) and the conversion tree carries the molecule's types
# (`extend_forcefield`) -- both measured to work, neither wired into this script yet. Until then the tool stops at
# "DDM is not in the fragment database!" on a complex whose CG input still carries the detergent.
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

# A conversion is not resumable, and the tool does not clear up after itself: it writes a topology and a structure that
# are one system, and a leftover pair from an earlier attempt is read as this attempt's. Measured on a re-run: grompp
# refused "number of coordinates in coordinate file (113724) does not match topology (113714)" because the topology was
# the previous, already-neutralised one. So the stage clears its own conversion before it starts.
rm -rf FINAL

# The atomistic reference the conversion aligns to. The prepared protein when the run built one: `1_system/protein.pdb`
# carries heavy atoms only, and CG2AT2 runs pdb2gmx on what it is handed -- measured, that answers "the supplied protein
# structure contains incorrectly named or missing atoms", while the protonated `0_prepare/protein_prepared.pdb` completes.
ATOMISTIC=../0_prepare/protein_prepared.pdb
[ -f "$ATOMISTIC" ] || ATOMISTIC=../1_system/protein.pdb
cp -f "$ATOMISTIC" cg2at_atomistic.pdb

# The conversion's own inputs, from the run's own mapping: the detergent's fragment, a force-field directory carrying the
# molecule's atom types, a mirror of the fragment library that holds them, and the CG structure with bead names short
# enough to survive the tool's PDB round trip. Built inside the stage -- the vendored database is not written to. A run
# whose detergent has no mapping cannot be converted, and the helper says so and exits 3.
python "$PROJECT_ROOT/dashboard/execution/scripts/pdc_backmap.py" --stage . --project-root "$PROJECT_ROOT" \
  2>&1 | tee backmap_inputs.log
test -f backmap_inputs.json
FRAGMENTS=$(python -c "import json;print(json.load(open('backmap_inputs.json'))['library'])")
FORCEFIELD=$(python -c "import json;print(json.load(open('backmap_inputs.json'))['force_field'])")
# `-c` takes the renamed **gro**, not a pdb from `gmx editconf`: the tool rewrites whatever it is handed to PDB, and the
# shortening is lost the moment it does. The gro carries its own box line, so no `-box` is needed either.
STRUCTURE=cg2at_input.gro

# Every one of these flags is named because leaving it out does not fail, it *prompts*: `-silent` suppresses the banner, not
# the questions, so a stage with no terminal answers "Oops! That was a invalid choice" three times and dies.
#
#   -ff charmm36-mar2019-updated   the only copies of the tool's database that carry `merged.rtp` -- the file its residue
#                                  lookup reads, and the only one with `CYSD`, the disulphide cysteine this protein needs.
#                                  `charmm36-jul2022` here has no `merged.rtp` at all, and `charmm36` is not a name in the
#                                  list: measured, each of those ends in a prompt.
#   -fg <path>                     the mirrored copy of `martini_3-0_charmm36` that holds this run's detergent fragment.
#                                  `-fg` takes a path, not just a name: the mirror keeps the library's own name and
#                                  structure, because the tool reads `<parent>/<name>/non_protein/...`.
#   -w tip3p                       the water the all-atom half uses (`charmm36-jul2022.ff/tip3p.itp` in the reference
#                                  topology), and a prompt without it.
#   -loc FINAL                     the directory the last line of this script tests for.
#
# stdin is `/dev/null` so any prompt still to come fails at once instead of waiting on nobody.
#
# The tool's exit status is not this stage's verdict: it exits 1 whenever the aligned build is missing, and the aligned
# build is missing whenever its steering leg gives up -- while the de-novo complex it did convert sits on disk. So the
# status is tolerated and the files are what decide (measured: a whole 113,724-atom complex, exit 1).
set +e
python "$CG2AT" -c "$STRUCTURE" -a cg2at_atomistic.pdb -o align -fg "$FRAGMENTS" -ff "$FORCEFIELD" -w tip3p \
  -silent -loc FINAL < /dev/null 2>&1 | tee backmap.log
CG2AT_EXIT=$?
set -e
echo "cg2at exit status: $CG2AT_EXIT (the converted files, not this, decide the outcome)"

# The conversion writes the de-novo build whenever it converts at all, and the aligned one only when its steering leg
# succeeds: measured on this box, the steering leg refuses a system with net charge ("Ewald electrostatics in a system with
# net charge"), so a stage that demanded `final_cg2at_aligned.pdb` failed after converting the whole complex. The de-novo
# build is the success this stage claims, and it says which one it produced.
# `-loc FINAL` names the tool's *working* directory; it writes the finished system one level deeper, in `FINAL/FINAL/`
# (measured: topol_final.top and the 113,724-atom pdb both live there, and a check one level short reads a converted
# complex as no conversion at all).
if [ -f FINAL/FINAL/final_cg2at_aligned.pdb ]; then
  echo "back-mapped: FINAL/FINAL/final_cg2at_aligned.pdb (aligned to the CG input)"
elif [ -f FINAL/FINAL/final_cg2at_de_novo.pdb ]; then
  echo "back-mapped: FINAL/FINAL/final_cg2at_de_novo.pdb (de novo; the alignment leg did not produce one)"
else
  echo "back-mapping produced no converted structure; see backmap.log" >&2
  exit 3
fi

# The converted complex carries the atomistic protein's own net charge against the ions the CG system held -- measured on
# the 4iar/DDM complex: -5. Neutralising it here is what lets a later atomistic leg (and CG2AT2's own steering) run in a
# box GROMACS will simulate without warning about Ewald background charge. `neutralisation.json` records the sum before and
# after and the ions it took, so a converted system that is still charged is visible rather than assumed fixed.
python "$PROJECT_ROOT/dashboard/execution/scripts/pdc_neutralise.py" --system FINAL/FINAL --stage . 2>&1 | tee neutralise.log
