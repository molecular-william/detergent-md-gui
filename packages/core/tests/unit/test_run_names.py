"""One name for a run: the spelling, the slug and the uniqueness rule."""
import pytest
from dashboard import run_names


@pytest.mark.parametrize("name", [
    "0c5f5738089c", "Glucose-AA-201ns-4fs-20261116", "DDM_micelle_140_1us", "a", "a-b", "A_b-1", "x" * 80,
])
def test_a_run_name_accepts_the_old_hex_ids_and_the_labels_people_type(name):
    assert run_names.validate(name) == name


@pytest.mark.parametrize("name", [
    "", ".", "..", "../x", "a/b", "a b", "a.b", "-a", "a-", "a\nb", "a" * 81, "résumé", "a:b", ".retired",
])
def test_a_run_name_refuses_anything_that_could_escape_the_runs_directory(name):
    with pytest.raises(ValueError, match="run name"):
        run_names.validate(name)


def test_a_label_slugs_to_one_name():
    assert run_names.slug("DDM AA reference, 200 ns (matching)") == "DDM-AA-reference-200-ns-matching"
    assert run_names.slug("  Glucose--AA 201ns  ") == "Glucose-AA-201ns"
    assert run_names.slug("") == "run"
    assert len(run_names.slug("x" * 200)) == run_names.MAX


def test_uniqueness_suffixes_until_the_name_is_free_and_never_exceeds_the_length():
    taken = {"glucose-aa"}
    is_taken = lambda name: name.casefold() in taken
    second = run_names.unique("Glucose-AA", is_taken)
    assert second == "Glucose-AA-2", "the comparison is casefolded, the stored spelling is not"
    taken.add(second.casefold())
    assert run_names.unique("Glucose-AA", is_taken) == "Glucose-AA-3"
    long = run_names.unique("x" * 80, lambda name: name in {"x" * 80})
    assert len(long) == run_names.MAX and long.endswith("-2")
