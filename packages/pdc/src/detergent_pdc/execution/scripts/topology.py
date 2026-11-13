"""The GROMACS topology and run-settings readers every pdc stage script shares.

Five stage scripts used to carry their own [ section ] splitter, three their own settings loader, and each had
drifted a little -- one kept inline comments, one accepted a row the others skipped. A stage runs as
'python -m detergent_pdc.execution.scripts.<stage>', so the helper is importable exactly as the adapters are.
"""
from __future__ import annotations

import json
from pathlib import Path


def sections(text: str) -> dict[str, list[str]]:
    """Every [ section ] of an itp/top as its data lines, comments and blanks stripped.

    A line is stripped of its ';' comment before the section rule is applied, so a commented-out directive is
    data nowhere. Header lines are not returned: '[ molecules ]' is the key 'molecules'.
    """
    found: dict[str, list[str]] = {}
    name = ''
    for raw in str(text).splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            name = line[1:-1].strip().lower()
            found.setdefault(name, [])
            continue
        found.setdefault(name, []).append(line)
    return found


def molecule_rows(text: str, *, source: str = 'the topology', strict: bool = False) -> list[tuple[str, int]]:
    """Every readable [ molecules ] row as (name, count), in the order the file writes them.

    'strict' is the build's rule: a row it cannot read is refused rather than skipped, because a half-understood
    topology produces a system grompp refuses after a stage has already run. A row is data only when its count
    column is a signed integer.
    """
    rows = []
    for line in sections(text).get('molecules', []):
        fields = line.split()
        if len(fields) < 2 or not fields[1].lstrip('-').isdigit():
            if strict:
                raise SystemExit(f'{source} lists a [ molecules ] row this stage cannot read: {line!r}')
            continue
        rows.append((fields[0], int(fields[1])))
    return rows


def molecule_name(text: str) -> str:
    """The molecule a topology declares, because [ molecules ] has to spell it exactly."""
    lines = str(text).splitlines()
    for index, line in enumerate(lines):
        stripped = line.split(';', 1)[0].strip()
        if stripped.startswith('[') and stripped.lower().startswith('[ moleculetype'):
            for following in lines[index + 1:]:
                content = following.split(';', 1)[0].strip()
                if content:
                    return content.split()[0]
    raise SystemExit('a topology without a [ moleculetype ] name cannot be listed in [ molecules ]')


def read_settings(path, *, description: str = 'its decisions') -> dict:
    """A stage's pdc-settings.json, refused rather than defaulted when the run left none."""
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f'{path} is missing: this stage reads {description} from it')
    return read_json(path)


def read_json(path) -> dict:
    """One JSON record, read as written."""
    return json.loads(Path(path).read_text())
