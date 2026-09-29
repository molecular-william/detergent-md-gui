"""The consistency comparison as one analysis: three sections, one result, nothing approved.

The other analyses each answer one question. This one answers the question the mapping exists for — does the
model we simulate reproduce the atomistic structure it was built from — and it answers it in three parts that
are reported side by side because they fail in different ways: the constrained pairs (is the geometry the
right size), the bonded terms (is the shape right term by term), and the displacement of each bead after a
rigid-body fit (is it the right part of the molecule that moved).

It is anchored on the coarse-grained consumer run, because that run holds all three ensembles: its own
atomistic reference, the trajectory mapped onto the beads, and the simulated coarse-grained trajectory. The
mapping is supplied by the caller, since that is what `analysis/metadata`'s request payload carries and a
mapping is a reviewable record rather than something to be re-recognised from a trajectory.

Two readings are parameters with real defaults. They exist so this composition can be tested without a
coarse-grained run and without reading a developer's workspace; production always uses the defaults, which
read the run's own files through `analysis/runs/layout`.
"""
import json
from pathlib import Path

from .. import sugar_ensemble as ensemble
from . import bonded_terms, consistency, layout

#: Which comparison each section makes. A figure or table that does not say this is misread as evidence.
SECTIONS = {'pairs': 'AA vs CG', 'terms': 'AA-mapped vs CG-simulated',
            'displacement': 'AA vs CG, rigid-body fitted on the beads that own atoms'}


def _terms_for(work_dir):
    return bonded_terms.read_terms(layout.cg_topology(work_dir).read_text())


def _aa_measure(work_dir, mapping, molecule, terms, stride, limit):
    """The atomistic side: the supplied mapping's pairs and mean bead centres, under its own dilation."""
    return {'samples': consistency.aa_samples(work_dir, mapping, molecule, stride, limit),
            'means': consistency.aa_bead_means(work_dir, mapping, stride, limit),
            'terms': bonded_terms.measure(layout.resolve(work_dir, 'mapped_trajectory'),
                                          layout.resolve(work_dir, 'mapped_structure'), terms, stride, limit)}


def _cg_measure(work_dir, mapping, terms, stride, limit):
    """The simulated side: what the coarse-grained trajectory actually holds."""
    return {'samples': consistency.cg_samples(work_dir, mapping, stride, limit),
            'means': consistency.cg_bead_means(work_dir, stride, limit),
            'terms': bonded_terms.measure(layout.resolve(work_dir, 'cg_trajectory'),
                                          layout.resolve(work_dir, 'cg_structure'), terms, stride, limit)}


def _mapping_from(payload):
    mapping = (payload or {}).get('mapping_snapshot')
    if not isinstance(mapping, dict) or not mapping.get('beads'):
        raise ValueError('A mapping snapshot is required: the comparison is made through the assignment')
    return mapping


def run(work_dir, payload=None, stride=1, limit=None, aa_measure=None, cg_measure=None):
    """The whole comparison for one coarse-grained run, as a result an analysis attempt can publish."""
    payload = payload or {}
    work_dir = Path(work_dir)
    mapping = _mapping_from(payload)
    molecule = payload.get('molecule') or payload.get('molecule_id') or 'Sucrose'
    entry = payload.get('entry_name')
    terms = _terms_for(work_dir)
    aa = (aa_measure or _aa_measure)(work_dir, mapping, molecule, terms, stride, limit)
    cg = (cg_measure or _cg_measure)(work_dir, mapping, terms, stride, limit)

    reference = ensemble.published_constraints(entry) if entry else {}
    pairs = consistency.report(aa['samples'], cg['samples'], reference, entry=entry)
    rows = bonded_terms.compare_terms(aa['terms'], cg['terms'], cg['samples']['beads'])
    shape = consistency.displacement(aa['means'], cg['means'], consistency.physical_indices(mapping))
    return {'schema_version': 1, 'comparison': 'AA vs CG', 'molecule': molecule, 'entry': entry,
            'sections': dict(SECTIONS),
            'pairs': pairs, 'terms': rows, 'displacement': shape,
            'diagnostic_only': True, 'scientifically_validated': False,
            'interpretation': 'This compares our model with our own atomistic reference, which is a '
                              'statement about this system and not experimental evidence. The reference '
                              "entry's numbers are carried as context and set no verdict."}


def publish(work_dir, payload=None, **options):
    """Write the comparison under `analysis/` and return the summary a result record carries."""
    result = run(work_dir, payload, **options)
    target = Path(work_dir) / 'analysis/mapping_consistency.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2))
    outside = [row for row in result['terms'] if row.get('compared') and row['aa'] and row['cg']
               and not (row['aa']['min'] <= row['cg']['mean'] <= row['aa']['max'])]
    return {'artifact': 'analysis/mapping_consistency.json',
            'comparison': result['comparison'],
            'pairs': result['pairs']['counts'],
            'terms': {'rows': len(result['terms']), 'outside_aa_range': len(outside)},
            'displacement_rmsd_nm': result['displacement']['rmsd_nm'],
            'diagnostic_only': True, 'scientifically_validated': False}
