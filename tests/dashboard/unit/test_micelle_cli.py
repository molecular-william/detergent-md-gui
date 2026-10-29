"""The builder's own entry point: what a structure that states its membrane changes, and what it leaves alone.

The decisions are pinned here. A build writes a micelle, and that is what `test_micelle_job.py` and the pdc path
exercise; this is about the lines that turn a statement into a frame, a frame into an orientation report, and a
requested grompp into a verdict the report can hold.
"""
import argparse
import json
from pathlib import Path

from micelle import cli
from micelle.frame import frame_from_structure
from micelle.orientation import infer_orientation

PROTEIN = [[0.0, 0.0, -1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 3.0]]
# A tracked repository asset, and `validate_template` reports no issues for it -- so a build reaches its report.
TEMPLATE = Path('molecules/DDM/micelle_template.json')


def _arguments(structure, output, aggregation_number=4, mdp=None):
    return argparse.Namespace(template=str(TEMPLATE), protein=str(structure), aggregation_number=aggregation_number,
                              seed=7, output=str(output), radius=3.0, margin=2.0, box_shape='cubic', ions=0, mdp=mdp)


def test_the_heuristic_path_is_preserved_when_a_structure_states_nothing():
    """`None` is what keeps the principal-axis fallback and its 0.35 confidence exactly as they were."""
    assert cli.frame_metadata(None) is None


def test_the_metadata_is_what_the_orientation_then_reads():
    """The two halves have to agree: what the CLI builds is what `infer_orientation` consumes."""
    report = infer_orientation(PROTEIN, opm=cli.frame_metadata(frame_from_structure(1.18)))
    assert report.method == 'opm' and report.span == (-1.18, 1.18)


def test_a_structure_that_states_its_membrane_reaches_the_report(tmp_path):
    """End to end through the entry point: the file's own REMARK becomes a frame a run can be re-read against."""
    structure = tmp_path / 'stated.pdb'
    structure.write_text('REMARK      1/2 of bilayer thickness:   11.8\n'
                         'ATOM      1  N   ALA A   1       0.000   0.000  -1.000  1.00  0.00           N\n'
                         'ATOM      2  N   ALA A   1       0.000   0.000   1.000  1.00  0.00           N\n')
    output = tmp_path / 'built'

    code = cli.build(_arguments(structure, output))

    assert code == 0
    report = json.loads((output / 'validation' / 'validation.json').read_text())
    assert report['membrane']['half_thickness_nm'] == 1.18
    assert report['membrane']['source'] == 'stated.pdb REMARK'
    assert report['orientation']['method'] == 'opm'
    assert report['orientation']['span'] == [-1.18, 1.18]        # a tuple in the report, a list on disk
    assert report['orientation']['origin'] == [0.0, 0.0, 0.0]


def test_a_structure_that_states_nothing_builds_exactly_as_before(tmp_path):
    """The regression that makes this change reachable only by structures that measured themselves."""
    structure = tmp_path / 'plain.pdb'
    structure.write_text('ATOM      1  N   ALA A   1       0.000   0.000  -1.000  1.00  0.00           N\n'
                         'ATOM      2  N   ALA A   1       0.000   0.000   1.000  1.00  0.00           N\n')
    output = tmp_path / 'built'

    assert cli.build(_arguments(structure, output)) == 0
    report = json.loads((output / 'validation' / 'validation.json').read_text())
    assert report['membrane'] is None
    assert report['orientation']['method'] == 'heuristic'
    assert report['orientation']['span'] == [-1.0, 1.0]


def test_a_build_that_asks_for_grompp_reports_a_missing_gmx_rather_than_raising(tmp_path, monkeypatch):
    """`gmx` absent is a status the report carries, not an exception that costs a build its own report."""
    structure = tmp_path / 'plain.pdb'
    structure.write_text('ATOM      1  N   ALA A   1       0.000   0.000  -1.000  1.00  0.00           N\n'
                         'ATOM      2  N   ALA A   1       0.000   0.000   1.000  1.00  0.00           N\n')
    mdp = tmp_path / 'run.mdp'
    mdp.write_text('')
    output = tmp_path / 'built'
    monkeypatch.setenv('PATH', '')                # no `gmx` for the requested validation step to find

    assert cli.build(_arguments(structure, output, mdp=str(mdp))) == 0
    report = json.loads((output / 'validation' / 'validation.json').read_text())
    assert report['grompp'] == {'status': 'unavailable', 'error': 'gmx executable not found'}
