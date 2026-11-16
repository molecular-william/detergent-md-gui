"""A run is normally named already: its name is its label, and a retired name is never handed to a second run."""
from dashboard import run_names


def row(name):
    return {'id': name, 'label': name, 'status': 'completed', 'created': '2026-11-16T00:00:00+00:00'}


def test_a_claim_slugs_the_label_and_never_reuses_a_live_name(dashboard):
    coordinator = dashboard.coordinator
    first = coordinator._claim_name('Glucose AA 200ns 20261116')
    assert first == 'Glucose-AA-200ns-20261116'
    coordinator.database().insert(row(first))
    assert coordinator._claim_name('Glucose AA 200ns 20261116') == first + '-2'


def test_the_comparison_is_casefolded_so_a_copy_of_the_workspace_cannot_collide(dashboard):
    coordinator = dashboard.coordinator
    coordinator.database().insert(row('Glucose-AA'))
    assert coordinator._claim_name('glucose-aa') == 'glucose-aa-2'


def test_a_deleted_name_is_retired_rather_than_offered_again(dashboard):
    coordinator = dashboard.coordinator
    coordinator.database().insert(row('DDM-AA'))
    coordinator.database().delete_with_cleanup('DDM-AA', lambda: None)
    assert 'DDM-AA' in coordinator.database().retired_names()
    assert coordinator._claim_name('DDM-AA') == 'DDM-AA-2'


def test_only_a_callers_invalid_name_is_refused_by_the_shared_validator():
    for bad in (".", "..", "a/b", ""):
        try:
            run_names.validate(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
