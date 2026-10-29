"""Write stage 3's model topology from the mapping's parameterization, and record that it did.

`parameterization.json` is the mapping's current revision, staged by the run's `prepare` because the
run consumes a model and not a state id (D1). This script writes it under the two names the run's own
readers use, which are the two names stage 3 leaves behind when it fits:

  `$FINAL_ITP`            what stage 4's `system_EMPTY.top` includes: the model the run simulates.
  `<stem>_ff_inter.itp`   the fit's interaction topology, which is what the two checks
                          (`dihedral_fit.publish`, `bonded_estimate.cross_check`) and
                          `bartender_fit.model_topology` read -- and, through the analysis layer's own
                          declared sources (`3_initial_CG/*_ff_inter.itp`), the only name a run's
                          checks are ever handed. A model written under any other name would leave
                          them reading the coordinate seed beside it and commenting on a topology the
                          run never used.

`parameterization_used.json` is the stage's own record, and it exists because of one rule: a stage
that skips its fit must say so in its own artefact rather than look like one that fitted. So
`bonded_fit.json` -- the file `refine_bonded.py` writes when this stage does fit -- is deliberately
not written here, and this record carries the revision, the engine, the ensemble and the options the
terms came from instead.
"""
import hashlib
import json
import os
from pathlib import Path

source = Path('parameterization.json')
if not source.is_file():
    raise FileNotFoundError(
        "this stage consumes the model's parameterization and was staged without one; "
        'a run that fits its own bonded terms runs fit_topology.sh instead')

revision = json.loads(source.read_text())
topology = revision['topology']
options = revision.get('options') or {}
reference = revision.get('aa_reference') or {}
ensemble = revision.get('ensemble') or {}

# The AA reference's interaction histograms, named in place by the run's prepare and verified by the executor with the
# rest of its input record. `ff_assess` scores a CG trajectory against these files from its `-d` directory and never
# computes them, so a run without them simulates for an hour and then reports `Overall Score : nan`. They are checked
# here again, where the run's own stage can still say what is wrong, rather than three stages later in a tool's stdout.
inventory = Path('distributions.json')
recorded = []
pairs = {}
if inventory.is_file():
    contents = json.loads(inventory.read_text())
    # The count `prepare` staged beside the files: the pairwise family is what stage 5 builds its score matrix from, and
    # 0 of them is the difference between a run that scores and one whose stage 5 records `skipped`.
    pairs = contents.get('pairs') or {}
    for entry in contents.get('files') or []:
        path = Path(entry['name'])
        if not path.is_file():
            raise FileNotFoundError(
                f'the reference distribution {entry["name"]} is not staged beside this stage; '
                'the run could not be scored against the AA reference it consumed')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry['sha256']:
            raise ValueError(f'the reference distribution {entry["name"]} does not match the digest it was staged '
                             'with; the run could not be scored against the AA reference it consumed')
        recorded.append({'name': entry['name'], 'sha256': digest})

final = Path(os.environ.get('FINAL_ITP', 'DDM.itp'))
final.write_text(topology)
Path(f'{final.stem}_ff_inter.itp').write_text(topology)

record = {
    'fitted': False,
    'statement': ("this stage did not fit anything: the terms are the mapping's parameterization, "
                  f"revision {revision['revision']}, staged by the run's prepare"),
    'revision': revision['revision'],
    'engine': revision.get('engine'),
    'torsion_model': options.get('torsion_model'),
    'torsion_scale': options.get('torsion_scale'),
    'constraints_threshold': options.get('constraints_threshold'),
    'temperature_k': options.get('temperature_k'),
    'ensemble': {'frames': ensemble.get('frames'), 'source': ensemble.get('source')},
    'aa_reference': reference,
    'topology': str(final),
    'topology_sha256': hashlib.sha256(topology.encode()).hexdigest(),
    'revision_sha256': hashlib.sha256(json.dumps(
        {key: value for key, value in revision.items() if key != 'created_at'},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
    'checks_published_with_the_revision': sorted((revision.get('checks') or {}).keys()),
    # What stage 5 will score this run against, named by the stage that consumed the model: the baseline is part of
    # the model and travels with it, so a run's own record can say which histograms its numbers came from -- and how
    # many of them are the pairwise family the score matrix is built from.
    'reference_distributions': recorded,
    'reference_pairs': pairs,
    'scientifically_validated': False,
}
Path('parameterization_used.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
