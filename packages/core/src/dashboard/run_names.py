"""One name for a run: its directory, its row id and its URL segment.

A run used to be addressed by a random 12-hex id, which was a name in everything but intent: the runs list showed it,
a URL carried it and a revision recorded it. This module makes the name the identity and keeps the two properties the
old shape had for free -- a strict character class, so a name can never escape ``runs/``, collide with a URL or carry
markup, and one name per run, compared casefolded because a workspace can be copied to a filesystem that is not.

The pattern is a strict superset of the 12-hex ids, which is what lets the runs already on disk keep their directories
while new runs are named: ``validate`` accepts both, and nothing renames anything. Uniqueness is casefolded: SQLite's
primary key is case-sensitive, so ``Glucose-AA`` and ``glucose-aa`` would both insert and then collide on a case-
insensitive copy of the workspace.
"""
import re

#: A run name. Alphanumeric ends, letters/digits/underscore/dash inside, 1-80 characters. At 80 it matches the other
#: path components this repository names (a molecule id, a composition id, a detergent code) and leaves room for
#: ``runs/<name>/analyses/<kind>/<attempt>/...`` beneath it.
NAME = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9_-]{0,78}[A-Za-z0-9])?')
MAX = 80
#: A name a run may not take. Retired names are stored beside the jobs; this only reserves the store's own spelling.
RESERVED = frozenset({'.retired'})


def validate(name, *, what='A run name') -> str:
    """The name, or a refusal naming the rule.

    Every gate calls this -- the path resolver, the web view, adoption, a reference, a fit, a revision's aa_reference.
    One rule, because a name that the resolver accepts and the view refuses is a run that exists and cannot be seen.
    """
    if not isinstance(name, str) or name in RESERVED or not NAME.fullmatch(name):
        raise ValueError(f'{what} must be 1-{MAX} letters, digits, "-" or "_", starting and ending with a letter or '
                         'digit')
    return name


def slug(label) -> str:
    """The name a label suggests: runs of anything else become one dash, and the ends stay alphanumeric.

    The panel suggests ``<molecule>-<AA|CG>-<Nns>-<YYYYMMDD>``; a label a person typed (``DDM AA reference, 200 ns``)
    becomes ``DDM-AA-reference-200-ns``. An empty or unusable label becomes ``run``, which ``unique`` then suffixes.
    """
    text = re.sub(r'[^A-Za-z0-9_-]+', '-', str(label or '').strip())
    text = re.sub(r'-{2,}', '-', text).strip('-_')[:MAX].strip('-_')
    return text or 'run'


def unique(base, is_taken, *, limit=1000) -> str:
    """The first free name from ``base``: the base itself, then ``base-2``, ``base-3`` ...

    ``is_taken`` answers whether a name is already used or retired, and is the caller's predicate because the live
    names and the retired ones live in different tables: this module owns the spelling, not the store.
    """
    root = slug(base)
    for suffix in range(1, limit + 1):
        tail = '' if suffix == 1 else f'-{suffix}'
        stem = root[:MAX - len(tail)].rstrip('-_') or 'run'
        candidate = f'{stem}{tail}'
        if NAME.fullmatch(candidate) and not is_taken(candidate):
            return candidate
    raise ValueError(f'No free run name for {root!r}')
