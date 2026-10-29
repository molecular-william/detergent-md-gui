"""Reviewed physics profiles and the one writer that renders them.

A run records the profile name it used (`PROFILES` keys are the versioned names, e.g. `cg-equilibration-v1`) beside
the numbers it chose; `render` and `write_mdp` turn that pair into the complete MDP file GROMACS reads.
"""
from .profiles import PROFILES
from .writer import Profile, render, write_mdp

__all__ = ['PROFILES', 'Profile', 'render', 'write_mdp']
