"""One selector for "which ITP is this run's CG model", with the provenance an analysis reports."""
from pathlib import Path

import pytest

from dashboard.analysis.runs import layout


def test_the_fitted_interaction_topology_wins_over_a_draft_and_a_seed():
    """The ranking three modules used to spell out: a fitted model first, then the draft geometry, then the rest."""
    ranked = layout.rank_model([Path('X_initial.itp'), Path('X_ff_inter.itp'), Path('X_seed.itp')])

    assert [path.name for path in ranked] == ['X_ff_inter.itp', 'X_initial.itp', 'X_seed.itp']


def test_a_recorded_name_is_the_answer_when_the_run_states_one(tmp_path):
    """`cg_names` is what the run itself wrote; it outranks any ranking of the directory."""
    stage = tmp_path / '3_initial_CG'
    stage.mkdir(parents=True)
    for name in ('DDM_ff_inter.itp', 'DDM_initial.itp'):
        (stage / name).write_text('[ moleculetype ]\nDDM 1\n')

    path, provenance = layout.model_topology(tmp_path, name='DDM_initial.itp')

    assert path.name == 'DDM_initial.itp'
    assert 'recorded' in provenance


def test_a_run_with_neither_a_fit_nor_a_draft_says_so_in_the_readers_words(tmp_path):
    (tmp_path / '3_initial_CG').mkdir()

    with pytest.raises(ValueError) as refused:
        layout.model_topology(tmp_path)

    assert 'neither a fit nor a draft' in str(refused.value)
