"""The MDP writer's contract with the template it is composed into.

The unit tests beside this one pin the values a particular run writes. The failure this covers is a
different and already-paid-for one: a key the template *already names*, written a second time by the
adapter, is refused by `grompp` as `doubly defined`, and a value stamped over a template's own is
invisible until the run reads the file -- which is how every CG run here came to be NVT with
`pcoupl = no` while its manifest recorded a barostat (`a20d844`). Reading the text back through the
module's own reader, rather than looking for a substring, is the check that does not depend on the
writer's spacing or key case.

Three properties over settings the adapter's own normalizer accepted:

1. every key in a written mdp appears exactly once -- the merge of the force-field block, the
   common block and the per-kind block cannot emit a duplicate;
2. every numeric value reads back, through `cg._mdp_value`, as the value that went in;
3. the coarse-grained half's own decisions hold for any step count: the timestep is stamped on the
   atomistic half only, and the barostat is never in the changes -- both standing decisions
   (`AGENTS.md`: CG production 20 fs, and `cg.py` no longer stamps `pcoupl`).
"""
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dashboard.execution.adapters import aa, cg

PROFILE = settings(max_examples=40, deadline=None,
                  suppress_health_check=(HealthCheck.too_slow, HealthCheck.function_scoped_fixture))
# `function_scoped_fixture` is suppressed because the one fixture used below (`tmp_path`) is not
# state the test reads between examples: each example writes its own mdp over the same path.

# The keys `mdp()` always writes a number to, whatever the kind: the merge's own arithmetic rather
# than a value the test chose.
NUMERIC_KEYS = ('nstlist', 'verlet-buffer-tolerance', 'ref-t', 'tau-t', 'dt', 'nsteps', 'nstenergy',
                'nstlog', 'tau-p', 'ref-p')
KINDS = ('em', 'ions', 'nvt', 'npt', 'production')
# What an integrating kind must carry for the loop below not to pass over an empty file: the
# timestep decision, the duration, and the coupling the template states.
INTEGRATING_KEYS = ('dt', 'nsteps', 'ref-t', 'tau-t')


def settings_for(temperature, production, interval=10.0):
    """Settings the adapter itself accepted -- drawn inside the bounds it publishes."""
    return aa.normalize_settings({'temperature_k': temperature, 'aa_production_ps': production,
                                  'output_interval_ps': interval})


def keys_of(text):
    """Every key the text assigns to, in order, with comments and blank lines dropped."""
    keys = []
    for line in text.splitlines():
        raw = line.split(';', 1)[0].strip()
        if '=' in raw:
            keys.append(raw.split('=', 1)[0].strip().lower())
    return keys


@given(kind=st.sampled_from(KINDS),
       temperature=st.floats(min_value=200, max_value=500, allow_nan=False, allow_infinity=False),
       production=st.floats(min_value=10, max_value=100000, allow_nan=False, allow_infinity=False))
def test_every_key_in_a_written_mdp_appears_exactly_once(kind, temperature, production):
    """A duplicate key is what `grompp` refuses as `doubly defined`, before anything runs."""
    text = aa.mdp(settings_for(temperature, production), kind)
    keys = keys_of(text)
    duplicates = sorted({key for key in keys if keys.count(key) > 1})

    assert duplicates == [], f'{kind} wrote {duplicates} twice'


@PROFILE
@given(kind=st.sampled_from(KINDS),
       temperature=st.floats(min_value=200, max_value=500, allow_nan=False, allow_infinity=False),
       production=st.floats(min_value=10, max_value=100000, allow_nan=False, allow_infinity=False))
def test_a_value_read_back_through_the_reader_is_the_value_that_went_in(kind, temperature, production, tmp_path):
    """Read with the module's own parser, not by looking for a substring: the formatting is its own.

    A key a kind does not write is skipped rather than required -- minimisation and the ion stage have
    no temperature and no timestep -- so the test states which keys the integrating kinds must carry,
    which is what keeps the loop from passing vacuously over an empty file.
    """
    text = aa.mdp(settings_for(temperature, production), kind)
    path = Path(tmp_path) / f'{kind}.mdp'
    path.write_text(text)
    keys = keys_of(text)
    if kind in ('nvt', 'npt', 'production'):
        assert set(INTEGRATING_KEYS) <= set(keys), f'{kind} is missing {set(INTEGRATING_KEYS) - set(keys)}'

    for key in set(NUMERIC_KEYS) & set(keys):
        written_value = cg_read(text, key)

        assert cg._mdp_value(path, key) == pytest.approx(float(written_value)), f'{kind}: {key}'


@PROFILE
@given(temperature=st.floats(min_value=200, max_value=500, allow_nan=False, allow_infinity=False),
       production=st.floats(min_value=10, max_value=100000, allow_nan=False, allow_infinity=False))
def test_the_integrator_duration_and_step_count_agree(temperature, production):
    """The two numbers a run's own record quotes: `nsteps * dt` is the duration, to the nearest step.

    The writer turns the requested duration into a whole number of steps, so the two agree to within
    half a step and never exactly -- the first version of this test asked for equality and failed on
    production 10.625 ps, where 5312.5 steps rounds to 5312 and 10.624 ps. The rounding is the code's
    rule; the tolerance is the test's, and half a step is the largest gap it can leave.
    """
    dt = 0.002
    adapter_settings = settings_for(temperature, production)
    text = aa.mdp(adapter_settings, 'production')
    steps = float(cg_read(text, 'nsteps'))

    assert steps >= 1, 'a run always integrates at least one step'
    assert abs(float(cg_read(text, 'dt')) * steps - production) <= dt / 2 + 1e-9


@PROFILE
@given(folder=st.sampled_from(('aa', 'cg')), steps=st.integers(min_value=0, max_value=10**9))
def test_the_timestep_and_the_barostat_stay_where_the_decisions_put_them(folder, steps):
    """The timestep is stamped on the atomistic half only, and `pcoupl` is never stamped at all."""
    aa_dir = Path('/run/1_AA-reference')
    changes = cg.mdp_integration(aa_dir if folder == 'aa' else Path('/run/4_CG_sim/inputs'), aa_dir, steps)

    assert changes['nsteps'] == steps
    assert ('dt' in changes) is (folder == 'aa'), 'only the atomistic half is stamped with a timestep'
    assert 'pcoupl' not in changes, 'the template states the barostat; this must not override it'


def cg_read(text, key):
    """One key's value out of an mdp's text, using the same spelling rule the reader uses."""
    for line in text.splitlines():
        raw = line.split(';', 1)[0].strip()
        if '=' in raw and raw.split('=', 1)[0].strip().lower() == key.lower():
            return raw.split('=', 1)[1].strip()
    raise AssertionError(f'{key} is missing from the mdp')
