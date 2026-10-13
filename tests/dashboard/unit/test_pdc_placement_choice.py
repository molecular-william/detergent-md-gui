"""The initialisation style has to survive the queue route, not only the browser.

`runs.py:queue` builds a job's settings from `set(adapter.settings_specs()) | set(adapter.choice_specs())`, so a key an
adapter does not advertise is dropped silently -- no error, just a job built on the default. The panel sent
`pdc_placement_mode` while pdc advertised only `SETTING_SPECS`, so choosing self-assembly produced a run that was built
on the lattice anyway. These tests hold both ends of that: the adapter advertises the choice, and the expression the
route uses keeps it.
"""
from dashboard.execution.adapters import pdc, pdc_placement


def test_the_adapter_advertises_the_placement_choice():
    choices = pdc.PROTOCOL.choice_specs()
    assert 'pdc_placement_mode' in choices
    label, options = choices['pdc_placement_mode']
    assert label, 'a choice with no label would render as nothing'
    assert tuple(options) == ('lattice', 'self-assembly')


def test_the_keys_the_queue_route_keeps_are_the_keys_the_panel_sends():
    """The route's own filter, spelled the way the route spells it."""
    kept = set(pdc.PROTOCOL.settings_specs()) | set(pdc.PROTOCOL.choice_specs())
    for key in ('pdc_placement_mode', 'pdc_seed', 'aggregation_number', 'pdc_assessment_ns', 'pdc_extension_ns'):
        assert key in kept, f'{key} would be dropped before the job was created'


def test_every_option_is_a_mode_the_placement_accepts():
    """An option the builder refuses would be a control that lies."""
    for mode in pdc.CHOICE_SPECS['pdc_placement_mode'][1]:
        assert pdc_placement.canonical_mode(mode) == mode
    assert set(pdc.CHOICE_SPECS['pdc_placement_mode'][1]) == {'lattice', 'self-assembly'}
