#!/bin/bash
set -e

source /usr/local/gromacs-2024.1/bin/GMXRC


########################################
###### SCRIPT TO RUN SIMULATIONS #######
########################################
# $1 - name of molecule
# $2 - number of threads to use
# $3 - gpu_id for mdrun

threads=8

tar -xzvf results.tar.gz

gmx editconf -f MMFF/lig.pdb -d 2.0 -c -bt dodecahedron -o newbox.gro

mkdir min-vac; cd min-vac
gmx grompp -f ../mdps/em.mdp -c ../newbox.gro -p ../topol.top -o min-vac.tpr -maxwarn 1
gmx mdrun -deffnm min-vac -v -nt $threads -pin on 
cd ../

mkdir solvate; cd solvate
gmx solvate -cp ../min-vac/min-vac.gro -cs spc216.gro -p ../topol.top -o solvated.gro
gmx grompp -f ../mdps/ions.mdp -p ../topol.top -c solvated.gro -o ions.tpr
echo SOL | gmx genion -s ions.tpr -p ../topol.top -conc 0.15 -neutral -pname SOD -nname CLA -o ions.gro
cd ../

mkdir min; cd min
gmx grompp -f ../mdps/em.mdp -p ../topol.top -c ../solvate/ions.gro -o min.tpr
gmx mdrun -deffnm min -v -nt $threads -pin on 
cd ../

mkdir eq; cd eq
gmx grompp -f ../mdps/eq.mdp -p ../topol.top -c ../min/min.gro  -o eq.tpr
gmx mdrun -deffnm eq -v -nt $threads -pin on 
cd ../

mkdir prod; cd prod
gmx grompp -f ../mdps/md.mdp -p ../topol.top -c ../eq/eq.gro -o prod.tpr
gmx mdrun -deffnm prod -v -nt $threads -pin on 
echo LIG LIG | gmx trjconv -f prod.xtc -s prod.tpr -pbc mol -center -o lig.gro -e 0
echo LIG LIG | gmx trjconv -f prod.xtc -s prod.tpr -pbc mol -center -o lig.xtc
cd ../

head -n -3 topol.top > lig.top
gmx grompp -f mdps/em.mdp -p lig.top -c prod/lig.gro -o lig.tpr

