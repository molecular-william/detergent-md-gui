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
