"""Every `trjconv -center` in the pdc scripts is fed the two answers it asks for."""
import re

from tests.harness.support import PACKAGE

SCRIPTS = PACKAGE / 'execution/scripts'


def test_a_centering_trjconv_is_given_both_its_answers():
    """`-center` prompts twice -- which group to centre on, and which to write out.

    Measured: the assessment stage ran its production to completion (17,176 ns/day, a 28 MB trajectory) and then
    died at `gmx trjconv -pbc mol -center` with "Fatal error: Cannot read from input", because only one answer was
    piped in. The answer is the same group twice, which is what the CG path already does for its own trajectory.
    """
    checked = 0
    for script in sorted(SCRIPTS.glob('*.sh')):
        for line_number, line in enumerate(script.read_text().splitlines(), start=1):
            if 'gmx trjconv' not in line or '-center' not in line:
                continue
            checked += 1
            answers = len(re.findall(r'\\n', line.split('|')[0]))
            assert answers >= 2, f'{script.name}:{line_number} centres a trajectory with {answers} answer(s)'
    assert checked, 'no centering trjconv was found to check'
