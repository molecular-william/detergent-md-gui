"""The kind table as the other two layers read it: `published()` and `default_for(run_type)`.

The web layer's `GET /api/analysis-kinds` serialises `published()` and the coordinator queues `default_for(run_type)`
beside `for_every_run()` when a run's stages finish, so both are seam functions rather than conveniences: a key that
changes shape here is a change to the control, and a name that leaves `default_for` is an analysis an AA-CG run stops
publishing without anyone noticing.

Two of these tests are about not being a second copy of a truth that lives elsewhere. The `payload` a kind publishes
is what its queue route (`web/routes/analyses.py::queue_analysis`) actually validates, and the route is read here --
its source is parsed -- rather than restated, so the two cannot drift: a branch the route gains, or a body key it
stops reading, fails this file and points at the declaration in `kinds._PAYLOAD`.
"""
import ast
import inspect
import json
import textwrap

from dashboard.analysis import kinds
from dashboard.web.routes import analyses as analyses_routes

#: The keys of one published row, as the seam block in the plan names them. Written literally rather than derived:
#: this is the contract the web layer serialises, so it must be read here in the words both sides agreed on.
SEAM_KEYS = {'name', 'label', 'inputs', 'payload', 'runs_for_every_run', 'default_for_run_types', 'summary'}


def _payload_keys_read(node):
    """Every body key `node` reads from a `payload` object: `payload.get(k)`, `payload[k]`, `k in payload`.

    Deliberately narrow. A dict *literal* that writes into a new payload (`{**payload, 'molecule_id': ...}`)
    is a key the route produces, not one it demands, so it is not collected -- only reads are.
    """
    keys = set()
    for child in ast.walk(node):
        if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == 'get'
                and isinstance(child.func.value, ast.Name) and child.func.value.id == 'payload'
                and child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str)):
            keys.add(child.args[0].value)
        elif (isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name)
              and child.value.id == 'payload' and isinstance(child.slice, ast.Constant)
              and isinstance(child.slice.value, str)):
            keys.add(child.slice.value)
        elif (isinstance(child, ast.Compare) and isinstance(child.left, ast.Constant)
              and isinstance(child.left.value, str) and any(isinstance(op, ast.In) for op in child.ops)
              and any(isinstance(other, ast.Name) and other.id == 'payload' for other in child.comparators)):
            keys.add(child.left.value)
    return keys


def _route_payload_keys():
    """Which kinds `queue_analysis` branches on, and the body keys each branch reads, read off the route's source."""
    function = ast.parse(textwrap.dedent(inspect.getsource(analyses_routes.queue_analysis))).body[0]
    assert isinstance(function, ast.FunctionDef), 'the queue route is no longer a plain function'
    branches = {}
    for statement in function.body:
        test = getattr(statement, 'test', None)
        if (isinstance(statement, ast.If) and isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name) and test.left.id == 'kind'
                and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
                and isinstance(test.comparators[0], ast.Constant) and isinstance(test.comparators[0].value, str)):
            branches[test.comparators[0].value] = _payload_keys_read(statement)
    assert branches, (
        'the queue route no longer branches on `kind == <name>`, so its body contract cannot be read from it. '
        'Re-read `web/routes/analyses.py` and update `kinds._PAYLOAD` and this reader together.')
    return branches


def test_published_writes_the_whole_table_in_order_with_exactly_the_seam_keys():
    rows = kinds.published()
    assert [row['name'] for row in rows] == list(kinds.TABLE)
    assert len(rows) == len(kinds.TABLE)
    for row in rows:
        assert set(row) == SEAM_KEYS, f'{row["name"]}: keys {sorted(set(row) ^ SEAM_KEYS)} differ from the seam'


def test_every_value_a_published_row_carries_is_a_plain_json_type():
    """No dashboard object leaks into the response the control reads: a tuple is not what a template can index."""
    rows = kinds.published()
    for row in rows:
        name = row['name']
        assert isinstance(name, str) and isinstance(row['label'], str) and isinstance(row['summary'], str), name
        assert isinstance(row['runs_for_every_run'], bool), name
        for key in ('inputs', 'default_for_run_types'):
            assert isinstance(row[key], list) and all(isinstance(item, str) for item in row[key]), f'{name}: {key}'
        assert row['payload'] is None or (
            isinstance(row['payload'], list) and row['payload']
            and all(isinstance(item, str) for item in row['payload'])), f'{name}: payload'
    assert json.loads(json.dumps(rows)) == rows, 'published() carries something json cannot write and read back'


def test_a_published_row_reads_the_table_rather_than_a_second_copy_of_it():
    published = {row['name']: row for row in kinds.published()}
    for name, row in kinds.TABLE.items():
        entry = published[name]
        assert entry['label'] == row.title, name
        assert entry['inputs'] == list(row.sources), name
        assert entry['summary'] == row.ideal_result, name
        assert entry['runs_for_every_run'] == row.runs_for_every_run, name
        assert entry['default_for_run_types'] == list(row.default_for_run_types), name


def test_every_published_payload_is_the_payload_its_queue_route_validates():
    """A wrong `payload` is a button the control offers and the worker refuses, so it is read off the route."""
    route_keys = _route_payload_keys()
    published = {row['name']: row['payload'] for row in kinds.published()}
    for name in kinds.TABLE:
        expected = sorted(route_keys.get(name, ())) or None
        actual = sorted(published[name]) if published[name] is not None else None
        assert actual == expected, (
            f'{name}: kinds._PAYLOAD says {actual}, the queue route validates {expected}. '
            'Read `web/routes/analyses.py::queue_analysis` and change the declaration, not this test.')
    # And the other direction: a branch the table does not carry is a kind the control cannot name its arguments for.
    assert set(route_keys) == {name for name, payload in published.items() if payload is not None}


def test_the_only_kind_with_a_payload_is_the_validation_report():
    """Measured, not guessed: only this branch reads the body at all; everything else takes any object."""
    assert set(_route_payload_keys()) == {'carbohydrate-validation'}


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
