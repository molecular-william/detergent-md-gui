"""The nonbonded and constraint settings one shared section of the New run form posts.

AA and CG runs expose the same physics knobs but read their reviewed values from different places: an AA run's
cut-offs and van der Waals treatment come from its force-field block (`forcefields.entry().mdp`), a CG run's from
its MDP profiles (`mdp.PROFILES[...].settings`). This module owns the one vocabulary -- bounds, choice lists, the
per-kind MDP names and the canonical spellings -- so the two adapters cannot drift apart, and the one checker for
the combinations GROMACS refuses.

`overrides` returns only the values a run changed from its reviewed default, which is what keeps an untouched run's
files byte-identical: a value equal to the reviewed one is omitted and the force-field block or profile keeps its
own line. `check` refuses the combinations `grompp` refuses, at the queue route rather than at prepare, and names
the setting the reader has to change.
"""

#: The settings each kind posts, in the form's order. The minimisation legs never receive them: they are a
#: dynamics-only set.
AA_FIELDS = ('rlist', 'rcoulomb', 'rvdw', 'rvdw_switch', 'vdwtype', 'vdw_modifier',
             'nsttcouple', 'nstpcouple', 'lincs_order', 'lincs_warnangle', 'lincs_iter')
CG_FIELDS = ('rlist', 'rcoulomb', 'rvdw', 'rvdw_switch', 'vdwtype', 'vdw_modifier',
             'coulombtype', 'epsilon_r', 'epsilon_rf',
             'nsttcouple', 'nstpcouple', 'lincs_order', 'lincs_warnangle')

#: (label, low, high) for each numeric setting, shared by both adapters. The labels are what a refusal names and
#: what the run's Stage settings read-back shows.
NUMERIC = {
    'rlist': ('Neighbour cut-off (nm)', 0.1, 5.0),
    'rcoulomb': ('Coulomb cut-off (nm)', 0.1, 5.0),
    'rvdw': ('van der Waals cut-off (nm)', 0.1, 5.0),
    'rvdw_switch': ('LJ switch start (nm)', 0.0, 5.0),
    'nsttcouple': ('Thermostat coupling interval (steps)', 1, 10000),
    'nstpcouple': ('Barostat coupling interval (steps)', 1, 10000),
    'lincs_order': ('LINCS order', 1, 12),
    'lincs_warnangle': ('LINCS warning angle (deg)', 0, 180),
    'lincs_iter': ('LINCS iterations', 1, 10),
    'epsilon_r': ('Relative permittivity (epsilon-r)', 0.0, 1000.0),
    'epsilon_rf': ('Reaction-field permittivity (epsilon-rf)', 0.0, 1000.0),
}

#: (label, options) for each choice setting. The option values are the form's, in lower case; `_SPELLING` writes
#: them in the spelling GROMACS' manual states.
CHOICES = {
    'vdwtype': ('van der Waals type', ('cutoff', 'pme')),
    'vdw_modifier': ('van der Waals modifier',
                     ('force-switch', 'potential-shift-verlet', 'potential-switch', 'none')),
    'coulombtype': ('Coulomb type', ('reaction-field', 'pme', 'cut-off')),
}

#: The counts among the settings above. They are advertised to `settings.normalize` so a fractional value is
#: refused by name rather than reaching an MDP as `12.5` steps.
INTEGRALS = {key: f'{key} must be an integer'
             for key in ('nsttcouple', 'nstpcouple', 'lincs_order', 'lincs_warnangle', 'lincs_iter')}

#: The MDP option each setting writes, per kind. The AA spelling of `vdwtype` is the force-field block's own; the CG
#: profiles spell it `vdw-type`. `writer.render` matches a variable option to whichever spelling the profile or
#: force-field block already states, so a run's value replaces that line rather than adding a second one.
AA_MDP = {
    'rlist': 'rlist', 'rcoulomb': 'rcoulomb', 'rvdw': 'rvdw', 'rvdw_switch': 'rvdw-switch',
    'vdwtype': 'vdwtype', 'vdw_modifier': 'vdw-modifier',
    'nsttcouple': 'nsttcouple', 'nstpcouple': 'nstpcouple',
    'lincs_order': 'lincs-order', 'lincs_warnangle': 'lincs-warnangle', 'lincs_iter': 'lincs-iter',
}
CG_MDP = {
    'rlist': 'rlist', 'rcoulomb': 'rcoulomb', 'rvdw': 'rvdw', 'rvdw_switch': 'rvdw-switch',
    'vdwtype': 'vdw-type', 'vdw_modifier': 'vdw-modifier',
    'coulombtype': 'coulombtype', 'epsilon_r': 'epsilon-r', 'epsilon_rf': 'epsilon-rf',
    'nsttcouple': 'nsttcouple', 'nstpcouple': 'nstpcouple',
    'lincs_order': 'lincs-order', 'lincs_warnangle': 'lincs-warnangle',
}

#: The spelling GROMACS documents for a changed choice. The form states the canonical lower case so the same
#: option value works for both kinds; the writer states the documented spelling.
_SPELLING = {
    'vdwtype': {'cutoff': 'Cut-off', 'pme': 'PME'},
    'vdw_modifier': {'force-switch': 'Force-switch', 'potential-shift-verlet': 'Potential-shift-verlet',
                     'potential-switch': 'Potential-switch', 'none': 'none'},
    'coulombtype': {'reaction-field': 'reaction-field', 'pme': 'PME', 'cut-off': 'cut-off'},
}


def numeric_specs(fields):
    """The numeric `SETTING_SPECS` entries one kind advertises."""
    return {key: NUMERIC[key] for key in fields if key in NUMERIC}


def choice_specs(fields):
    """The `CHOICE_SPECS` entries one kind advertises."""
    return {key: CHOICES[key] for key in fields if key in CHOICES}


def defaults(reviewed, mapping, fields):
    """The reviewed values a form starts from, in the form's own spelling.

    `reviewed` is the force-field block or MDP profile's settings, keyed by its own MDP spelling. A setting the
    reviewed source does not state has no default: the form leaves it blank and the run writes no line, which is
    how `nsttcouple` (GROMACS' `-1` rule) and the AA LINCS options stay the manual's default.
    """
    values = {}
    for setting in fields:
        value = reviewed.get(mapping[setting])
        if value is None:
            continue
        values[setting] = _canonical(setting, value)
    return values


def _canonical(setting, value):
    """A reviewed choice in the form's own option spelling; a number is left as it is."""
    if setting not in _SPELLING:
        return value
    folded = str(value).lower().replace('-', '').replace('_', '')
    for option in CHOICES[setting][1]:
        if option.lower().replace('-', '').replace('_', '') == folded:
            return option
    return str(value).lower()


def overrides(settings, reviewed, mapping, fields):
    """The MDP values a run changed, keyed by the MDP spelling, ready for `writer.render`.

    A value equal to the reviewed one is omitted on purpose: the profile or force-field block then renders its own
    line, so an untouched run's files stay byte-identical. A value the reviewed source does not state is written
    whenever the run names one.
    """
    values = {}
    for setting in fields:
        value = settings.get(setting)
        if value is None or value == '':
            continue
        mdp = mapping[setting]
        if _same(value, reviewed.get(mdp)):
            continue
        values[mdp] = _SPELLING.get(setting, {}).get(value, value)
    return values


def _same(value, reviewed):
    """Physics equality: `4` and `4.0` are one value, and a choice is compared without its case."""
    if reviewed is None:
        return False
    if isinstance(value, str) or isinstance(reviewed, str):
        return str(value).lower() == str(reviewed).lower()
    try:
        return float(value) == float(reviewed)
    except (TypeError, ValueError):
        return False


def check(settings, defaults, *, coulombtype):
    """Refuse the nonbonded combinations GROMACS refuses, naming the setting to change.

    The rules are `docs/plans/2026-11-18-new-run-nonbonded-and-constraints.md`'s, taken from the 2026-rc manual and
    `src/gromacs/gmxpreprocess/readir.cpp`. `settings` is the run's payload (or normalized result); `defaults` the
    reviewed values for the settings it does not name; `coulombtype` the effective `cutoff`/`reaction-field`/`PME`
    kind, which is not a setting of an AA run (it is always PME).
    """
    effective = {}
    for setting in set(settings) & (set(NUMERIC) | set(CHOICES)):
        if settings[setting] is not None and settings[setting] != '':
            effective[setting] = settings[setting]
    for setting, value in defaults.items():
        effective.setdefault(setting, value)

    rcoulomb, rvdw = effective.get('rcoulomb'), effective.get('rvdw')
    rlist = effective.get('rlist')
    if rlist is not None and rcoulomb is not None and rvdw is not None and rlist < max(rcoulomb, rvdw):
        raise ValueError(f'rlist ({rlist:g} nm) cannot be smaller than rvdw ({rvdw:g} nm) or '
                         f'rcoulomb ({rcoulomb:g} nm): with Verlet lists GROMACS refuses a neighbour list '
                         'inside a cut-off')
    if rcoulomb is not None and rvdw is not None and rcoulomb != rvdw:
        twin_range = (str(coulombtype).lower() == 'pme'
                      and str(effective.get('vdwtype', '')).lower() == 'cutoff'
                      and rcoulomb > rvdw)
        if not twin_range:
            raise ValueError(f'rcoulomb ({rcoulomb:g} nm) must equal rvdw ({rvdw:g} nm): GROMACS supports a '
                             'difference only for PME electrostatics with a cut-off van der Waals treatment '
                             'and rcoulomb > rvdw')

    vdwtype = str(effective.get('vdwtype', '')).lower()
    modifier = str(effective.get('vdw_modifier', '')).lower()
    if vdwtype == 'pme' and modifier not in ('none', 'potential-shift-verlet'):
        raise ValueError('van der Waals type PME supports only the potential-shift-verlet or none modifier, '
                         f'not {modifier}')
    if modifier in ('force-switch', 'potential-switch'):
        switch = effective.get('rvdw_switch')
        if switch is None or switch <= 0:
            raise ValueError(f'van der Waals modifier {modifier} needs an LJ switch start (rvdw_switch) '
                             'above 0 nm and below rvdw')
        if rvdw is not None and switch >= rvdw:
            raise ValueError(f'LJ switch start ({switch:g} nm) must be below rvdw ({rvdw:g} nm): GROMACS '
                             'refuses a switched potential whose switch does not end before the cut-off')

    if 'epsilon_rf' in effective or 'epsilon_r' in effective:
        epsilon_r = effective.get('epsilon_r', 15)
        epsilon_rf = effective.get('epsilon_rf', 0)
        if str(coulombtype).lower() != 'reaction-field':
            if epsilon_rf != 0:
                raise ValueError(f'epsilon-rf ({epsilon_rf:g}) is used only by reaction-field electrostatics; '
                                 f'this run is {coulombtype}')
        elif epsilon_rf != 0 and epsilon_rf < epsilon_r:
            raise ValueError(f'epsilon-rf ({epsilon_rf:g}) must be at least epsilon-r ({epsilon_r:g}), or 0 '
                             'for the reaction field at infinity')
