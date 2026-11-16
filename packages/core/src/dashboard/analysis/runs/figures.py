"""Which of a run's published figures a reader is being shown, and which were superseded.

A figure lives where its analysis published it: `analyses/<kind>/<NNNN>-<YYYYMMDD>/<output>/...`, where the
sequenced attempt is its own published set and another run of the analysis is another answer. A stable kind publishes
one set at its kind root (`analyses/frame-series`), which is a record rather than an attempt.

Every attempt leaves its own copy beside the newer one. Measured on this workspace's own sucrose CG run: 38 images,
33 of them the same three snapshot SVGs from eleven runs of the same analysis, so listing the index answers a
question nobody asked, and the picture a reader wants is buried among its own earlier selves.

The rule is the one the frame series already follows: the newest set of a given analysis kind is what the run
currently shows, and every earlier set stays on disk, reachable through the artifact index the Runs gallery reads.

A figure outside `analyses/` -- one a stage wrote as it ran -- belongs to no analysis attempt and is otherwise always
shown, with one exception that is the same rule applied to a stage: an assessment a run re-scored leaves
`stages/5_assessment@1/` beside the first `stages/5_assessment/`, and both hold a score matrix, a distance
distribution and a diagnostic matrix. A numbered run's final assessment is `09_final_assessment`, re-scored as
`09_final_assessment@<n>`. Only the newest attempt's are what the run currently shows; the earlier ones stay on disk
and are counted, because a reader comparing a re-score with what it replaced needs to reach the old pictures rather
than have them disappear.
"""

import re

#: A sequenced attempt directory: `NNNN-YYYYMMDD`. The coordinator mints the next number per run and kind, so the
#: directory an attempt lives in is the directory a reader is shown.
SEQUENCE = re.compile(r'^(\d{4,})-(\d{8})$')

#: A figure one assessment attempt wrote: a CG run's `5_assessment` or a numbered run's `09_final_assessment`,
#: and a re-score's `@<n>` beside either. The `stages/` prefix is optional because the layout written before
#: `layout_version` 2 kept the stage directories at the run's root, and an attempt directory is created where the
#: stage root is.
ASSESSMENT_ATTEMPT = re.compile(r'^(?:stages/)?(?:09_final_assessment|5_assessment)(?:@(\d+))?/')

#: What a reader sees in the figure viewer: an image. An analysis may publish an interactive HTML artifact (the
#: overlap heatmap, an older surfaces comparison), but that is an artifact served by its own route, not a figure.
FIGURE_SUFFIXES = ('.png', '.svg')


def attempts(paths):
    """The analysis attempts these run-relative paths belong to, one entry per attempt.

    `{attempt directory: {'kind', 'published', 'paths'}}`. An attempt is
    `analyses/<kind>/<NNNN>-<YYYYMMDD>/...`: it is its own published set, the newest attempt of a kind is the answer
    a reader is shown, and each attempt stays reachable on disk. Anything else under `analyses/` -- a stable kind's
    published root, a file a stage wrote -- is not an attempt here.

    One reader uses this to find the attempts that hold a published `result.json`, another to decide which published
    set a figure belongs to, so the two readers cannot disagree about the shapes a run may hold.
    """
    found = {}
    for path in paths or ():
        parts = str(path).split('/')
        if len(parts) < 4 or parts[0] != 'analyses' or SEQUENCE.fullmatch(parts[2]) is None:
            continue
        attempt = '/'.join(parts[:3])
        entry = found.setdefault(attempt, {'kind': parts[1], 'published': attempt, 'paths': []})
        entry['paths'].append(str(path))
    return found


def current_figures(entries):
    """`(kept, superseded)`: the figures to show, and how many published sets a newer one replaced.

    A "set" is the directory an analysis published into: one sequenced attempt. Two sets of one kind are two
    different analyses (different settings, different payloads), and the newer of them is the one the run currently
    shows -- the newest series in the index, and the older ones are counted rather than dropped in silence so a
    reader can go and look.

    An assessment attempt is a set by the same reading: `stages/5_assessment` is attempt 0 and `stages/5_assessment@n`
    is attempt n, the newest one is what the run currently shows, and each earlier one is counted as superseded.
    """
    entries = list(entries or ())
    directories = attempts(str(entry.get('path', '')) for entry in entries)
    published = {path: (info['kind'], info['published'])
                 for info in directories.values() for path in info['paths']}
    sets, loose = {}, []
    for entry in entries:
        key = published.get(str(entry.get('path', '')))
        if key is None:
            loose.append(entry)
        else:
            kind, directory = key
            sets.setdefault(kind, {}).setdefault(directory, []).append(entry)
    kept, superseded = [], 0
    for kind in sorted(sets):
        groups = sets[kind]
        newest = max(groups, key=lambda directory: max(
            str(entry.get('modified_at') or '') for entry in groups[directory]))
        for directory in sorted(groups):
            if directory == newest:
                kept.extend(sorted(groups[directory], key=lambda entry: str(entry.get('path'))))
            else:
                superseded += 1
    assessments = {}
    for entry in loose:
        match = ASSESSMENT_ATTEMPT.match(str(entry.get('path', '')))
        if match:
            assessments.setdefault(int(match.group(1) or 0), []).append(entry)
    shown = loose
    if assessments:
        newest = max(assessments)
        shown = []
        for entry in loose:
            match = ASSESSMENT_ATTEMPT.match(str(entry.get('path', '')))
            if match is None or int(match.group(1) or 0) == newest:
                shown.append(entry)
        superseded += len(assessments) - 1
    return kept + sorted(shown, key=lambda entry: str(entry.get('path'))), superseded
