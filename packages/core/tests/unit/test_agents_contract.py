"""What AGENTS.md may contain, enforced rather than trusted.

The file had grown to 181 lines by restating what `PROJECT_GUIDE.md` and `HANDOFF.md` already carry, and the
restatement had gone stale in a way nobody noticed: two bullets said the CG Bond Interactions panel deletes the
mapping, one said in bold that it deletes the parameterization. A budget alone would not have caught that, but a
budget plus "invariants name code or a pointer" catches both -- prose that belongs in a guide has nowhere to point.
"""

from __future__ import annotations

import re

import pytest

from tests.harness.support import PROJECT_ROOT

ROOT = PROJECT_ROOT
AGENTS = ROOT / 'AGENTS.md'

HUMAN_BUDGET = 150
MAX_LINES_PER_BULLET = 4
HEADINGS = (
    '# Project guidance for coding agents',
    '## What belongs in this file',
    '## Goal',
    '## Where things are',
    '## Run contract',
    '## Invariants',
    '## Engineering rules',
    '## Do not',
    '## Standing decisions',
    '## Verify',
)
POINTERS = ('PROJECT_GUIDE', 'HANDOFF', 'DDM_CALIBRATION')
DATE = re.compile(r'\b20\d\d-\d\d-\d\d\b')


def _section(lines: list[str], heading: str) -> list[str]:
    start = lines.index(heading) + 1
    rest = [i for i, line in enumerate(lines[start:], start) if line.startswith('## ')]
    return lines[start:rest[0] if rest else len(lines)]


def _bullets(section: list[str]) -> list[list[str]]:
    bullets: list[list[str]] = []
    for line in section:
        if line.startswith('- '):
            bullets.append([line])
        elif bullets and line.startswith('  ') and line.strip():
            bullets[-1].append(line)
    return bullets


@pytest.fixture(scope='module')
def lines():
    return AGENTS.read_text().rstrip('\n').splitlines()


def test_agents_stays_within_its_budget(lines):
    """The budget is the ratchet. A line that must be added here has to displace one, or move to a guide."""
    assert len(lines) <= HUMAN_BUDGET, (
        f'AGENTS.md carries {len(lines)} lines, budget {HUMAN_BUDGET}. A rule, an invariant, a decision or a '
        'command belongs here; how a subsystem works belongs in docs/PROJECT_GUIDE.md, state and incidents in '
        'docs/HANDOFF.md, and scoring science in docs/DDM_CALIBRATION.md -- with one line and a pointer kept here.'
    )


def test_agents_keeps_a_fixed_set_of_headings(lines):
    """A new section is a decision about the file's shape, not something to add while writing a paragraph."""
    found = [line for line in lines if line.startswith('#')]
    assert found == list(HEADINGS), (
        'AGENTS.md headings changed. The allowed set is: ' + ', '.join(HEADINGS)
    )


def test_every_invariant_names_code_or_a_pointer(lines):
    """An invariant says what must not break and where the reasoning lives; if it can name neither, it is prose."""
    bullets = _bullets(_section(lines, '## Invariants'))
    assert bullets, 'the Invariants section is empty'
    for group in bullets:
        joined = ' '.join(group)
        assert '`' in joined or any(name in joined for name in POINTERS), (
            f'invariant names no code and points at no document: {group[0][:90]}'
        )


def test_invariants_stay_short_and_undated(lines):
    """Dated incident narrative is HANDOFF's; a date here means the line is a story, and the story has a home."""
    for group in _bullets(_section(lines, '## Invariants')):
        assert len(group) <= MAX_LINES_PER_BULLET, (
            f'invariant runs to {len(group)} lines; move the detail to a guide: {group[0][:90]}'
        )
        assert not DATE.search(' '.join(group)), (
            f'invariant carries a date, so it is narrative rather than a rule: {group[0][:90]}'
        )
