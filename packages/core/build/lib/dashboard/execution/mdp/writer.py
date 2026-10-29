"""The single MDP writer: a reviewed physics profile plus the run's own numbers.

Phase 3 of `docs/plans/2026-10-27-run-lifecycle-refactor.md` replaces copied-and-patched MDP files with MDPs
written from here. Every setting a stage does not vary with the run lives in a named profile in `profiles.py`,
commented with the source it comes from. A run supplies only its own numbers and the name of the profile it used,
which the run records so that its physics is identifiable after the fact.

`values` maps GROMACS option names to the run's numbers in the option they belong to (`nsteps`, `gen-seed`, `ref-t`,
`nstxtcout`, ...). It is not a second profile: a key the profile does not own is refused, so a caller cannot smuggle
physics past the reviewed table, and a profile setting of `None` is a number the run must supply, so a file cannot be
rendered with a missing one. The writer does not guess a derivation: duration to steps is rounded differently per
stage today (`round`, `ceil`, `max(1, round(...))`), and that arithmetic belongs to the adapter that knows which leg
it is preparing.

Formatting is the format today's runs were prepared with (`environment.update_mdp` and `aa.mdp`): floats as `%.12g`,
integers verbatim, booleans as `yes`/`no`, and an empty string as an empty value -- `define = ` with the trailing
space, which is what `update_mdp` writes for a cleared define.

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

    `force_field` is true for a profile whose force-field block is the registry's, read at render time: the block is
    not baked in here, because a run's force field is a choice recorded in its manifest.
    """

    settings: dict
    comments: dict
    source: str
    version: str
    force_field: bool = False
    notes: tuple = ()


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
    # The run's numbers are the settings the profile left as None, and nothing else: a value the profile fixes is the
    # reviewed physics, and a caller overriding it would be running one profile under another's name.
    run_keys = {key for key, value in profile.settings.items() if value is None}
    if profile.force_field:
        run_keys.add('force_field')
    foreign = sorted(set(values) - run_keys)
    if foreign:
        raise ValueError(f"{profile.version} takes no run value for {', '.join(foreign)}; its settings are the "
                         "reviewed physics, and only its None entries are the run's")
    settings = {}
    header = [f'; {profile.version}: reviewed physics profile, dashboard/execution/mdp/profiles.py',
              f'; source: {profile.source}']
    if profile.force_field:
        entry = forcefields.entry(values.get('force_field'))
        settings.update(entry.mdp)
        settings['constraints'] = entry.constraints
        header.append(f'; force-field block: {entry.name} (dashboard.execution.forcefields.entry at render time)')
    for key, default in profile.settings.items():
        settings[key] = values.get(key, default)
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
