#!/bin/bash
set -e
source /usr/local/gromacs-2024.1/bin/GMXRC

mkdir setup; cd setup
gmx editconf -f ../../2_mapping/mapped.gro -c -d 2.0 -bt dodecahedron -o newbox.gro > editconf.out 2>&1
gmx solvate -cp newbox.gro -cs ../inputs/water.gro -p ../topol.top -radius 0.21 -o solvated.gro > solvate.out 2>&1 
gmx grompp -f ../inputs/minimization.mdp -p ../topol.top -c solvated.gro -o ions.tpr -maxwarn 1 > ions.out 2>&1 
echo W | gmx genion -s ions.tpr -neutral -conc 0.15 -p ../topol.top -o ions.gro > genion.out 2>&1
cd ../

mkdir min; cd min
gmx grompp -f ../inputs/minimization.mdp -p ../topol.top -c ../setup/ions.gro -o min.tpr -maxwarn 1 > min-grompp.out 2>&1
gmx mdrun -deffnm min -pin on -nt 8 -v -gpu_id 0 > min.out 2>&1
cd ../

mkdir eq; cd eq
gmx grompp -f ../inputs/eq.mdp -p ../topol.top -c ../min/min.gro -o eq.tpr > eq-grompp.out 2>&1
gmx mdrun -deffnm eq -pin on -nt 8 -v -gpu_id 0 > eq.out 2>&1 
cd ../

mkdir prod; cd prod
gmx grompp -f ../inputs/md.mdp -p ../topol.top -c ../eq/eq.gro -o prod.tpr > prod-grompp.out 2>&1
gmx mdrun -deffnm prod -pin on -nt 8 -v -gpu_id 0 > prod.out 2>&1
echo ENAP ENAP | gmx trjconv -f prod.xtc -s prod.tpr -pbc mol -center -o lig_CG.gro -e 0 > trjconv_0.out 2>&1
echo ENAP ENAP | gmx trjconv -f prod.xtc -s prod.tpr -pbc mol -center -o lig_CG.xtc > trjconv_1.out 2>&1
cd ../
rm */*.out

head -n -3 topol.top > lig_CG.top
gmx grompp -f inputs/minimization.mdp -p lig_CG.top -c prod/lig_CG.gro -o prod/lig_CG.tpr -maxwarn 2


