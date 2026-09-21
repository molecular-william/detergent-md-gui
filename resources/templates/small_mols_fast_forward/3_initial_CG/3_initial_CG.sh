#!/bin/bash

source ../2_mapping/.venv/bin/activate
source /usr/local/gromacs-2024.1/bin/GMXRC

gmx grompp -f initial.mdp -p topol.top -c ../2_mapping/mapped.gro -o mapped.tpr -maxwarn 1

ff_inter -f ../2_mapping/mapped.xtc -s mapped.tpr -i ENAP_initial.itp -dists -plots -itp-only

