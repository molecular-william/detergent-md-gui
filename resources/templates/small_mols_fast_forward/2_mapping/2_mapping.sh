#!/bin/bash

source /usr/local/gromacs-2024.1/bin/GMXRC

virtualenv .venv
source .venv/bin/activate

pip install git+https://github.com/fgrunewald/fast_forward.git

ff_map -f ../1_AA_reference/prod/lig.xtc -s ../1_AA_reference/prod/lig.tpr -m cgbuilder.map -o mapped.xtc -mols LIG

