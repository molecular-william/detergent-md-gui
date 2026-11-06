"""Reading a GROMACS topology by section, once, for every in-package parser.

The stage scripts under `execution/scripts` are standalone and must not import this: they stay self-contained.

The differences that used to live in hand-rolled parsers -- whether the header is lowercased, which token of it
is the name, whether `#` lines count as content -- are settled here instead: a section name is the lowercased
first token inside the brackets, and every non-empty line with its inline `;` comment stripped is a content
line. Whether a `#` line is content or a directive stays the caller's decision, because callers differ.

`dashboard/models/bonded/__init__.py` deliberately does not import this: the file is copied alone into a run
directory as `bonded.py`, so it keeps its own self-contained parser.
"""


def _content_lines(text):
    """Every non-empty line with its inline `;` comment stripped, with its 1-based number."""
    for number, raw in enumerate(text.splitlines(), start=1):
        body = raw.split(';', 1)[0].strip()
        if body:
            yield number, body


def active_lines(text, defines=()):
    """Yield `(line_number, line)` for the lines in the live preprocessor branch.

    A topology is preprocessed by `grompp` before it is a table of terms: `#ifdef FLEXIBLE` / `#ifndef FLEXIBLE` /
    `#else` / `#endif` choose between alternative term sets. Fast_Forward writes one bond family under `#ifdef` and
    the same pair as a constraint under `#ifndef`, so a reader that treats a `#` line as content either trips over
    it or reads both alternatives and measures one term twice.

    The branch stack is `(parent_active, branch_taken)`, so nested blocks and `#else` work. `#define`/`#undef`
    inside a live branch update the set, because a topology may declare its own switches. A line is yielded only
    while the current branch is active, and its original number travels with it for the caller's error messages.
    """
    defined = set(defines)
    stack = []
    active = True
    for number, body in _content_lines(text):
        if body.startswith('#'):
            fields = body[1:].split()
            directive = fields[0].lower() if fields else ''
            argument = fields[1] if len(fields) > 1 else ''
            if directive in ('ifdef', 'ifndef'):
                branch = (argument in defined) == (directive == 'ifdef')
                stack.append((active, branch))
                active = active and branch
            elif directive == 'else' and stack:
                parent, branch = stack[-1]
                stack[-1] = (parent, not branch)
                active = parent and not branch
            elif directive == 'endif' and stack:
                active = stack.pop()[0]
            elif directive == 'define' and active and argument:
                defined.add(argument)
            elif directive == 'undef' and active and argument:
                defined.discard(argument)
            continue
        if active:
            yield number, body


def _sections(lines):
    """Group `(line_number, line)` pairs into `(name, rows)`, once per `[ ... ]` header."""
    name, rows = None, []
    for number, body in lines:
        if body.startswith('['):
            if name is not None:
                yield name, rows
            inside = body[1:body.index(']')] if ']' in body else body[1:]
            tokens = inside.split()
            name, rows = (tokens[0].lower() if tokens else ''), []
            continue
        if name is not None:
            rows.append((number, body))
    if name is not None:
        yield name, rows


def sections(text, defines=None):
    """Yield `(name, [(line_number, line), ...])`, once per `[ ... ]` header.

    `name` is the lowercased first token inside the brackets. Lines before the first header belong to no
    section and are not returned. A comment-only or blank line is not a content line; a header with no content
    is still yielded, with an empty list, so a caller rewriting the document keeps every section it had.
    Line numbers are 1-based over `text.splitlines()`, which is what the callers' error messages quote.

    `defines` is the caller's preprocessor decision. `None` keeps the historical reading, where a `#` line is
    content like any other; a tuple (including the empty tuple) evaluates the directives and returns only the live
    branch, with `active_lines`.
    """
    yield from _sections(active_lines(text, defines) if defines is not None else _content_lines(text))
