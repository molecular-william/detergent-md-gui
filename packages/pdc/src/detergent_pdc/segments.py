"""The protein-detergent trajectory as ordered segments: the system is rebuilt mid-run.

The removal path takes detergents out of the micelle and re-solvates what is left, so the atom count changes and the
legs on either side of that boundary are not the same system. Measured on `00b9ae6db23f`: the first four legs are
11,708 atoms, the extension is 10,427, and the final assessment re-declares the extension's trajectory rather than
writing a second. So a segment boundary is where the count changes, and a copy of another segment's bytes is dropped.
"""
from __future__ import annotations

from pathlib import Path

from dashboard.analysis.runs import layout
from dashboard.analysis.runs import segments as engine

#: `(human name, layout stage key, structure path inside the stage, trajectory paths inside the stage, note)`. The
#: stage key is looked up through the registered layout table, so the numbered directories and the legacy spellings
#: resolve to the same band; `structure` always names the stage's own output, so a picture and a trajectory come from
#: the same system.
STAGES = (
    ('System preparation', 'system', 'system.gro', None, 'the built system, before solvation'),
    ('Energy minimisation', 'minimisation', 'system.gro', ('system.xtc',), None),
    ('NVT equilibration', 'nvt', 'system.gro', ('system.xtc',), None),
    ('NPT equilibration', 'npt', 'system.gro', ('system.xtc',), None),
    ('CG assessment MD', 'assessment', 'prod/run.gro',
     ('prod/whole.xtc', 'prod/run.xtc'), 'PBC made whole where the stage wrote one'),
    ('Micelle assessment', 'micelle_assessment', 'kept.gro', None,
     'the system the assessment would keep; no trajectory of its own'),
    ('CG extension MD', 'extension', 'prod/run.gro',
     ('prod/whole.xtc', 'prod/run.xtc'), 'the system rebuilt after the removal path'),
    ('Final assessment', 'final_assessment', 'prod/run.gro',
     ('prod/whole.xtc', 'prod/run.xtc'), None),
    ('Back-mapping (CG2AT2)', 'backmap',
     ('FINAL/FINAL/final_cg2at_neutral.pdb', 'FINAL/FINAL/final_cg2at_de_novo.pdb'), None,
     'the atomistic complex converted back from the CG one'),
)

#: The stages a timed reel covers, in order; the final assessment re-declares the extension's trajectory.
TIMELINE_STAGES = ('Energy minimisation', 'NVT equilibration', 'NPT equilibration',
                   'CG assessment MD', 'CG extension MD')

#: The directories only a protein-detergent run writes; `04_nvt` alone is not a marker (an AA-only run has one).
MARKERS = ('08_extension', '06_assessment', '02_system', '03_minimisation', '07_micelle_assessment',
           '09_final_assessment', '10_backmap', '4_extension', '2_assessment', '3_nvt', '1_system')


def _stage_path(root, stage, names):
    for name in ((names,) if isinstance(names, str) else names or ()):
        found = layout.stage_path(root, stage, name)
        if found is not None:
            return found
    return None


def segments(root: Path) -> list[dict]:
    """The chain's trajectories in stage order, with duplicates and merge units made explicit."""
    root = Path(root)
    skipped = engine.skipped_stages(root)
    seen: dict[str, str] = {}
    group, previous_atoms = 0, None
    found = []
    for name, stage, structure_name, trajectory_names, note in STAGES:
        structure = _stage_path(root, stage, structure_name)
        reason = skipped.get(name)
        if structure is None:
            if reason is not None:
                found.append({'name': name, 'structure': None, 'atoms': None, 'trajectory': None,
                              'role': 'pdc', 'group': None, 'skipped': reason,
                              'note': f'skipped: {reason}'})
            continue
        count = engine.atoms(structure)
        trajectory = _stage_path(root, stage, trajectory_names)
        entry = {'name': name, 'structure': engine.relative(root, structure), 'atoms': count,
                 'trajectory': None, 'role': 'pdc', 'group': None}
        if note:
            entry['note'] = note
        if reason is not None:
            entry['skipped'] = reason
        if trajectory is not None:
            # Every candidate the stage holds is registered, not only the chosen one: the final assessment
            # re-declares the extension's raw run.xtc while the extension plays its whole.xtc, so a rule comparing
            # chosen files would call that pair different and play the same frames twice.
            keys = {}
            for option in trajectory_names or ():
                candidate = layout.stage_path(root, stage, option)
                if candidate is not None:
                    keys[engine.identity(candidate)] = candidate
            duplicate = next((seen[key] for key in keys if key in seen), None)
            if duplicate is not None:
                entry.update({'duplicate_of': duplicate, 'trajectory': engine.relative(root, trajectory)})
                entry['note'] = f'not a segment: the same trajectory as {duplicate}'
                found.append(entry)
                continue
            for key in keys:
                seen.setdefault(key, name)
            if count != previous_atoms:
                group += 1
            entry['trajectory'] = engine.relative(root, trajectory)
            entry['group'] = group
        found.append(entry)
        previous_atoms = count if trajectory is not None else previous_atoms
    return found


def register():
    """Give the engine this run type's segmenter and the directories that mark one of its runs on disk."""
    from dashboard.analysis.runs import segments as engine

    engine.register({'pdc': segments}, [('pdc', MARKERS)])
