"""The kind table as the layers read it: `default_for(run_type)` and the queue route's payload contract.

The coordinator queues `default_for(run_type)` beside `for_every_run()` when a run's stages finish, so a name that
leaves `default_for` is an analysis an AA-CG run stops publishing without anyone noticing.

One of these tests is about not being a second copy of a truth that lives elsewhere. The `payload` a kind declares
is what its queue route (`web/routes/analyses.py::queue_analysis`) actually validates, and the route is read here --
its source is parsed -- rather than restated, so the two cannot drift.
"""
import ast
import inspect
import textwrap

import pytest
from dashboard import features
from dashboard.analysis import kinds


def _payload_keys_read(node, name='payload'):
    """Every body key `node` reads from a `payload` object: `payload.get(k)`, `payload[k]`, `k in payload`.

    Deliberately narrow. A dict *literal* that writes into a new payload (`{**payload, 'molecule_id': ...}`)
    is a key the route produces, not one it demands, so it is not collected -- only reads are.
    """
    keys = set()
    for child in ast.walk(node):
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == 'get'
                and isinstance(child.func.value, ast.Name) and child.func.value.id == name
                and child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str)):
            keys.add(child.args[0].value)
        elif (isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name)
              and child.value.id == name and isinstance(child.slice, ast.Constant)
              and isinstance(child.slice.value, str)):
            keys.add(child.slice.value)
        elif (isinstance(child, ast.Compare) and isinstance(child.left, ast.Constant)
              and isinstance(child.left.value, str) and any(isinstance(op, ast.In) for op in child.ops)
              and any(isinstance(other, ast.Name) and other.id == name for other in child.comparators)):
            keys.add(child.left.value)
    return keys


@pytest.fixture(autouse=True)
def _installed_features():
    """The validation rows are registered by the feature, so the table is complete before a test reads it."""
    features.ensure()


def _validator_payload_keys():
    """Which kinds a feature supplies a body contract for, and the body keys its validator reads."""
    found = {}
    for name in kinds.TABLE:
        validator = features.kind_payload_for(name)
        if validator is None:
            continue
        function = ast.parse(textwrap.dedent(inspect.getsource(validator))).body[0]
        assert isinstance(function, ast.FunctionDef), f'{name}: the validator is no longer a plain function'
        found[name] = _payload_keys_read(function, 'body')
    return found


def test_the_two_kinds_with_a_payload_are_the_features_own():
    """The validation report and the mapping comparison: everything else takes any object.

    The mapping comparison reads nothing out of the body -- it derives its payload from the run -- so its entry is
    the empty set, which is why the assertion is over the names rather than over keys.
    """
    assert set(_validator_payload_keys()) == {'carbohydrate-validation', 'mapping-consistency'}


def test_default_for_aa_cg_is_the_two_checks_that_re_derive_the_fit():
    """D5: both read stages 2 and 3 only, so they run with every AA-CG run as analyses rather than inside a stage."""
    assert set(kinds.default_for('aa_cg')) == {'bonded-cross-check', 'dihedral-fit'}
    assert kinds.default_for('aa_cg') == [name for name, row in kinds.TABLE.items()
                                          if 'aa_cg' in row.default_for_run_types]
    for name in ('bonded-cross-check', 'dihedral-fit'):
        assert kinds.TABLE[name].default_for_run_types == ('aa_cg',), name
        assert all(source.startswith(('2_mapping/', '3_initial_CG/'))
                   for source in kinds.TABLE[name].sources), f'{name}: a source outside stages 2 and 3'


def test_the_kind_that_needs_a_cg_trajectory_defaults_to_no_run_type():
    """The counter-example the field's own sentence names: validation reads `4_CG_sim/prod/lig_CG.*`."""
    validation = kinds.TABLE['carbohydrate-validation']
    assert any(source.startswith('4_CG_sim/') for source in validation.sources)
    assert validation.default_for_run_types == ()
    assert 'carbohydrate-validation' not in kinds.default_for('aa_cg')


def test_a_kind_that_runs_for_every_run_is_not_also_a_run_type_default():
    """A kind in both facets would be queued twice by the coordinator, so the two are disjoint."""
    for name, row in kinds.TABLE.items():
        assert not (row.runs_for_every_run and row.default_for_run_types), name


def test_a_run_type_nobody_defaulted_a_kind_for_gets_an_empty_list():
    """Every run type but `aa_cg`: the ones that consume a pre-parameterized molecule fit nothing to check."""
    for run_type in ('aa_only', 'composition', 'pdc', 'not-a-run-type'):
        assert kinds.default_for(run_type) == [], run_type
