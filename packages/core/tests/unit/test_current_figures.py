"""Which of a run's published figures a reader is shown: the newest set per analysis kind.

The defect this holds shut was visible on the page before it was visible in a test: a run's figure list showed the
same three snapshot SVGs once per attempt, because an analysis publishes its figures again every time it runs.
"""
from dashboard.analysis.runs.figures import current_figures


def figure(path, when='2026-10-01T00:00:00+00:00'):
    return {'path': path, 'modified_at': when}


def test_only_the_newest_set_of_a_kind_is_shown():
    older = figure('analyses/snapshots/aaaa/1111/output/x/snapshots/CG-first.svg', '2026-10-01T00:00:00+00:00')
    newer = figure('analyses/snapshots/bbbb/2222/output/y/snapshots/CG-first.svg', '2026-10-02T00:00:00+00:00')

    kept, superseded = current_figures([older, newer])

    assert [entry['path'] for entry in kept] == [newer['path']]
    assert superseded == 1


def test_each_analysis_kind_keeps_its_own_newest_set():
    """Two kinds are two answers; only repeats of one kind are the same picture twice."""
    snapshots = figure('analyses/snapshots/aaaa/1111/output/x/snapshots/CG-first.svg')
    validation = figure('analyses/carbohydrate-validation/cccc/3333/output/z/surface-comparison.html')

    kept, superseded = current_figures([snapshots, validation])

    assert sorted(entry['path'] for entry in kept) == sorted([snapshots['path'], validation['path']])
    assert superseded == 0


def test_a_figure_a_stage_wrote_belongs_to_no_attempt_and_is_always_shown():
    stage = figure('stages/5_assessment/score_matrix_LIG1.png')
    attempt = figure('analyses/snapshots/aaaa/1111/output/x/snapshots/CG-first.svg')

    kept, superseded = current_figures([stage, attempt])

    assert [entry['path'] for entry in kept] == [attempt['path'], stage['path']]
    assert superseded == 0


def test_a_rescored_assessment_shows_only_its_newest_attempt():
    """A re-score writes `stages/5_assessment@1/` beside the first attempt's `stages/5_assessment/`.

    Both hold a score matrix, a distance distribution and a diagnostic matrix, and only the newest is what the run
    currently shows -- the same rule the analysis kinds follow. The first attempt's pictures stay on disk and are
    counted, because "the run scored 0.00" is what a reader comparing a re-score with it came to see.
    """
    first = figure('stages/5_assessment/score_matrix_LIG1.png', '2026-10-01T00:00:00+00:00')
    rescored = figure('stages/5_assessment@1/score_matrix_LIG1.png', '2026-10-05T00:00:00+00:00')

    kept, superseded = current_figures([first, rescored])

    assert [entry['path'] for entry in kept] == [rescored['path']]
    assert superseded == 1


def test_the_attempt_number_orders_the_sets_and_not_the_file_name():
    """Attempt 10 is newer than attempt 9, and both are newer than the run's own first attempt."""
    entries = [figure('stages/5_assessment/score_matrix_LIG1.png'),
               figure('stages/5_assessment@9/score_matrix_LIG1.png'),
               figure('stages/5_assessment@10/score_matrix_LIG1.png')]

    kept, superseded = current_figures(entries)

    assert [entry['path'] for entry in kept] == ['stages/5_assessment@10/score_matrix_LIG1.png']
    assert superseded == 2


def test_a_run_in_the_older_layout_numbers_its_attempts_by_the_same_rule():
    """A run prepared before `stages/` keeps its stage directories at its root; attempt numbering is the same."""
    first = figure('5_assessment/score_matrix_LIG1.png')
    rescored = figure('5_assessment@1/score_matrix_LIG1.png')

    kept, superseded = current_figures([first, rescored])

    assert [entry['path'] for entry in kept] == [rescored['path']]
    assert superseded == 1


def test_a_numbered_pdc_final_assessment_numbers_its_attempts_by_the_same_rule():
    """A current pdc run's final assessment is `stages/09_final_assessment/`, and a re-score goes beside it."""
    first = figure('stages/09_final_assessment/assessment.json', '2026-10-01T00:00:00+00:00')
    rescored = figure('stages/09_final_assessment@1/assessment.json', '2026-10-05T00:00:00+00:00')

    kept, superseded = current_figures([first, rescored])

    assert [entry['path'] for entry in kept] == [rescored['path']]
    assert superseded == 1


def test_a_figure_outside_the_assessment_is_not_superseded_by_a_rescore():
    """The rule is about one stage's attempts, not about everything under `stages/`."""
    sasa = figure('stages/6_SASA/CG/SASA-CG.xvg.png')
    first = figure('stages/5_assessment/score_matrix_LIG1.png')
    rescored = figure('stages/5_assessment@1/score_matrix_LIG1.png')

    kept, superseded = current_figures([sasa, first, rescored])

    assert [entry['path'] for entry in kept] == ['stages/5_assessment@1/score_matrix_LIG1.png', sasa['path']]
    assert superseded == 1


def test_the_set_with_the_newest_file_wins_even_when_another_signature_has_one_too():
    """A signature's figures are written together, so the newest file in a set dates that set.

    Deliberately the case that reads backwards: the *older* signature here holds the newest file, and it is the one
    that wins -- a reader wants the set that was published last, not the one whose name sorts first.
    """
    latest = [figure('analyses/snapshots/aaaa/1111/output/x/snapshots/CG-first.svg', '2026-10-01T00:00:00+00:00'),
              figure('analyses/snapshots/aaaa/1111/output/x/snapshots/CG-last.svg', '2026-10-05T00:00:00+00:00')]
    earlier = [figure('analyses/snapshots/bbbb/2222/output/y/snapshots/CG-first.svg', '2026-10-03T00:00:00+00:00')]

    kept, superseded = current_figures(earlier + latest)

    assert [entry['path'] for entry in kept] == [entry['path'] for entry in latest], kept
    assert superseded == 1
