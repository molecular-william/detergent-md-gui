"""MkVsites derivation from synthetic ITP/RTP fixtures and the packaged DDM topology.

The expected virtual-site numbers are computed by hand from the formulas in the module
docstring, not by calling the module: the fixture's masses, bond lengths and angle are chosen
to give the constants below.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from dashboard.cli import derive_vsites
from dashboard.models.molecules import vsites

from tests.harness.support import PROJECT_ROOT

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'vsites'
ITP = FIXTURES / 'methyl_hydroxyl.itp'
RTP = FIXTURES / 'lig.rtp'
FF = FIXTURES / 'ff'
DDM_ITP = PROJECT_ROOT / 'molecules' / 'DDM' / 'results' / 'MMFF' / 'lig1.itp'

#: Hand-computed from mTot = 12 + 3*1, dHy = 0.109*sin(109.4712206), I = 3*1*dHy^2,
#: dDummy = 2*sqrt(I/mTot), dX = (12*0.150 + 1*3*(0.150 + 0.109/3))/mTot.
DUMMY_DISTANCE = 0.09191687067512362
ANCHOR_DISTANCE = 0.16384438415530056
#: b0 = sqrt((0.143 + 0.096*cos(108.5))^2 + (0.096*sin(108.5))^2).
OH_DISTANCE = 0.19590027219546738


def variant(tmp_path: Path, text: str, name: str = 'variant.itp') -> Path:
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


def without_lines(text: str, *needles: str) -> str:
    return ''.join(line for line in text.splitlines(keepends=True)
                   if not any(needle in line for needle in needles))


def test_the_synthetic_methyl_and_hydroxyl_constructs_are_derived():
    result = vsites.derive_from_itp(ITP)

    assert result['source']['kind'] == 'itp'
    assert result['source']['moleculetype'] == 'MOL'
    assert len(result['source']['sha256']) == 64
    assert result['diagnostics'] == []

    assert len(result['vsites']) == 1
    vsite = result['vsites'][0]
    assert vsite['name'] == 'MCH3_1'
    assert vsite['center'] == 'CT1'
    assert vsite['heavy'] == 'CT2'
    assert vsite['nH'] == 3
    assert vsite['count'] == 2
    assert vsite['atoms'] == [[1, 5, 2, 3, 4], [8, 5, 9, 10, 11]]
    assert vsite['dummy_mass'] == pytest.approx(7.5)
    assert vsite['dummy_distance_nm'] == pytest.approx(DUMMY_DISTANCE, rel=1e-12)
    assert vsite['anchor_distance_nm'] == pytest.approx(ANCHOR_DISTANCE, rel=1e-12)

    assert len(result['angle_constraints']) == 1
    constraint = result['angle_constraints'][0]
    assert constraint['heavy'] == 'CT2'
    assert constraint['hydrogen'] == 'HO'
    assert constraint['count'] == 1
    assert constraint['atoms'] == [[5, 7]]
    assert constraint['distance_nm'] == pytest.approx(OH_DISTANCE, rel=1e-12)

    assert result['forcefield'] == {
        'constraints': ['MCH3_1 MCH3_1 2 0.091917', 'MCH3_1 CT2 2 0.163844'],
        'angle_constraints': ['CT2 HO 2 0.195900'],
        'dummy_masses': ['MCH3_1 0 0.000000 0.00 A 0.0 0.0'],
        'atomtypes': ['MCH3_1 0.00000'],
        'vsd': ['CT1 CT2 MCH3_1'],
    }


def test_identical_constructs_share_a_type_and_a_different_geometry_gets_a_suffix(tmp_path):
    text = ITP.read_text(encoding='utf-8').replace(
        '   8  9 1 0.109 300000', '   8  9 1 0.112 300000')
    result = vsites.derive_from_itp(variant(tmp_path, text))

    assert [vsite['name'] for vsite in result['vsites']] == ['MCH3_1', 'MCH3_2']
    assert [vsite['count'] for vsite in result['vsites']] == [1, 1]
    assert result['vsites'][1]['atoms'] == [[8, 5, 9, 10, 11]]
    assert result['forcefield']['vsd'] == ['CT1 CT2 MCH3_1', 'CT1 CT2 MCH3_2']


def test_an_underivable_construct_is_a_warning_not_an_exception(tmp_path):
    text = without_lines(ITP.read_text(encoding='utf-8'), '   2  1  5 ', '   3  1  5 ', '   4  1  5 ')
    result = vsites.derive_from_itp(variant(tmp_path, text))

    assert len(result['vsites']) == 1
    assert result['vsites'][0]['atoms'] == [[8, 5, 9, 10, 11]]
    messages = [item['message'] for item in result['diagnostics']]
    assert any('atom 1' in message and 'underivable' in message for message in messages)
    assert all(item['level'] == 'warning' for item in result['diagnostics'])


def test_a_non_funct_one_term_is_a_diagnostic_and_does_not_crash(tmp_path):
    text = ITP.read_text(encoding='utf-8').replace(
        '   5  6  7 1 108.5 400', '   5  6  7 2 108.5 400')
    result = vsites.derive_from_itp(variant(tmp_path, text))

    assert result['angle_constraints'] == []
    assert result['forcefield']['angle_constraints'] == []
    assert any('funct 2' in item['message'] for item in result['diagnostics'])
    assert len(result['vsites']) == 1


def test_an_alien_atom_type_is_refused_by_name(tmp_path):
    text = without_lines(ITP.read_text(encoding='utf-8'), ' CT2    6 ')
    with pytest.raises(vsites.VsiteError, match='CT2'):
        vsites.derive_from_itp(variant(tmp_path, text))


def test_a_missing_inline_atomtype_can_come_from_the_force_field(tmp_path):
    text = without_lines(ITP.read_text(encoding='utf-8'), ' CT2    6 ')
    result = vsites.derive_from_itp(variant(tmp_path, text), FF)

    assert result['vsites'][0]['dummy_distance_nm'] == pytest.approx(DUMMY_DISTANCE, rel=1e-12)
    assert result['angle_constraints'][0]['distance_nm'] == pytest.approx(OH_DISTANCE, rel=1e-12)


def test_inline_terms_win_over_force_field_types(tmp_path):
    forcefield = tmp_path / 'ff'
    forcefield.mkdir()
    for name in ('ffnonbonded.itp', 'ffbonded.itp'):
        (forcefield / name).write_text((FF / name).read_text(encoding='utf-8'), encoding='utf-8')
    (forcefield / 'ffbonded.itp').write_text(
        (forcefield / 'ffbonded.itp').read_text(encoding='utf-8').replace(
            ' CT1 HC  1 0.109', ' CT1 HC  1 0.120'), encoding='utf-8')

    result = vsites.derive_from_itp(ITP, forcefield)

    assert result['vsites'][0]['dummy_distance_nm'] == pytest.approx(DUMMY_DISTANCE, rel=1e-12)


@pytest.mark.parametrize('replacement,match', [
    ('   1  2 1 -0.109 300000', 'negative'),
    ('   1  2 1 nan 300000', 'not finite'),
])
def test_negative_or_nonfinite_distances_are_refused(tmp_path, replacement, match):
    text = ITP.read_text(encoding='utf-8').replace('   1  2 1 0.109 300000', replacement)
    with pytest.raises(vsites.VsiteError, match=match):
        vsites.derive_from_itp(variant(tmp_path, text))


def test_duplicate_atom_numbers_are_refused(tmp_path):
    text = ITP.read_text(encoding='utf-8').replace(
        '    3 HC   1 MOL H2 1 0.0  1.0', '    2 HC   1 MOL H2 1 0.0  1.0')
    with pytest.raises(vsites.VsiteError, match='duplicate atom number 2'):
        vsites.derive_from_itp(variant(tmp_path, text))


def test_a_gap_in_atom_numbering_is_refused(tmp_path):
    text = without_lines(ITP.read_text(encoding='utf-8'), '    3 HC   ')
    with pytest.raises(vsites.VsiteError, match='contiguous'):
        vsites.derive_from_itp(variant(tmp_path, text))


def test_a_bond_to_a_missing_atom_is_refused(tmp_path):
    text = ITP.read_text(encoding='utf-8').replace('   1  2 1 0.109 300000', '   1 99 1 0.109 300000')
    with pytest.raises(vsites.VsiteError, match='missing atom 99'):
        vsites.derive_from_itp(variant(tmp_path, text))


def test_derive_text_hashes_the_text_and_matches_the_file_route():
    text = ITP.read_text(encoding='utf-8')
    result = vsites.derive_text(text)

    assert result['source']['sha256'] == hashlib.sha256(text.encode('utf-8')).hexdigest()
    assert result['vsites'] == vsites.derive_from_itp(ITP)['vsites']


def test_derive_file_infers_the_rtp_kind():
    result = vsites.derive_file(RTP, force_field=FF, residue='LIG')

    assert result['source']['kind'] == 'rtp'
    assert result['vsites'][0]['name'] == 'MCH3_1'


def test_rtp_reads_missing_terms_from_the_force_field():
    result = vsites.derive_from_rtp(RTP, 'LIG', FF)

    assert result['source']['kind'] == 'rtp'
    assert result['source']['moleculetype'] == 'LIG'
    assert result['diagnostics'] == []
    assert result['vsites'][0]['dummy_distance_nm'] == pytest.approx(DUMMY_DISTANCE, rel=1e-12)
    assert result['vsites'][0]['anchor_distance_nm'] == pytest.approx(ANCHOR_DISTANCE, rel=1e-12)
    assert result['angle_constraints'][0]['distance_nm'] == pytest.approx(OH_DISTANCE, rel=1e-12)


def test_rtp_without_a_force_field_cannot_supply_atom_types():
    with pytest.raises(vsites.VsiteError, match='atomtypes'):
        vsites.derive_from_rtp(RTP, 'LIG')


def test_rtp_residue_must_exist():
    with pytest.raises(vsites.VsiteError, match="residue 'NOPE' not found"):
        vsites.derive_from_rtp(RTP, 'NOPE', FF)


def test_cli_writes_sorted_json_to_stdout(capsys):
    code = derive_vsites.main(['--itp', str(ITP)])

    assert code == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert captured.out == json.dumps(parsed, indent=2, sort_keys=True) + '\n'
    assert parsed['vsites'][0]['name'] == 'MCH3_1'
    assert captured.err == ''


def test_cli_writes_a_file_and_prints_nothing(tmp_path, capsys):
    target = tmp_path / 'vsites.json'
    code = derive_vsites.main(['--itp', str(ITP), '--out', str(target)])

    assert code == 0
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == ''
    assert json.loads(target.read_text(encoding='utf-8'))['vsites'][0]['name'] == 'MCH3_1'


def test_cli_returns_two_for_an_unreadable_topology(tmp_path, capsys):
    code = derive_vsites.main(['--itp', str(tmp_path / 'missing.itp')])

    assert code == 2
    assert 'cannot read topology' in capsys.readouterr().err


def test_cli_returns_two_for_an_unresolved_include(tmp_path, capsys):
    bad = variant(tmp_path, '#include "forcefield.itp"\n[ moleculetype ]\nMOL 1\n')
    code = derive_vsites.main(['--itp', str(bad)])

    assert code == 2
    assert 'preprocessor directive' in capsys.readouterr().err


def test_cli_returns_two_when_an_rtp_lacks_a_force_field(capsys):
    code = derive_vsites.main(['--rtp', str(RTP), '--residue', 'LIG'])

    assert code == 2
    assert 'requires --force-field' in capsys.readouterr().err


def test_cli_returns_two_for_a_mismatched_residue_option(capsys):
    code = derive_vsites.main(['--itp', str(ITP), '--residue', 'LIG'])

    assert code == 2
    assert 'only valid with --rtp' in capsys.readouterr().err


def test_cli_keeps_exit_zero_for_an_underivable_construct(tmp_path, capsys):
    text = without_lines(ITP.read_text(encoding='utf-8'), '   2  1  5 ', '   3  1  5 ', '   4  1  5 ')
    path = variant(tmp_path, text)
    code = derive_vsites.main(['--itp', str(path)])

    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert any('underivable' in item['message'] for item in result['diagnostics'])


def test_cli_help_names_the_force_field_destinations():
    help_text = derive_vsites.build_parser().format_help()

    for name in ('ffbonded.itp', 'ffnonbonded.itp', 'atomtypes.atp', '.vsd'):
        assert name in help_text


def test_the_packaged_ddm_topology_has_a_methyl_vsite_and_a_hydroxyl_constraint():
    result = vsites.derive_from_itp(DDM_ITP)

    assert any(vsite['name'].startswith('MCH3') for vsite in result['vsites'])
    assert any(constraint['heavy'] == 'CR' and constraint['hydrogen'] == 'HOR'
               for constraint in result['angle_constraints'])
    methyl = result['vsites'][0]
    assert methyl['count'] == 1
    assert methyl['atoms'] == [[1, 2, 36, 37, 38]]
    assert methyl['dummy_distance_nm'] == pytest.approx(0.09179535444791292, rel=1e-12)
    assert methyl['anchor_distance_nm'] == pytest.approx(0.16502684202735918, rel=1e-12)
    assert result['angle_constraints'][0]['count'] == 7
    assert result['angle_constraints'][0]['atoms'] == [
        [17, 65], [24, 71], [26, 73], [28, 75], [30, 77], [32, 79], [34, 81]]
