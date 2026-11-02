"""The detergent's beads in place, and the topology that names them: stage 1's last two pieces.

The stamping is checked against arithmetic a reader can do by hand (a two-bead molecule, a stated centre and a
direction), and the topology against the invariant `grompp` enforces: every `[ molecules ]` count times its
molecule's bead count must equal the atoms the structure holds. The end-to-end case runs the real stage on the
repository's own DDM with a mapping the test writes, which is the first time that stage can complete.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import types
from pathlib import Path

import detergent_pdc
import numpy as np
import pytest
from detergent_pdc.execution.adapters import pdc
from detergent_pdc.execution.scripts import pdc_build

from tests.harness.pdc_fixtures import candidate_file, system_stage, write_cg_pdb
from tests.harness.support import PROJECT_ROOT

MOLECULE_ROOT = PROJECT_ROOT / 'molecules'
TEMPLATE = {
    'name': 'DDM', 'residue': 'DDM', 'coordinates': 'results/MMFF/lig1.pdb',
    'topology': 'results/MMFF/lig1.itp', 'beads': [{'name': 'TAIL1', 'type': 'C1', 'role': 'tail'},
                                                   {'name': 'HEAD', 'type': 'SN6', 'role': 'head'}],
}
PROTEIN_ITP = '[ moleculetype ]\nPROT 1\n\n[ atoms ]\n1 C1 1 PROT B01 1 0 72\n'
DRAFT = {'molecule_id': 'DDM', 'residue': 'DDM', 'terms': 2, 'reference_terms': 0, 'fallback_terms': 2,
         'beads': [{'name': 'TAIL1', 'type': 'C1', 'residue': 'DDM', 'position': [0.5, 0.0, 0.0]},
                   {'name': 'HEAD', 'type': 'SN6', 'residue': 'DDM', 'position': [0.0, 0.0, 0.0]}]}


def prepared_stage(tmp_path):
    """The stage `pdc.prepare` and martinize2 leave: settings, the detergent model and the CG protein's files.

    The real DDM is copied into the test's own tree so nothing is written near the repository's files, and the CG
    protein is written rather than coarse-grained, so the build reads a structure without running the tool. The
    template names two beads and the mapping derives two, which is what a library entry has to match.
    """
    root = tmp_path / 'root'
    (root / 'molecules').mkdir(parents=True)
    shutil.copytree(MOLECULE_ROOT / 'DDM', root / 'molecules' / 'DDM')
    (root / 'molecules' / 'DDM' / 'protein.pdb').write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n')
    (root / 'molecules' / 'DDM' / 'micelle_template.json').write_text(json.dumps(TEMPLATE))
    run = tmp_path / 'run'
    run.mkdir()
    pdc.prepare(run, protein='molecules/DDM/protein.pdb', template='molecules/DDM/micelle_template.json',
                settings={'seed': 20260930, 'aggregation_number': 2}, project_root=root,
                mapping=candidate_file(tmp_path))
    stage = system_stage(run)
    # martinize2's own output: the itps in `cg/`, named after their molecule types, and the `protein.top` that lists
    # them. `build` reads the list from the tool's file rather than from the first itp it can find.
    write_cg_pdb(stage / 'cg' / 'protein_cg.pdb', [(1, 'PRO', 'B01', (0.0, 0.0, 0.0)),
                                                   (1, 'PRO', 'B02', (1.0, 0.0, 0.0)),
                                                   (1, 'PRO', 'B03', (0.0, 1.0, 0.0))])
    (stage / 'cg' / 'PROT.itp').write_text(PROTEIN_ITP)
    (stage / 'cg' / 'protein.top').write_text('#include "martini.itp"\n#include "PROT.itp"\n\n[ system ]\nTitle\n\n'
                                              '[ molecules ]\nPROT    1\n')
    return stage


def test_a_detergent_is_placed_with_its_head_end_at_the_site_it_was_given():
    """Heads to the water, tails to the core -- and the *head end* is what the site names.

    The placement's sites are the head ends of the belt's detergents (the tube's outer surface), so `stamp`
    translates each copy until its head-most bead sits at the site and its body hangs back toward the centre-line.
    Measured before this: the molecule's *mean* was put at the site, which left every head bead 0.25 nm past the
    site it was supposed to stand on. The direction the placement hands over is the way out of the tube, so the
    molecule's head-ward axis is the one that takes it.
    """
    along = pdc_build.stamp(DRAFT, [[3.0, 0.0, 0.0]], [[1.0, 0.0, 0.0]], first_residue=10)
    against = pdc_build.stamp(DRAFT, [[3.0, 0.0, 0.0]], [[-1.0, 0.0, 0.0]], first_residue=10)

    beads = {atom['name']: atom['position'] for atom in along}
    assert beads['HEAD'] == [3.0, 0.0, 0.0], 'the head end is the site, not the molecule\'s middle'
    assert beads['TAIL1'] == [2.5, 0.0, 0.0], 'and the tail hangs back toward the centre-line'
    flipped = {atom['name']: atom['position'] for atom in against}
    assert flipped['HEAD'] == [3.0, 0.0, 0.0], 'the anchor holds whichever way the head faces'
    assert flipped['TAIL1'] == [3.5, 0.0, 0.0], 'and the body follows the direction it was given'


def test_a_stamped_micelle_has_its_heads_toward_the_water_and_its_tails_in_the_core():
    """The property the frames are judged by: per detergent, the head is further from the micelle's centre than
    the tail -- heads to the water, tails in the core.

    This is the end-to-end shape of the defect a reader saw -- the head bead pointing into the micelle -- measured
    the way the draft's frames were measured, over a real lattice placement of the pipeline's own code.
    """
    import numpy as np
    from detergent_pdc.execution.adapters import pdc_placement

    placed = pdc_placement.place_detergents(None, None, 24, seed=20261013, mode='lattice')
    atoms = pdc_build.stamp(DRAFT, placed['centers'], placed['directions'], first_residue=10)
    centre = np.mean([atom['position'] for atom in atoms], axis=0)

    molecules: dict[int, list[dict]] = {}
    for atom in atoms:
        molecules.setdefault(atom['residue_id'], []).append(atom)
    assert len(molecules) == 24
    centres = set()
    for residue_id, beads in molecules.items():
        head = np.mean([atom['position'] for atom in beads if atom['name'] == 'HEAD'], axis=0)
        tail = np.mean([atom['position'] for atom in beads if atom['name'] == 'TAIL1'], axis=0)
        assert np.linalg.norm(head - centre) > np.linalg.norm(tail - centre), \
            f'detergent {residue_id} has its head facing the micelle and its tail facing the water'
        centres.add(tuple(np.round(np.mean([atom['position'] for atom in beads], axis=0), 4)))
    assert len(centres) == 24, 'sanity: every detergent sits at its own placement site'


def test_every_copy_keeps_the_topologys_bead_names_and_gets_its_own_residue():
    atoms = pdc_build.stamp(DRAFT, [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]], [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                            first_residue=7)

    assert [atom['name'] for atom in atoms] == ['TAIL1', 'HEAD', 'TAIL1', 'HEAD']
    assert [atom['residue'] for atom in atoms] == ['DDM'] * 4
    assert [atom['residue_id'] for atom in atoms] == [8, 8, 9, 9], 'one residue per molecule, after the protein'


def test_a_mapping_that_marks_no_hydrophobic_core_is_refused():
    undifferentiated = {'residue': 'DDM', 'beads': [{'name': 'A', 'type': 'SN6', 'position': [0.0, 0.0, 0.0]},
                                                    {'name': 'B', 'type': 'SP1r', 'position': [0.5, 0.0, 0.0]}]}

    with pytest.raises(SystemExit, match='no hydrophobic core'):
        pdc_build.stamp(undifferentiated, [[0.0, 0.0, 0.0]], [[1.0, 0.0, 0.0]])


def test_the_topology_names_its_molecules_exactly_as_the_tool_listed_them(tmp_path):
    """martinize2 writes one `.itp` per molecule type, named after it, and lists each with its count.

    The fixture reproduces that shape -- the itps in `cg/`, beside the tool's own `protein.top`. The include this
    stage writes names the file from the build stage that holds it (`../<stage>/cg/<name>.itp`), because a sibling
    leg reads the copied `system.top` from its own directory and a bare `cg/<name>.itp` would not resolve there.
    """
    cg = tmp_path / 'cg'
    cg.mkdir()
    (cg / 'PROT.itp').write_text(PROTEIN_ITP)
    (cg / 'protein.top').write_text('#include "martini.itp"\n#include "PROT.itp"\n\n[ system ]\nTitle\n\n'
                                    '[ molecules ]\nPROT    1\n')
    detergent = tmp_path / 'detergent_CG.itp'
    detergent.write_text('[ moleculetype ]\nDDM 1\n\n[ atoms ]\n1 C1 1 DDM TAIL1 1 0 72\n')

    written = pdc_build.write_topologies(tmp_path, cg / 'protein.top', detergent, 3)

    whole = (tmp_path / 'system.top').read_text()
    assert written == {'protein_molecule': 'PROT', 'protein_molecules': ['PROT'],
                       'detergent_molecule': 'DDM', 'detergents': 3}
    protein_include = f'../{tmp_path.name}/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/PROT.itp'
    assert f'#include "{protein_include}"' in whole, 'the include names the build stage tree, not this directory'
    detergent_include = f'../../{pdc.INPUTS_DIRECTORY}/{pdc.DETERGENT_TOPOLOGY}'
    assert f'#include "{detergent_include}"' in whole, "the detergent is the run's generated original in inputs/"
    assert 'PROT\t1' in whole and 'DDM\t3' in whole
    assert 'martini.itp' not in whole, "the tool's own force field is not this system's"
    assert 'DDM\t' not in (tmp_path / 'system_EMPTY.top').read_text(), 'the empty topology is the protein alone'


def test_a_molecule_the_tool_listed_without_its_itp_is_refused_rather_than_written(tmp_path):
    """The failure this replaces was `grompp`'s, in a stage after the build: name the missing file at the build."""
    cg = tmp_path / 'cg'
    cg.mkdir()
    (cg / 'PROT.itp').write_text(PROTEIN_ITP)
    (cg / 'protein.top').write_text('[ molecules ]\nPROT 1\nLIGAND 2\n')

    with pytest.raises(SystemExit, match='LIGAND'):
        pdc_build.write_topologies(tmp_path, cg / 'protein.top', None, 0)


def test_a_topology_without_a_molecule_name_is_refused_rather_than_guessed():
    with pytest.raises(SystemExit, match='moleculetype'):
        pdc_build.molecule_name('; a topology with nothing to name\n')


def test_the_stage_completes_when_the_run_was_prepared_with_a_detergent_mapping(tmp_path):
    """The whole of stage 1: a placed system, a topology whose counts match its atoms, and exit 0."""
    stage = prepared_stage(tmp_path)

    code = pdc_build.build(stage)

    assert code == 0, 'the first time this stage has anything to finish with'
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['system_top'] == 'system.top' and report['molecules']['detergent_molecule'] == 'DDM'
    system = (stage / 'system.gro').read_text().splitlines()
    beads = int(system[1])
    protein = 3
    per_detergent = len(json.loads((stage / pdc.DETERGENT_GEOMETRY).read_text())['beads'])
    assert per_detergent == 2
    assert beads == protein + 2 * per_detergent, 'the atoms present are what [ molecules ] claims'
    topology = (stage / 'system.top').read_text()
    assert 'DDM\t2' in topology and 'PROT\t1' in topology
    protein_include = f'../{stage.name}/{pdc.PROTEIN_TOPOLOGY_DIRECTORY}/PROT.itp'
    assert f'#include "{protein_include}"' in topology, \
        'the topology names the protein itp in the build stage tree, where every sibling leg resolves it'
    assert not (stage / 'snapshots').exists(), 'the build no longer records a placement snapshot'
    assert 'conformations' not in report, 'a run that names no library is the report it always was'


# --- a conformation library's drawn body ---------------------------------------------------------------

#: The atoms `stamp` wrote before a library could be named, byte for byte: the template path is unchanged, and a
#: change here means every existing build's coordinates moved. Re-record it only when that is the intended change.
TEMPLATE_STAMP_SHA256 = '8f8bd798adf0ead7a7283f8fb56baa44d396851064103b67a07656d3f4c81368'
#: One library entry in the model's own bead order (TAIL1 then HEAD), head-anchored with its axis along +z: the
#: head bead is the origin, the tail sits half a nanometre behind it and a fifth off the axis.
LIBRARY_ENTRIES = [[[0.2, 0.0, -0.5], [0.0, 0.0, 0.0]]]


def test_stamping_with_no_entries_is_the_stamp_it_always_was():
    centres, directions = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0]]
    implicit = pdc_build.stamp(DRAFT, centres, directions, first_residue=7)
    explicit = pdc_build.stamp(DRAFT, centres, directions, first_residue=7, entries=None, twists=None)

    assert implicit == explicit
    digest = hashlib.sha256(json.dumps(implicit, sort_keys=True).encode()).hexdigest()
    assert digest == TEMPLATE_STAMP_SHA256


def test_a_library_entry_is_stamped_head_on_the_site_and_turned_by_its_azimuth():
    """`position = centre + R @ Rz(twist) @ bead`, with the bead names and residue numbers still the topology's."""
    entry = np.array([[0.2, 0.0, -0.5], [0.0, 0.0, 0.0]])
    centres = [[2.0, 0.0, 0.0], [0.0, 3.0, 0.0]]
    directions = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    twists = [0.0, 0.8]

    atoms = pdc_build.stamp(DRAFT, centres, directions, first_residue=10, entries=[entry, entry], twists=twists)

    assert [atom['name'] for atom in atoms] == ['TAIL1', 'HEAD', 'TAIL1', 'HEAD'], 'the topology names its beads'
    assert [atom['residue_id'] for atom in atoms] == [11, 11, 12, 12], 'one residue per molecule, after the protein'
    assert all(atom['residue'] == 'DDM' for atom in atoms)
    for index, (centre, direction, twist) in enumerate(zip(centres, directions, twists)):
        rotation = pdc_build._rotation(np.array([0.0, 0.0, 1.0]), np.asarray(direction, dtype=float))
        about_z = np.array([[np.cos(twist), -np.sin(twist), 0.0],
                            [np.sin(twist), np.cos(twist), 0.0], [0.0, 0.0, 1.0]])
        expected = np.asarray(centre) + (rotation @ about_z @ entry.T).T
        assert np.allclose([atom['position'] for atom in atoms[2 * index:2 * index + 2]], expected, atol=1e-5)
    assert np.allclose(atoms[1]['position'], centres[0]), 'the head anchor is the site'
    assert np.allclose(atoms[3]['position'], centres[1])
    untwisted = pdc_build.stamp(DRAFT, [centres[1]], [directions[1]], first_residue=10, entries=[entry],
                                twists=[0.0])
    assert not np.allclose(untwisted[0]['position'], atoms[2]['position']), 'the azimuth turns the body'


def test_an_entry_whose_bead_count_differs_is_refused_naming_both_counts():
    with pytest.raises(SystemExit) as caught:
        pdc_build.stamp(DRAFT, [[0.0, 0.0, 0.0]], [[0.0, 0.0, 1.0]], entries=[np.zeros((3, 3))], twists=[0.0])

    sentence = str(caught.value)
    assert '3' in sentence and '2' in sentence, sentence


def test_stamp_refuses_half_a_library_draw():
    entry = np.zeros((2, 3))
    with pytest.raises(SystemExit, match='entries and their twists'):
        pdc_build.stamp(DRAFT, [[0.0, 0.0, 0.0]], [[0.0, 0.0, 1.0]], entries=[entry])
    with pytest.raises(SystemExit, match='entries and their twists'):
        pdc_build.stamp(DRAFT, [[0.0, 0.0, 0.0]], [[0.0, 0.0, 1.0]], twists=[0.0])


def test_stamp_refuses_a_draw_that_does_not_name_every_site():
    entry = np.zeros((2, 3))
    with pytest.raises(SystemExit, match='one entry and one twist'):
        pdc_build.stamp(DRAFT, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
                        entries=[entry], twists=[0.0])


def library_profile(entry):
    """One library entry's profile, in the shape the library's pinned API states: head at the origin, axis +z."""
    points = np.asarray(entry, dtype=float)
    return {'offsets': points, 'axis': np.array([0.0, 0.0, 1.0]),
            'length_nm': float(-points[:, 2].min()), 'reach_nm': float(np.linalg.norm(points, axis=1).max()),
            'radial_nm': float(np.linalg.norm(points[:, :2], axis=1).max()), 'bead_count': int(len(points)),
            'source': 'conformations', 'head_source': 'library'}


class StubConformations:
    """What `Library.conformations()` hands the placement: a key, a size and one profile per entry."""

    def __init__(self, *, key, size, profiles):
        self.key, self.size, self.profiles = key, size, profiles


class StubLibrary:
    """`conformations.Library`'s pinned surface, so the build is tested without the library package existing."""

    def __init__(self, path, entries, *, key='librarykey012345', mismatch=None):
        self.path = Path(path)
        self.key = key
        self.size = len(entries)
        self.profiles = tuple(library_profile(entry) for entry in entries)
        self._offsets = np.asarray(entries, dtype=float)
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.mismatch = mismatch
        self.matched = None

    def offsets(self):
        return self._offsets

    def conformations(self):
        return StubConformations(key=self.key, size=self.size, profiles=self.profiles)

    def assert_matches(self, *, residue, beads, mapping_sha256):
        self.matched = {'residue': residue, 'beads': list(beads), 'mapping_sha256': mapping_sha256}
        if self.mismatch:
            raise ValueError(self.mismatch)


def fake_library(monkeypatch, library, *, load_error=None):
    """Stand the library package in where the build's lazy `from detergent_pdc import conformations` looks."""
    module = types.ModuleType('detergent_pdc.conformations')

    def load(path):
        if load_error:
            raise load_error
        return library

    module.load = load
    monkeypatch.setitem(sys.modules, 'detergent_pdc.conformations', module)
    monkeypatch.setattr(detergent_pdc, 'conformations', module, raising=False)


def name_library(stage, library, **overrides):
    """The settings lane 3's prepare writes for a library, on a stage that was built before it knew about one."""
    settings = json.loads((stage / pdc.SETTINGS_NAME).read_text())
    settings.update({'conformations_library': str(library.path),
                     'conformations_sha256': library.sha256,
                     'conformations_mapping_sha256': 'f' * 64,
                     'conformations_mode': 'build',
                     'conformations_runs': ['b920391735dd']})
    settings.update(overrides)
    (stage / pdc.SETTINGS_NAME).write_text(json.dumps(settings, indent=2, sort_keys=True))
    return settings


def gro_atoms(path):
    """The atoms in a `.gro` this stage wrote, read out of the fixed-width columns GROMACS itself reads."""
    lines = Path(path).read_text().splitlines()[2:-1]
    return [{'residue_id': int(line[:5]), 'residue': line[5:10].strip(), 'name': line[10:15].strip(),
             'position': np.array([float(line[20:28]), float(line[28:36]), float(line[36:44])])}
            for line in lines]


def test_the_build_stamps_the_librarys_drawn_entries(tmp_path, monkeypatch):
    """The library reaches the coordinates: matched against the model, drawn per site, stamped bead for bead."""
    stage = prepared_stage(tmp_path)
    library_file = tmp_path / 'library.json'
    library_file.write_text('{"format":"detergent-conformations-v1"}\n')
    library = StubLibrary(library_file, LIBRARY_ENTRIES)
    fake_library(monkeypatch, library)
    name_library(stage, library)

    code = pdc_build.build(stage)

    assert code == 0, json.loads((stage / pdc.REPORT_NAME).read_text())['reasons']
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert library.matched == {'residue': 'DDM', 'beads': ['TAIL1', 'HEAD'], 'mapping_sha256': 'f' * 64}, \
        "the library is matched against the run's own detergent model"
    record = report['conformations']
    assert record['key'] == library.key and record['size'] == library.size
    assert record['mode'] == 'build' and record['sources'] == ['b920391735dd']
    assert len(record['entries']) == 2 and len(record['twists']) == 2, 'one entry and one azimuth per molecule'

    atoms = gro_atoms(stage / 'system.gro')
    protein = [atom for atom in atoms if atom['residue'] == 'PRO']
    detergents = [atom for atom in atoms if atom['residue'] == 'DDM']
    assert len(protein) == 3 and [atom['name'] for atom in detergents] == ['TAIL1', 'HEAD'] * 2
    middle = np.mean([atom['position'] for atom in protein], axis=0)
    radius = report['placement_shell']['radius_nm']
    entry = np.asarray(LIBRARY_ENTRIES[0], dtype=float)
    heads = [atom['position'] for atom in detergents if atom['name'] == 'HEAD']
    tails = [atom['position'] for atom in detergents if atom['name'] == 'TAIL1']
    for index, (head, tail) in enumerate(zip(heads, tails)):
        span = np.linalg.norm(head - middle)
        assert span == pytest.approx(radius, abs=1e-3), 'the head end is the site the placement chose'
        direction = (head - middle) / span
        twist = record['twists'][index]
        about_z = np.array([[np.cos(twist), -np.sin(twist), 0.0],
                            [np.sin(twist), np.cos(twist), 0.0], [0.0, 0.0, 1.0]])
        rotation = pdc_build._rotation(np.array([0.0, 0.0, 1.0]), direction)
        assert np.allclose(tail, head + rotation @ about_z @ entry[0], atol=2e-3), \
            'the drawn body and its azimuth are the coordinates the build writes'


def test_a_library_whose_digest_is_not_the_runs_stops_the_build(tmp_path, monkeypatch):
    stage = prepared_stage(tmp_path)
    library_file = tmp_path / 'library.json'
    library_file.write_text('{"format":"detergent-conformations-v1"}\n')
    library = StubLibrary(library_file, LIBRARY_ENTRIES)
    fake_library(monkeypatch, library)
    name_library(stage, library, conformations_sha256='0' * 64)

    code = pdc_build.build(stage)

    assert code == 2
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['valid'] is False
    assert library.sha256 in report['reasons'][0] and '0' * 64 in report['reasons'][0]
    assert not (stage / 'system.gro').exists(), 'nothing is built on a library the run did not pin'


def test_a_library_that_does_not_match_the_runs_detergent_stops_the_build(tmp_path, monkeypatch):
    stage = prepared_stage(tmp_path)
    library_file = tmp_path / 'library.json'
    library_file.write_text('{"format":"detergent-conformations-v1"}\n')
    sentence = 'the library names 3 beads and this run names 2'
    library = StubLibrary(library_file, LIBRARY_ENTRIES, mismatch=sentence)
    fake_library(monkeypatch, library)
    name_library(stage, library)

    code = pdc_build.build(stage)

    assert code == 2
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['valid'] is False and report['reasons'] == [sentence]
    assert library.matched == {'residue': 'DDM', 'beads': ['TAIL1', 'HEAD'], 'mapping_sha256': 'f' * 64}
    assert not (stage / 'system.gro').exists()


def test_a_library_that_cannot_be_loaded_stops_the_build(tmp_path, monkeypatch):
    stage = prepared_stage(tmp_path)
    library_file = tmp_path / 'library.json'
    library_file.write_text('{"format":"detergent-conformations-v1"}\n')
    library = StubLibrary(library_file, LIBRARY_ENTRIES)
    fake_library(monkeypatch, library, load_error=ValueError(f'{library_file} is not a detergent-conformations-v1 '
                                                             'file'))
    name_library(stage, library)

    code = pdc_build.build(stage)

    assert code == 2
    report = json.loads((stage / pdc.REPORT_NAME).read_text())
    assert report['valid'] is False and 'conformations-v1' in report['reasons'][0]
