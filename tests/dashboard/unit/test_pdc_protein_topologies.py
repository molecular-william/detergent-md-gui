"""The protein's own topologies: every molecule martinize2 listed, in the file `grompp` is handed, and in every leg.

The first real run of this chain stopped at Energy minimisation with

    Topology include file "molecule_0.itp" not found

for two reasons at once, and they are the two this file pins. `system.top` included the protein's itp by its bare
name although martinize2 had written it in `cg/`; and it listed one molecule although the tool had written two, so
the second chain's beads sat in `system.gro` with no topology and no `[ molecules ]` row. Neither is about 4IAR: the
number of molecules is the tool's to decide (one per chain), so it is *read* from the tool's own `protein.top`
rather than written down anywhere.

Then the legs: each one runs `grompp` on a copy of `system.top`, and `grompp` resolves an include against the
directory the topology is in. So each leg declares the protein's whole `cg/` tree as one input and carries it, which
is the only spelling that works for one molecule and for N.
"""
from __future__ import annotations

import re
import subprocess
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


def protein_includes(topology: Path) -> list[str]:
    return [name for name in includes(topology) if name.startswith(pdc.PROTEIN_TOPOLOGY_DIRECTORY + '/')]


def a_two_chain_system(tmp_path: Path) -> Path:
    """A prepared run whose system-preparation stage holds martinize2's two-molecule output and a built system."""
    run = prepared_run(tmp_path)
    system = stage_dir(run, 'System preparation')
    protein_top = martinize_output(system, TWO_MOLECULES)
    (system / pdc.DETERGENT_TOPOLOGY).write_text(DETERGENT_ITP)
    pdc_build.write_topologies(system, protein_top, system / pdc.DETERGENT_TOPOLOGY, 120)
    # The structure the first leg is handed, and the assessment's own products, which the extension continues from.
    write_gro(system / 'system.gro', [(1, 'MOL', 'BB', (0.0, 0.0, 0.0))])
    prod = stage_dir(run, 'CG assessment MD') / 'prod'
    prod.mkdir(parents=True, exist_ok=True)
    for name in ('run.tpr', 'run.cpt'):
        (prod / name).write_text('; a placeholder, so the extension leg has a phase to continue from\n')
    return run


def copy_declared(stage: Path, name: str) -> None:
    """Run the copy prelude the adapter emitted into a leg's script, as the leg itself would run it.

    Only the emitted copy commands are executed: this test is about whether the files a leg declares arrive in its
    directory, not about running GROMACS.
    """
    script = stage / Path(pdc.stage_by_name(name).relative).name
    lines = [line for line in script.read_text().splitlines()
             if not line.strip().startswith('#') and line.startswith(('cp ', 'mkdir '))]
    assert lines, f'{name} copies nothing into its own directory'
    subprocess.run(['bash', '-euc', '\n'.join(lines)], cwd=stage, check=True, capture_output=True, text=True)


# --- the topology the stage writes ------------------------------------------------------------------------------

def test_every_molecule_the_tool_listed_is_included_from_where_the_tool_wrote_it(tmp_path):
    run = prepared_run(tmp_path)
    system = stage_dir(run, 'System preparation')
    protein_top = martinize_output(system, TWO_MOLECULES)
    (system / pdc.DETERGENT_TOPOLOGY).write_text(DETERGENT_ITP)

    info = pdc_build.write_topologies(system, protein_top, system / pdc.DETERGENT_TOPOLOGY, 120)

    whole = (system / 'system.top').read_text()
    assert '#include "cg/molecule_0.itp"' in whole, 'the include names the file, not the stage root'
    assert '#include "cg/molecule_1.itp"' in whole, 'the second molecule the tool listed is not left behind'
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
    assert protein_includes(empty) == ['cg/molecule_0.itp', 'cg/molecule_1.itp']
    assert rows(empty) == [('molecule_0', 1), ('molecule_1', 2)]
    for include in protein_includes(empty):
        assert (system / include).is_file(), f'{empty.name} includes {include}, which the stage does not hold'


def test_a_protein_the_tool_built_as_one_molecule_still_writes_exactly_one_row(tmp_path):
    run = prepared_run(tmp_path)
    system = stage_dir(run, 'System preparation')
    protein_top = martinize_output(system, ONE_MOLECULE)
    (system / pdc.DETERGENT_TOPOLOGY).write_text(DETERGENT_ITP)

    pdc_build.write_topologies(system, protein_top, system / pdc.DETERGENT_TOPOLOGY, 24)

    assert rows(system / 'system.top') == [('molecule_0', 1), ('DDM', 24)]
    assert rows(system / 'system_EMPTY.top') == [('molecule_0', 1)]


# --- the legs' declared inputs -----------------------------------------------------------------------------------

def test_each_leg_declares_the_protein_tree_as_a_directory_beside_its_topology():
    """One entry, spelled as a directory: a list of itp names could not be right for one molecule and for two."""
    for name in LEGS_ON_A_TOPOLOGY:
        stage = pdc.stage_by_name(name)
        topologies = [entry for entry in stage.inputs if str(entry).endswith('system.top')]
        trees = [entry for entry in stage.inputs if str(entry).endswith('/')]
        assert len(topologies) == 1, f'{name} declares {topologies}'
        assert len(trees) == 1, f'{name} declares the protein tree as {trees}'
        assert str(trees[0]) == f'{Path(str(topologies[0])).parent}/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/', \
            f'{name} takes its protein itps from a directory other than its topology\'s'


def test_every_leg_receives_everything_its_topology_includes(tmp_path):
    """The chain, leg by leg: after the copies each leg holds each include of the `system.top` it will hand grompp.

    This is the shape the first run failed in -- a leg whose `system.top` included a file that was never put beside
    it -- checked for two molecules over five legs. It also checks the contract's own input check before each copy:
    an entry spelled as a directory has to satisfy it, or the executor refuses the stage before its script runs.
    """
    run = a_two_chain_system(tmp_path)
    system = stage_dir(run, 'System preparation')
    assert protein_includes(system / 'system.top') == ['cg/molecule_0.itp', 'cg/molecule_1.itp'], \
        'the fixture has to be the failing case'

    for name in LEGS_ON_A_TOPOLOGY:
        stage = stage_dir(run, name)
        assert workflow.missing_files(stage, pdc.stage_by_name(name).inputs) == [], f'{name} is refused before it runs'
        copy_declared(stage, name)
        for include in includes(stage / 'system.top'):
            assert (stage / include).is_file(), \
                f'{name} runs grompp on a topology including {include}, which is not in its directory'
        assert (stage / pdc.PROTEIN_TOPOLOGY_DIRECTORY / 'protein.top').is_file(), \
            f'{name} carries the tree whole, including the topology that names its itps'


def test_the_extension_leg_reads_the_tree_from_the_phase_whose_topology_it_runs():
    """The extension's `system.top` is the assessment phase's, so its itps have to come from there as well.

    Copying them from `1_system` would work by luck -- both trees hold the same files today -- and would stop
    working the day a stage edited one of them.
    """
    extension = pdc.stage_by_name('CG extension MD')

    assert '../2_assessment/system.top' in extension.inputs
    assert f'../2_assessment/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/' in extension.inputs


def test_the_itps_a_leg_carries_are_recorded_as_its_inputs(tmp_path):
    """The manifest's `inputs_sha256` is provenance, and a carried tree's files are what the stage was given."""
    stage = tmp_path / '2_minimisation'
    stage.mkdir()
    tree = tmp_path / '1_system' / pdc.PROTEIN_TOPOLOGY_DIRECTORY
    tree.mkdir(parents=True)
    for name in ('molecule_0.itp', 'molecule_1.itp', 'protein.top'):
        (tree / name).write_text(f'; {name}\n')
    (tmp_path / '1_system' / 'system.top').write_text('[ molecules ]\n')

    carried = {str(path.relative_to(stage))
               for path in workflow._declared_paths(stage, f'../1_system/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/')}

    assert carried == {'../1_system/cg/molecule_0.itp', '../1_system/cg/molecule_1.itp',
                       '../1_system/cg/protein.top'}
    assert [path.name for path in workflow._declared_paths(stage, '../1_system/system.top')] == ['system.top'], \
        'a file input is still one file, not its directory'
