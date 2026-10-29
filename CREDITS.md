# Credits

Third-party methods this repository reimplements, and the people and projects they came from. What was *run* as a
tool rather than reimplemented is listed where it is configured -- `config/tools.json` and the docs beside each stage
-- with the resolved version recorded per run in that run's manifest.

## shaker

[shaker](https://github.com/Martini-Force-Field-Initiative/shaker) (Martini Force Field Initiative, LGPL-2.1, assessed
at commit `b7680219`) documents several workflows for building and judging coarse-grained models.
`docs/design/2026-10-05-shaker-and-taster-assessment.md` records what was assessed, area by area, and why.

**What was taken: the method, not the code.** No shaker source is copied, vendored or imported. Three analyses here
are reimplementations of workflows shaker documents, written from the documented method and validated against shaker's
own recorded output rather than trusted:

| our module | shaker's | reimplemented |
| --- | --- | --- |
| `dashboard/analysis/runs/overlap.py` | `overlap.py` | the overlap coefficient between two distributions |
| `dashboard/analysis/runs/bonded_estimate.py` | `estimator.py` | equipartition `k = R T / sigma^2` per term, with the constraint threshold as a stated parameter |
| `dashboard/analysis/runs/dihedral_fit.py` | `dihedral_fitting.py` | inverted Boltzmann, Savitzky-Golay smoothing, a cosine series, and AIC/BIC over the number of terms |

Each carries this credit in its module docstring, so it travels with the number it produced.

**The validation, because a credit is not evidence.** `bonded_estimate` was measured against shaker's own output on
the DDM 200 ns reference, on the same 20,001 frames at the same temperature: worst length disagreement 3.9 pm, worst
force-constant ratio 1.182, and every constraint verdict the same on both sides. The comparison and its limitations
are recorded under Task 3.2 of `docs/plans/2026-10-05-cross-check-analyses.md`.

**What was not taken** -- their mapper, topology writer, measurer, virtual-site solver and renderers -- each for a
reason recorded in the assessment note's area-by-area table. Two are worth repeating here: our mapper is a superset of
theirs (ring expansion and inter-ring link reconstruction, which shaker has no concept of), and our topology writer
carries per-term provenance that theirs has no place to put.
