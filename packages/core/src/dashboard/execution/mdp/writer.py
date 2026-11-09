"""The single MDP writer: a reviewed physics profile plus the run's own numbers.

Phase 3 of `docs/plans/2026-10-27-run-lifecycle-refactor.md` replaces copied-and-patched MDP files with MDPs
written from here. Every setting a stage does not vary with the run lives in a named profile in `profiles.py`,
commented with the source it comes from. A run supplies only its own numbers and the name of the profile it used,
which the run records so that its physics is identifiable after the fact.

`values` maps GROMACS option names to the run's numbers in the option they belong to (`nsteps`, `gen-seed`, `ref-t`,
`nstxtcout`, ...). It is not a second profile: a key the profile does not own is refused, so a caller cannot smuggle
physics past the reviewed table, and a profile setting of `None` is a number the run must supply, so a file cannot be
rendered with a missing one. A profile's `variable` entries are the options the New run form owns as overrides: they
keep a reviewed default (so an untouched run renders the reviewed file) and take the run's number only when it names
one. The writer does not guess a derivation: duration to steps is rounded differently per
stage today (`round`, `ceil`, `max(1, round(...))`), and that arithmetic belongs to the adapter that knows which leg
it is preparing.

Formatting is the format today's runs were prepared with: floats as `%.12g`,
integers verbatim, booleans as `yes`/`no`, and an empty string as an empty value -- `define = ` with the trailing
space, which is how a cleared `define` is written.

"""
from dataclasses import dataclass
from pathlib import Path

from .. import forcefields


@dataclass(frozen=True)
class Profile:
    """One reviewed MDP, versioned by name.

    `settings` is the whole file in order, with `None` where the run supplies the number. `comments` is keyed by
    setting name and rendered on that line. `source` says where the science comes from, and `version` is the name a
    run records -- the same string `PROFILES` is keyed by, so a run's record cannot name a profile that does not exist.

    `variable` names the options whose reviewed value a run may replace -- the numbers the New run form offers as
    overrides. They are not `None`: the profile still states a reviewed default, so an untouched run renders exactly
    the reviewed file, and only a run that supplied one changes it. A variable key the profile does not state (such
    as `rlist`, which the CG production profile deliberately leaves to GROMACS) is appended when a run supplies it,
    and absent otherwise. Every other fixed setting stays the reviewed physics.

    `force_field` is true for a profile whose force-field block is the registry's, read at render time: the block is
    not baked in here, because a run's force field is a choice recorded in its manifest. The block's constraint set is
    the run's too: the entry's value is the default, and a run that names `constraints` replaces it.
    """

    settings: dict
    comments: dict
    source: str
    version: str
    force_field: bool = False
    notes: tuple = ()
    variable: tuple = ()


def formatted(value):
    """One value in the form the current code writes it."""
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, float):
        return f'{value:.12g}'
    if isinstance(value, int):
        return str(value)
    return str(value)


def resolve(profile):
    """A `Profile` for a name, so a caller may record the name and render from it."""
    if isinstance(profile, Profile):
        return profile
    from .profiles import PROFILES
    try:
        return PROFILES[profile]
    except KeyError:
        raise ValueError(f'unknown MDP profile {profile!r}; known: {", ".join(sorted(PROFILES))}') from None


def render(profile, values=None):
    """The complete, commented MDP file for one profile at one run's numbers."""
    profile = resolve(profile)
    values = dict(values or {})
    # The run's numbers are the settings the profile left as None, the options it marks variable, and nothing else: a
    # value the profile fixes is the reviewed physics, and a caller overriding it would be running one profile under
    # another's name.
    run_keys = {key for key, value in profile.settings.items() if value is None} | set(profile.variable)
    if profile.force_field:
        # The force-field block's two run-scoped options: which entry, and its constraint set. The entry is the
        # default for both; a run that names a different constraint set (the manual's `h-bonds`, or `none` for a
        # diagnostic) replaces the entry's own, and the run records the value it used.
        run_keys |= {'force_field', 'constraints'}
    foreign = sorted(set(values) - run_keys)
    if foreign:
        raise ValueError(f"{profile.version} takes no run value for {', '.join(foreign)}; its settings are the "
                         "reviewed physics, and only its None entries and variable options are the run's")
    settings = {}
    header = [f'; {profile.version}: reviewed physics profile, dashboard/execution/mdp/profiles.py',
              f'; source: {profile.source}']
    if profile.force_field:
        entry = forcefields.entry(values.get('force_field'))
        settings.update(entry.mdp)
        settings['constraints'] = values.get('constraints', entry.constraints)
        header.append(f'; force-field block: {entry.name} (dashboard.execution.forcefields.entry at render time)')
    for key, default in profile.settings.items():
        settings[key] = values.get(key, default)
    # A variable option the profile does not state has no reviewed default to keep; the run either names it or the
    # line is absent, which is what `rlist` wants (GROMACS sizes the list from the Verlet tolerance).
    for key in profile.variable:
        if key in settings:
            continue
        if key in values:
            settings[key] = values[key]
    missing = [key for key in profile.settings if settings[key] is None]
    if missing:
        raise ValueError(f"{profile.version} needs the run's own numbers for: {', '.join(missing)}")
    lines = header + ['']
    for key, value in settings.items():
        line = f'{key} = {formatted(value)}'
        comment = profile.comments.get(key)
        lines.append(f'{line}  ; {comment}' if comment else line)
    if profile.notes:
        lines += [''] + [f'; {note}' for note in profile.notes]
    return '\n'.join(lines) + '\n'


def write_mdp(profile, path, values=None):
    """Write one profile's MDP to `path` and return the path written."""
    path = Path(path)
    path.write_text(render(profile, values))
    return path
