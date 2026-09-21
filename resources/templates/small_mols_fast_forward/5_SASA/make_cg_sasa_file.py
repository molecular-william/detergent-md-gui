#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Mar 12 13:43:45 2025

@author: chris
"""

from vermouth.gmx import read_itp
from vermouth.forcefield import ForceField
import sys

if __name__=='__main__':

    ff = ForceField('dummy')
    
    file = sys.argv[1]
    with open(file) as f:
        lines = f.readlines()
        
    read_itp(lines, ff)
    
    radii = {"R":0.264, "S":0.230, "T":0.191}

    lines_out = []

    molname = list(ff.blocks.keys())[0]
    for node in ff.blocks[molname].nodes:
        atype = ff.blocks[molname].nodes[node]['atype']
        aname = ff.blocks[molname].nodes[node]['atomname']
        
        radius = radii.get(atype[0], 0.264)
        lines_out.append(f'{molname:3}\t{aname:5}\t{radius:5}\n')
    
    with open('vdwradii.dat', 'w') as fout:
        fout.writelines(lines_out)
        

