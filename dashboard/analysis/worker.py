"""Isolated analysis subprocess: sources are copied, outputs never replace them."""
import fnmatch
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .. import files
from ..execution import tools, workflow
from . import metadata as analysis_metadata
from .runs import bartender_fit, mapping_consistency, observability, refinement
from .runs import references as aa_references
from .validation import report as carbohydrate_validation
from .validation import targets

KINDS = {'plots', 'snapshots', 'surfaces', 'observables', 'stability', 'refinement-score', 'targets', 'carbohydrate-validation', 'mapping-consistency', 'bartender-fit'}
PATTERNS = {
    'plots': ['*SASA*/AA/*.xvg', '*SASA*/CG/*.xvg'],
    'snapshots': ['1_AA-reference/prod/lig.gro', '1_AA-reference/prod/lig.xtc'],
    'surfaces': ['1_AA-reference/prod/lig.gro', '1_AA-reference/prod/lig.xtc', '2_mapping/model.json', '4_CG_sim/prod/lig_CG.gro', '4_CG_sim/prod/lig_CG.xtc'],
    'observables': ['2_mapping/mapped.gro', '2_mapping/mapped.xtc', '3_initial_CG/DDM_initial.itp'],
    'stability': ['*.log', '*.xtc'],
    'refinement-score': ['5_assessment/validation.json'],
    'targets': [],
    'carbohydrate-validation': ['1_AA-reference/prod/lig.gro', '1_AA-reference/prod/lig.xtc',
                                '2_mapping/model.json', '4_CG_sim/prod/lig_CG.gro', '4_CG_sim/prod/lig_CG.xtc',
                                '3_initial_CG/*.itp'],
    # All three ensembles of one consumer run: its atomistic reference, the trajectory mapped onto the beads,
    # and the simulated coarse-grained trajectory, plus the topology that names the beads.
    'mapping-consistency': ['1_AA-reference/prod/lig.gro', '1_AA-reference/prod/lig.xtc',
                            '2_mapping/mapped.gro', '2_mapping/mapped.xtc',
                            '4_CG_sim/prod/lig_CG.gro', '4_CG_sim/prod/lig_CG.xtc', '3_initial_CG/*.itp'],
    # The atomistic solute and its trajectory (what the fit is checked against), the mapping that defines the beads,
    # and the generated topology whose terms the fit is compared with. Optional by design: nothing queues it.
    'bartender-fit': ['1_AA-reference/prod/lig.gro', '1_AA-reference/prod/lig.xtc', '2_mapping/model.json',
                      '2_mapping/mapping.ndx', '3_initial_CG/*.itp'],
}



def source_paths(root, kind):
    return list(source_entries(root,kind).values())


def source_entries(root,kind):
    patterns = list(PATTERNS[kind])
    run=root.parent if root.name=='stages' else root
    metadata=json.loads((run/'manifest.json').read_text()) if (run/'manifest.json').is_file() else {}
    shared=metadata.get('shared_reference');aa_source=None
    if kind in ('snapshots','surfaces','carbohydrate-validation','mapping-consistency'):
        if shared:aa_source,_=aa_references.resolve(run.parent,shared['source_run_id'],shared['sha256'])
        elif metadata.get('run_type')=='aa_only':
            aa_references.verify(run);aa_source=root/'07_reference'
    if kind == 'snapshots' and not aa_source and not (root/'1_AA-reference/prod/lig.xtc').is_file():
        patterns = ['1_AA-reference/3-run.xtc', '1_AA-reference/3-run.tpr']
    entries={str(p.relative_to(root)):p for p in files.safe_files(root) if str(p.relative_to(root)).split('/')[0] not in ('analysis','analyses','analysis_plots','snapshots','inputs','logs') and any(fnmatch.fnmatch(str(p.relative_to(root)),pattern) for pattern in patterns)}
    if aa_source:entries.update({f'1_AA-reference/prod/{name}':aa_source/name for name in ('lig.gro','lig.xtc')})
    return entries

def execute(request_path):
    request_path = Path(request_path)
    request = json.loads(request_path.read_text())
    run = Path(request['run']); attempt = request_path.parent
    kind = request['kind']; root = workflow.execution_root(run)
    if kind not in KINDS: raise ValueError('Unknown analysis')
    def progress(phase):
        files.atomic_json(attempt/'progress.json', {'phase': phase})
    progress('Copying and hashing sources')
    versions = {'python':sys.version,'executable':sys.executable}
    for package in ('MDAnalysis','numpy','matplotlib','plotly','scikit-image','scipy'):
        try: versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: pass
    gmx = tools.tool_path('gmx')
    if gmx and kind in ('surfaces','stability','carbohydrate-validation'):
        info = subprocess.run([gmx,'--version'],capture_output=True,text=True,timeout=30,check=True)
        versions['gmx'] = {'path':gmx,'version_output':info.stdout}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='.work-', dir=attempt) as temporary:
        work = Path(temporary); sources = {}
        for relative,path in source_entries(root,kind).items():
            target = work/relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            provenance=str(path.relative_to(run)) if path.is_relative_to(run) else 'shared/'+str(path.relative_to(run.parent))
            sources[provenance] = files.sha256(target)
        # Refinement depends on the latest completed diagnostic reports, with legacy fallback.
        if kind == 'refinement-score':
            for name in ('numerical_stability.json', 'experimental_targets.json'):
                path = request.get('dependencies', {}).get(name)
                path = run/path if path else root/'analysis'/name
                if path.is_file():
                    if path.is_symlink() or not path.resolve().is_relative_to(run.resolve()): raise ValueError('Invalid analysis dependency')
                    target = work/'analysis'/name; target.parent.mkdir(exist_ok=True)
                    shutil.copy2(path, target); sources[str(path.relative_to(run))] = files.sha256(target)
        baseline = files.hashes(work)
        files.atomic_json(attempt/'sources.json', sources)
        progress('Calculating ' + kind)
        if kind == 'targets': result = targets.build(work, request.get('payload', {}))
        elif kind == 'refinement-score': result = refinement.score(work)
        elif kind == 'carbohydrate-validation': result = carbohydrate_validation.run(work, request.get('payload', {}))
        elif kind == 'mapping-consistency': result = mapping_consistency.publish(work, request.get('payload', {}))
        elif kind == 'bartender-fit': result = bartender_fit.run(work, request.get('payload', {}))
        else:
            function = {'plots': observability.sasa_plot, 'snapshots': observability.generate,
                        'surfaces': observability.connolly_surfaces, 'observables': observability.unparameterized_observables,
                        'stability': observability.numerical_stability}[kind]
            result = function(work)
        files.atomic_json(work/'analysis-metadata.json', analysis_metadata.describe(kind, result))
        progress('Publishing immutable results')
        source_key = hashlib.sha256(json.dumps([sources,request.get('payload',{}),request.get('code_signature')],sort_keys=True).encode()).hexdigest()
        output = attempt/'output'/source_key; output.mkdir(parents=True)
        for path in files.safe_files(work):
            relative = str(path.relative_to(work))
            if relative in baseline:
                if files.sha256(path) != baseline[relative]: raise ValueError('Analysis modified its source copy: ' + relative)
                continue
            target = output/relative; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        files.atomic_json(attempt/'result.json', {'result': result, 'output_directory':str(output.relative_to(attempt)), 'sources_sha256': sources,
                          'outputs_sha256': files.hashes(output), 'tools':versions, 'wall_seconds': time.monotonic()-started})
        progress('Completed')


if __name__ == '__main__':
    execute(sys.argv[1])
