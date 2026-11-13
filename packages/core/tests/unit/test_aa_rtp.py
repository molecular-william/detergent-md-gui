"""The ITP -> RTP bridge for pdb2gmx vsite construction."""
import pytest
from dashboard.models.molecules import rtp

ITP = """
[ atomtypes ]
C 6 12.011 0.0 A 0.3 0.2
H 1 1.008 0.0 A 0.2 0.1
O 8 15.999 0.0 A 0.3 0.6
[ moleculetype ]
LIG1 3
[ atoms ]
1 C 1 LIG1 C 1 0.2
2 H 1 LIG1 H1 2 0.1
3 H 1 LIG1 H2 3 0.1
4 H 1 LIG1 H3 4 0.1
5 C 1 LIG1 C2 5 0.2
6 O 1 LIG1 O 6 -0.4
7 H 1 LIG1 HO 7 0.3
[ bonds ]
1 2 1 0.109 1000 0.109 1000
1 5 1 0.153 900 0.153 900
5 6 1 0.143 800 0.143 800
6 7 1 0.097 700 0.097 700
[ angles ]
2 1 5 1 109.5 100 109.5 100
1 5 6 1 112.0 100 112.0 100
5 6 7 1 108.0 100 108.0 100
[ dihedrals ]
1 2 5 6 9 0.0 1.0 1 180.0 2.0 2
[ dihedrals ]
1 2 3 4 2 0.0 1.0 0.0 1.0
"""


def test_the_rtp_drops_the_repeated_funct_one_parameters():
    text = rtp.from_itp(ITP, residue='LIG1')
    assert '[ LIG1 ]' in text
    assert 'C H1 0.109 1000' in text, 'one b0/kb pair, not the ITP duplicate'
    assert 'C H1 1 0.109' not in text, 'the function type comes from [ bondedtypes ]'
    assert 'H1 C C2 109.5 100' in text
    assert 'C H1 C2 O 9' not in text, 'dihedral rows omit the function field too'
    assert 'C H1 C2 O 0.0 1.0 1 180.0 2.0 2' in text
    assert 'HO' in text and 'O' in text


def test_a_funct_one_dihedral_is_refused_because_bondedtypes_has_nine():
    text = ITP.replace('1 2 5 6 9', '1 2 5 6 1').replace('0.0 1.0 1 180.0 2.0 2', '0.0 1.0')
    with pytest.raises(rtp.RtpError, match='dihedrals use function type 1'):
        rtp.from_itp(text, residue='LIG1')


def test_an_existing_virtual_site_is_refused():
    with pytest.raises(rtp.RtpError, match='already has virtual_sites'):
        rtp.from_itp(ITP + '\n[ virtual_sitesn ]\n1 2 1 2\n', residue='LIG1')


def test_a_term_naming_a_missing_atom_is_refused():
    text = ITP.replace('1 5 1 0.153', '1 9 1 0.153')
    with pytest.raises(rtp.RtpError, match='outside'):
        rtp.from_itp(text, residue='LIG1')
