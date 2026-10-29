"""The protein's own topologies: every molecule martinize2 listed, in the file `grompp` is handed, and in every leg.

The first real run of this chain stopped at Energy minimisation with

    Topology include file "molecule_0.itp" not found

for two reasons at once, and they are the two this file pins. `system.top` included the protein's itp by its bare
name although martinize2 had written it in `cg/`; and it listed one molecule although the tool had written two, so
the second chain's beads sat in `system.gro` with no topology and no `[ molecules ]` row. Neither is about 4IAR: the
number of molecules is the tool's to decide (one per chain), so it is *read* from the tool's own `protein.top`
rather than written down anywhere.

Then the legs: each one runs `grompp` on a copy of `system.top`, and `grompp` resolves an include against the
directory the topology is in. So each leg declares the build stage's whole `cg/` tree as one input -- one location
for the whole run -- and reads it there instead of carrying a copy, which is the only spelling that works for one
molecule and for N.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from dashboard.execution import workflow
from dashboard.execution.adapters import pdc
from dashboard.execution.scripts import pdc_build

from tests.dashboard.pdc_fixtures import prepared_run, stage_dir, write_gro

#: martinize2's own output for a protein it split into two molecules, with a count that is not 1: the counts are the
#: tool's, and a topology that assumed `1` would list a molecule the structure holds twice as often.
TWO_MOLECULES = ('#include "martini.itp"\n#include "molecule_0.itp"\n#include "molecule_1.itp"\n\n'
                 '[ system ]\nTitle of the system\n\n[ molecules ]\nmolecule_0    1\nmolecule_1    2\n')
ONE_MOLECULE = ('#include "martini.itp"\n#include "molecule_0.itp"\n\n'
                '[ system ]\nTitle of the system\n\n[ molecules ]\nmolecule_0    1\n')
MOLECULE_ITP = '[ moleculetype ]\n{name} 1\n\n[ atoms ]\n1 C1 1 TYR BB 1 0 72\n'
DETERGENT_ITP = '[ moleculetype ]\nDDM 1\n\n[ atoms ]\n1 C1 1 DDM TAIL1 1 0 72\n'
#: The five stages that hand a `system.top` to `grompp`. The two assessments read a trajectory and no topology, so
#: they are not among them.
LEGS_ON_A_TOPOLOGY = ('Energy minimisation', 'NVT equilibration', 'NPT equilibration', 'CG assessment MD',
                      'CG extension MD')


def martinize_output(system: Path, topology: str) -> Path:
    """martinize2's output as the tool leaves it: the itps in `cg/`, and the `protein.top` that lists them.

    Vermouth writes one `.itp` per molecule type, named after it (`"{}.itp".format(moltype)`), which is why the
    include this stage writes can be derived from a `[ molecules ]` row at all -- and why a row whose file is not
    there is a build-time failure rather than a `grompp` one.
    """
    cg = system / pdc.PROTEIN_TOPOLOGY_DIRECTORY
    cg.mkdir(exist_ok=True)
    for name in re.findall(r'#include "([^"]+)"', topology):
        if name.endswith('.itp'):
            (cg / name).write_text(MOLECULE_ITP.format(name=name[:-len('.itp')]))
    (cg / 'protein.top').write_text(topology)
    return cg / 'protein.top'


def rows(topology: Path) -> list[tuple[str, int]]:
    """A written topology's `[ molecules ]` section, parsed the way `grompp` reads it."""
    section = Path(topology).read_text().split('[ molecules ]')[1]
    parsed = re.findall(r'^(\S+)\s+(\d+)\s*$', section, re.M)
    return [(name, int(count)) for name, count in parsed]


def includes(topology: Path) -> list[str]:
    return re.findall(r'#include "([^"]+)"', Path(topology).read_text())


def build_tree() -> str:
    """How a leg names the build stage's protein tree: the one directory in the run that holds it."""
    build = Path(pdc.stage_by_name('System preparation').relative).parent
    return f'../{build}/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/'


def protein_include(itp: str) -> str:
    """How a topology written by the build names one of that stage's itps."""
    return f'{build_tree()}{itp}'


def protein_includes(topology: Path) -> list[str]:
    tree = build_tree()
    return [name for name in includes(topology) if name.startswith(tree)]


def a_two_chain_system(tmp_path: Path) -> Path:
    """A prepared run whose system-preparation stage holds martinize2's two-molecule output and a built system."""
    run = prepared_run(tmp_path)
    system = stage_dir(run, 'System preparation')
    protein_top = martinize_output(system, TWO_MOLECULES)
    # The detergent topology a mapped build's `prepare` generates lives in the run's `inputs/`, and the topology
    # names it there from every stage that reads it.
    detergent = run / pdc.INPUTS_DIRECTORY / pdc.DETERGENT_TOPOLOGY
    detergent.write_text(DETERGENT_ITP)
    pdc_build.write_topologies(system, protein_top, detergent, 120)
    # The structure the first leg is handed, and the assessment's own products, which the extension continues from.
    write_gro(system / 'system.gro', [(1, 'MOL', 'BB', (0.0, 0.0, 0.0))])
    prod = stage_dir(run, 'CG assessment MD') / 'prod'
    prod.mkdir(parents=True, exist_ok=True)
    for name in ('run.tpr', 'run.cpt'):
        (prod / name).write_text('; a placeholder, so the extension leg has a phase to continue from\n')
    # The micelle assessment's own decision, which the extension reads and does not recompute.
    assessment = stage_dir(run, 'Micelle assessment')
    assessment.mkdir(parents=True, exist_ok=True)
    (assessment / 'removed.json').write_text('{"removed": []}\n')
    (assessment / 'kept.gro').write_text('system\n0\n   1.00000   1.00000   1.00000\n')
    return run


def copy_declared(stage: Path, name: str) -> None:
    """Copy the writable working copies a leg's script copies in: the phase-before `system.gro` and `system.top`.

    Everything else is read where it lies. A directory is never copied: the protein tree is declared as the build
    stage's directory and named by the topology, the Martini set is installed once, and the mdp/json records stay in
    `inputs/`. This does the plain-file copy without running GROMACS.
    """
    copied = 0
    for entry in pdc.stage_by_name(name).inputs:
        entry = str(entry)
        if not entry.startswith('../') or entry.startswith('../../') or entry.endswith('/'):
            continue
        if Path(entry).name not in ('system.gro', 'system.top'):
            continue
        source = stage / entry
        assert source.is_file(), f'{name} declares {entry}, which the phase before it did not write'
        shutil.copy2(source, stage / Path(entry).name)
        copied += 1
    assert copied, f'{name} copies nothing into its own directory'


# --- the topology the stage writes ------------------------------------------------------------------------------

def test_every_molecule_the_tool_listed_is_included_from_where_the_tool_wrote_it(tmp_path):
    run = prepared_run(tmp_path)
    system = stage_dir(run, 'System preparation')
    protein_top = martinize_output(system, TWO_MOLECULES)
    detergent = run / pdc.INPUTS_DIRECTORY / pdc.DETERGENT_TOPOLOGY
    detergent.write_text(DETERGENT_ITP)

    info = pdc_build.write_topologies(system, protein_top, detergent, 120)

    whole = (system / 'system.top').read_text()
    assert protein_includes(system / 'system.top') == [protein_include('molecule_0.itp'),
                                                       protein_include('molecule_1.itp')], \
        'every molecule the tool listed is included, from the build stage that holds it'
    assert 'martini.itp' not in whole, "the tool's own force field is not this system's"
    assert rows(system / 'system.top') == [('molecule_0', 1), ('molecule_1', 2), ('DDM', 120)], \
        'every row, with the counts the tool wrote'
    assert info['protein_molecules'] == ['molecule_0', 'molecule_1']


def test_the_empty_topology_carries_the_same_molecules_and_the_itps_for_them(tmp_path):
    """`system_EMPTY.top` is the stage's declared input, so it has to be as resolvable as the whole system."""
    run = prepared_run(tmp_path)
    system = stage_dir(run, 'System preparation')
    protein_top = martinize_output(system, TWO_MOLECULES)

    pdc_build.write_topologies(system, protein_top, None, 0)

    empty = system / 'system_EMPTY.top'
    assert protein_includes(empty) == [protein_include('molecule_0.itp'), protein_include('molecule_1.itp')]
    assert rows(empty) == [('molecule_0', 1), ('molecule_1', 2)]
    for include in protein_includes(empty):
        assert (system / include).is_file(), f'{empty.name} includes {include}, which the build stage does not hold'


def test_a_protein_the_tool_built_as_one_molecule_still_writes_exactly_one_row(tmp_path):
    run = prepared_run(tmp_path)
    system = stage_dir(run, 'System preparation')
    protein_top = martinize_output(system, ONE_MOLECULE)
    detergent = run / pdc.INPUTS_DIRECTORY / pdc.DETERGENT_TOPOLOGY
    detergent.write_text(DETERGENT_ITP)

    pdc_build.write_topologies(system, protein_top, detergent, 24)

    assert rows(system / 'system.top') == [('molecule_0', 1), ('DDM', 24)]
    assert rows(system / 'system_EMPTY.top') == [('molecule_0', 1)]


# --- the legs' declared inputs -----------------------------------------------------------------------------------

def test_each_leg_declares_the_build_stages_protein_tree_as_a_directory():
    """One entry, spelled as a directory: the build stage's tree, the one location that holds it for the run.

    A list of itp names could not be right for one molecule and for two, and a copy per leg would let two legs read
    different bytes; so every leg names the same directory, wherever its own `system.top` came from.
    """
    for name in LEGS_ON_A_TOPOLOGY:
        stage = pdc.stage_by_name(name)
        topologies = [entry for entry in stage.inputs if str(entry).endswith('system.top')]
        trees = [entry for entry in stage.inputs if str(entry).endswith('/')]
        assert len(topologies) == 1, f'{name} declares {topologies}'
        assert len(trees) == 1, f'{name} declares the protein tree as {trees}'
        assert str(trees[0]) == build_tree(), f'{name} reads the protein itps from somewhere other than the build'


def test_every_leg_receives_everything_its_topology_includes(tmp_path):
    """The chain, leg by leg: only the writable `system.gro`/`system.top` move forward, and each include resolves.

    This is the shape the first run failed in -- a leg whose `system.top` included a file that was never beside it --
    checked for two molecules over five legs. The protein tree, the generated detergent and the installed Martini set
    are read where they lie, never copied into a leg, so each leg's own directory has to resolve them. It also
    checks the contract's own input check before the copy: an entry spelled as a directory has to satisfy it, or the
    executor refuses the stage before its script runs.
    """
    run = a_two_chain_system(tmp_path)
    system = stage_dir(run, 'System preparation')
    assert protein_includes(system / 'system.top') == [protein_include('molecule_0.itp'),
                                                       protein_include('molecule_1.itp')], \
        'the fixture has to be the failing case'

    for name in LEGS_ON_A_TOPOLOGY:
        stage = stage_dir(run, name)
        assert workflow.missing_files(stage, pdc.stage_by_name(name).inputs) == [], f'{name} is refused before it runs'
        copy_declared(stage, name)
        for include in includes(stage / 'system.top'):
            assert (stage / include).is_file(), \
                f'{name} runs grompp on a topology including {include}, which does not resolve from its directory'
        assert (stage / protein_include('protein.top')).is_file(), \
            f'{name} cannot reach the tree that names its protein itps'


def test_the_extension_leg_takes_its_topology_from_the_assessment_and_the_tree_from_the_build():
    """The extension's `system.top` is the assessment phase's; the itps it includes stay in the build stage.

    One location for the whole run: the build stage wrote the tree, and every leg -- the extension included -- names
    it there. That is what lets a run carry the tree once rather than a copy per phase.
    """
    extension = pdc.stage_by_name('CG extension MD')
    assessment = Path(pdc.stage_by_name('CG assessment MD').relative).parent

    assert f'../{assessment}/system.top' in extension.inputs
    assert build_tree() in extension.inputs


def test_the_itps_a_leg_declares_are_recorded_as_its_inputs(tmp_path):
    """The manifest's `inputs_sha256` is provenance, and a declared tree's files are what the stage was given."""
    stage = tmp_path / '03_minimisation'
    stage.mkdir()
    tree = tmp_path / '02_system' / pdc.PROTEIN_TOPOLOGY_DIRECTORY
    tree.mkdir(parents=True)
    for name in ('molecule_0.itp', 'molecule_1.itp', 'protein.top'):
        (tree / name).write_text(f'; {name}\n')
    (tmp_path / '02_system' / 'system.top').write_text('[ molecules ]\n')

    carried = {str(path.relative_to(stage))
               for path in workflow._declared_paths(stage, f'../02_system/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/')}

    assert carried == {'../02_system/cg/molecule_0.itp', '../02_system/cg/molecule_1.itp',
                       '../02_system/cg/protein.top'}
    assert [path.name for path in workflow._declared_paths(stage, '../02_system/system.top')] == ['system.top'], \
        'a file input is still one file, not its directory'
