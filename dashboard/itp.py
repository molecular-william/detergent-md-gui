"""Reading a GROMACS topology by section, once, for every in-package parser.

The stage scripts under `execution/scripts` are standalone and must not import this: they stay self-contained.

The differences that used to live in hand-rolled parsers -- whether the header is lowercased, which token of it
is the name, whether `#` lines count as content -- are settled here instead: a section name is the lowercased
first token inside the brackets, and every non-empty line with its inline `;` comment stripped is a content
line. Whether a `#` line is content or a directive stays the caller's decision, because callers differ.

`dashboard/models/bonded/__init__.py` deliberately does not import this: the file is copied alone into a run
directory as `bonded.py`, so it keeps its own self-contained parser.
"""


def sections(text):
    """Yield `(name, [(line_number, line), ...])`, once per `[ ... ]` header.

    `name` is the lowercased first token inside the brackets. Lines before the first header belong to no
    section and are not returned. A comment-only or blank line is not a content line; a header with no content
    is still yielded, with an empty list, so a caller rewriting the document keeps every section it had.
    Line numbers are 1-based over `text.splitlines()`, which is what the callers' error messages quote.
    """
    name, rows = None, []
    for number, raw in enumerate(text.splitlines(), start=1):
        body = raw.split(';', 1)[0].strip()
        if not body:
            continue
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
