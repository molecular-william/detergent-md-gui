#!/bin/bash
set -e
source /usr/local/gromacs-2024.4/bin/GMXRC

# $1 is the molname

# AA
mkdir AA; cd AA
cp ../vdwradii_AA.dat  vdwradii.dat
# Compute SASA
echo 0| gmx sasa -f ../../1_AA_reference/prod/lig.xtc -s ../../1_AA_reference/prod/lig.tpr -ndots 4800 -probe 0.191  -o SASA-AA.xvg -dt 100
# Analyse SASA
gmx analyze -f SASA-AA.xvg -bw 0.01 -dist distr-SASA-AA.xvg &> temp_sasa.txt
# Compute Connolly Surface
echo 0 | gmx sasa -s ../../1_AA_reference/prod/lig.gro -o temp.xvg -probe 0.191 -ndots 240 -q surf-AA.pdb
rm temp.xvg temp_sasa.txt
cd ..


# CG
mkdir CG; cd CG
ln -s ../make_cg_sasa_file.py
./make_cg_sasa_file.py ../../4_CG_sim/ENAP.itp

# Compute SASA
echo 0 | gmx sasa -f ../../4_CG_sim/prod/lig_CG.xtc -s ../../4_CG_sim/prod/lig_CG.tpr -ndots 4800 -probe 0.191  -o SASA-CG.xvg
gmx analyze -f SASA-CG.xvg -bw 0.01 -dist distr-SASA-CG.xvg &> temp_sasa.txt
# Compute Connolly Surface
echo 0 | gmx sasa -s ../../2_mapping/mapped.gro -o temp.xvg -probe 0.191 -ndots 240 -q surf-CG.pdb
rm temp.xvg temp_sasa.txt
cd ..

