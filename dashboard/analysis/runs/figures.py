"""Which of a run's published figures a reader is being shown, and which were superseded.

A figure lives where its analysis published it -- `analyses/<kind>/<signature>/<attempt>/<output>/...` -- and every
attempt leaves its own copy beside the newer one. Measured on this workspace's own sucrose CG run: 38 images, 33 of
them the same three snapshot SVGs from eleven runs of the same analysis, so listing the index answers a question
nobody asked, and the picture a reader wants is buried among its own earlier selves.

The rule is the one the frame series already follows: the newest set of a given analysis kind is what the run
currently shows, and every earlier set stays on disk, reachable through the artifact index the Runs gallery reads.
A figure outside `analyses/` -- one a stage wrote as it ran -- belongs to no attempt and is always shown.
"""


def current_figures(entries):
    """`(kept, superseded)`: the figures to show, and how many published sets a newer one replaced.

    A "set" is one signature's figures: `analyses/<kind>/<signature>/...`. Two signatures of one kind are two
    different analyses (different settings, different payloads), and the newer of them is the one the run currently
    shows -- the same choice `snapshots` makes when it plays the newest frame series, and the older ones are counted
    rather than dropped in silence so a reader can go and look.
    """
    sets, loose = {}, []
    for entry in entries or ():
        parts = str(entry.get('path', '')).split('/')
        if len(parts) > 3 and parts[0] == 'analyses':
            sets.setdefault(parts[1], {}).setdefault('/'.join(parts[:3]), []).append(entry)
        else:
            loose.append(entry)
    kept, superseded = [], 0
    for kind in sorted(sets):
        signatures = sets[kind]
        newest = max(signatures, key=lambda signature: max(
            str(entry.get('modified_at') or '') for entry in signatures[signature]))
        for signature in sorted(signatures):
            if signature == newest:
                kept.extend(sorted(signatures[signature], key=lambda entry: str(entry.get('path'))))
            else:
                superseded += 1
    return kept + sorted(loose, key=lambda entry: str(entry.get('path'))), superseded
