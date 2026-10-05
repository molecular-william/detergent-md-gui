"""Molecule-scoped CG runs must consume a shared AA reference."""
import copy
import json
from pathlib import Path

import pytest

from dashboard.execution.adapters import cg
from dashboard.execution.adapters.cg_names import CGNames
from dashboard.execution.environment import TUTORIAL_TEMPLATE
from dashboard.models import mappings
from dashboard.models.mappings.context import as_structure, build_context
from dashboard.models.molecules import draft as draft_model

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_long_molecule_id_uses_short_source_residue_name_for_gro():
    names = CGNames.for_snapshot({'id': 'Maltose', 'metadata': {'molecule_type': 'LIG1'}})
    assert names.residue_name == 'LIG1'
    assert names.initial_itp == 'LIG1_initial.itp'


def test_molecule_scoped_cg_requires_shared_reference(tmp_path):
    snapshot = {'id': 'Maltose', 'metadata': {'molecule_type': 'MAL', 'cg_molecule_type': 'MAL'}}
    run = tmp_path / 'run'; run.mkdir()
    with pytest.raises(ValueError, match='shared AA reference'):
        cg.prepare(run, molecule_snapshot=snapshot, profile='draft-smoke')


def test_molecule_scoped_cg_rejects_invalid_reference_id(tmp_path):
    snapshot = {'id': 'Maltose', 'metadata': {'molecule_type': 'MAL', 'cg_molecule_type': 'MAL'}}
    run = tmp_path / 'run'; run.mkdir()
    with pytest.raises(ValueError, match='Invalid AA source run ID'):
        cg.prepare(
            run, molecule_snapshot=snapshot, profile='draft-smoke',
            shared_reference={'source_run_id': 'not-a-run-id', 'sha256': {}},
        )


CG_MDPS = PROJECT_ROOT / 'resources/templates/small_mols_fast_forward/4_CG_sim/inputs'
AA_MDPS = PROJECT_ROOT / 'resources/templates/small_mols_fast_forward/1_AA_reference/mdps'


def mdp_value(path, key):
    for line in path.read_text().splitlines():
        body = line.split(';', 1)[0].strip()
        if body.startswith(key + ' '):
            return float(body.split('=', 1)[1])
    raise AssertionError(f'{key} is not in {path.name}')


def test_the_coarse_grained_half_integrates_at_martini_timesteps():
    """20 fs in production, as agreed: a 10 ns coarse-grained production is 500,000 steps and not 5,000,000.

    The equilibration is the exception the Martini 3 Methods name -- "Except for equilibration runs, a time step
    of 20 fs was used for all systems" -- so it integrates at 10 fs and the profile's 10 ps equilibration is
    1,000 steps. This assertion used to require 20 fs on both files; the production half of it is what the
    agreement was about and it is unchanged.
    """
    assert mdp_value(CG_MDPS / 'md.mdp', 'dt') == pytest.approx(0.02)
    assert round(10000.0 / mdp_value(CG_MDPS / 'md.mdp', 'dt')) == 500000
    assert mdp_value(CG_MDPS / 'eq.mdp', 'dt') == pytest.approx(0.005)
    assert round(10.0 / mdp_value(CG_MDPS / 'eq.mdp', 'dt')) == 2000


def test_the_atomistic_half_still_integrates_at_two_femtoseconds():
    assert mdp_value(AA_MDPS / 'eq.mdp', 'dt') == pytest.approx(0.002)
    assert mdp_value(AA_MDPS / 'md.mdp', 'dt') == pytest.approx(0.002)


def test_the_timestep_is_stamped_on_the_atomistic_half_only(tmp_path):
    """Stamping `dt` on both halves is what put 2 fs on the coarse-grained MDPs of run `abd5bf461c49`."""
    aa_dir, cg_dir = tmp_path / 'aa', tmp_path / 'cg'
    assert cg.mdp_integration(aa_dir, aa_dir, 25000)['dt'] == 0.002
    assert 'dt' not in cg.mdp_integration(cg_dir, aa_dir, 25000), \
        'the coarse-grained half keeps its template timestep'


def test_the_template_still_carries_the_anchor_the_rewrite_needs():
    """The stage script ships a placeholder temperature; the adapter rewrites it from the run's settings.

    If the template's anchor changes, the rewrite silently stops happening and every run fits at whatever
    the template says. This test is the thing that fails instead.
    """
    template = (PROJECT_ROOT / 'dashboard/execution/scripts/fit_topology.sh').read_text()
    assert '-temperature 300' in template


def test_a_fractional_run_temperature_is_rounded_for_ff_inter():
    """`ff_inter` declares `-temperature` as an int: 303.15 makes it exit before fitting anything."""
    template = (PROJECT_ROOT / 'dashboard/execution/scripts/fit_topology.sh').read_text()
    written = cg.fit_temperature(template, 303.15)
    assert '-temperature 303 ' in written
    assert '303.15' not in written
    assert '-temperature 300' not in written


def test_the_topology_stage_lets_fast_forward_constrain_its_stiffest_bonds():
    """FF's own default for `-constraints` is 10000; the runs passed 1000000000, which disables it entirely.

    Measured on the ring arms (`860eb013a82c`, `e08dc53410f9`): the stage kept the `S1B-S2A` link at
    k = 12964.8 as a harmonic bond, and the run died at ~200 ps -- which is what a numerically extreme
    constant does at a 20 fs timestep. This pins the flag so a later edit cannot quietly switch it off again;
    the executable lines only, because the comment above the line names the old value to explain it.
    """
    script = (PROJECT_ROOT / 'dashboard/execution/scripts/fit_topology.sh').read_text()
    executable = '\n'.join(line for line in script.splitlines() if not line.lstrip().startswith('#'))

    assert '-constraints 10000' in executable, "FF's own default: a bond above k=10000 becomes a constraint"
    assert '1000000000' not in executable, 'that value disables the conversion for every bond'


def mdp_values(path):
    """An mdp's settings, keyed the way `update_mdp` normalizes them (lower-case, underscore-folded)."""
    values = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition('=')
        if not separator:
            continue
        values[key.strip().lower().replace('_', '-')] = value.split(';')[0].strip().lower()
    return values


def test_the_cg_templates_prescribe_the_barostat_both_papers_use():
    """C-rescale to equilibrate, Parrinello-Rahman to produce, both at 1 bar.

    Martini 3's Methods ("General setup for CG molecular dynamics simulations and analysis") and the
    carbohydrate paper's own protocol both maintain pressure with Parrinello-Rahman at tau_p = 12 ps by
    velocity rescaling and a barostat; the carbohydrate paper gives beta = 4.5e-5 bar-1 for the same system
    this project runs -- a single sugar in water. The templates carried those numbers all along.
    """
    inputs = TUTORIAL_TEMPLATE / '4_CG_sim/inputs'
    equil, production = mdp_values(inputs / 'eq.mdp'), mdp_values(inputs / 'md.mdp')

    assert equil['pcoupl'] == 'c-rescale' and equil['tau-p'] == '4.0'
    assert production['pcoupl'] == 'parrinello-rahman' and production['tau-p'] == '12.0'
    for values in (equil, production):
        assert values['ref-p'] == '1.0'
        assert values['compressibility'] == '4.5e-5', "the papers' water compressibility, not GROMACS' default"


def test_the_cg_half_keeps_the_barostat_its_template_carries():
    """`mdp_integration` decides durations, logging and the timestep. Pressure coupling is not its business.

    It used to stamp `pcoupl = no` on both mdps of the coarse-grained half -- over a template that asks for
    C-rescale and Parrinello-Rahman at 1 bar -- so every CG production run this project has done was NVT with
    `ref_p` and `compressibility` dead keys, and the published protocol had never been executed once.
    """
    changes = cg.mdp_integration(Path('/run/4_CG_sim/inputs'), Path('/run/1_AA-reference'), 25000)

    assert 'pcoupl' not in changes, 'the template states the barostat; this must not override it'
    assert changes['nsteps'] == 25000, 'the timestep and the step count are what it is for'


def test_the_cg_equilibration_integrates_more_finely_than_its_production():
    """Martini 3's Methods: "Except for equilibration runs, a time step of 20 fs was used for all systems."

    That sentence is the only instruction either paper gives on the point -- it excludes equilibration from the
    20 fs step without naming its own. The user set the value: 5 fs, after 10 fs ran the DDM arms twice as far as
    20 fs did (446 ps against 125-200). The templates state it, because the adapter is not the place that decides
    a half's timestep: it reads each file's own dt back when it turns the requested duration into a step count, so
    the equilibration still runs for the 10 ps the profile asks for -- 2,000 steps rather than 500.
    """
    inputs = TUTORIAL_TEMPLATE / '4_CG_sim/inputs'
    equil, production = mdp_values(inputs / 'eq.mdp'), mdp_values(inputs / 'md.mdp')

    assert equil['dt'] == '0.005', 'the equilibration step'
    assert production['dt'] == '0.02', "the paper's production step, which the standing decision fixes at 20 fs"
    assert float(equil['dt']) < float(production['dt'])


def test_neither_cg_template_has_its_timestep_stamped_by_the_adapter():
    """Side by side with the barostat: what a template states, the adapter leaves alone."""
    changes = cg.mdp_integration(Path('/run/4_CG_sim/inputs'), Path('/run/1_AA-reference'), 1000)

    assert 'dt' not in changes, 'the CG half keeps its template dt; only the atomistic half is stamped'
    assert cg.mdp_integration(Path('/run/1_AA-reference'), Path('/run/1_AA-reference'), 1000)['dt'] == 0.002


def test_an_integral_temperature_is_passed_unchanged():
    template = (PROJECT_ROOT / 'dashboard/execution/scripts/fit_topology.sh').read_text()
    assert '-temperature 310 ' in cg.fit_temperature(template, 310)


def test_maltose_mapping_validation_uses_its_bound_molecule():
    context = build_context(PROJECT_ROOT / 'molecules', 'Maltose')
    mapping = mappings.automatic_candidate(as_structure(context), 'Maltose')
    mapping.update(schema_version=3, molecule_id='Maltose',
                  molecule_snapshot=copy.deepcopy(context['snapshot']))

    loaded = draft_model.load(mapping)
    metadata = json.loads((PROJECT_ROOT / 'molecules/Maltose/metadata.json').read_text())
    names = CGNames.for_snapshot({'id': 'Maltose', 'metadata': metadata})
    topology = draft_model.initial_topology(loaded, residue_name=names.residue_name)

    assert len(loaded['beads']) == 8
    assert '[ moleculetype ]' in topology
    assert topology.count('\n[ atoms ]') == 1
    assert '\nLIG1 1\n' in topology
    # The run's files identify a bead by position under a single residue. Both halves matter: `gmx grompp`
    # reconciles a topology with coordinates by atom name (and the reference's per-residue letters name two
    # beads `A` here), while MDAnalysis treats each residue as a molecule, so a two-residue molecule is two
    # molecules to Fast_Forward's assessment and its per-molecule index array comes out the wrong shape.
    atoms, section = [], None
    for line in topology.splitlines():
        body = line.split(';', 1)[0].strip()
        if body.startswith('['):
            section = body.strip('[] ').strip()
            continue
        if section == 'atoms' and body:
            atoms.append(body.split())
    assert [(int(row[2]), row[4]) for row in atoms] == [(1, f'B{index:02d}') for index in range(1, 9)]
    assert ' DDM ' not in topology


def test_maltose_mapping_without_virtual_sites_allows_advisory_size_warnings():
    context = build_context(PROJECT_ROOT / 'molecules', 'Maltose')
    mapping = mappings.automatic_candidate(as_structure(context), 'Maltose')
    mapping['beads'] = [bead for bead in mapping['beads'] if not bead.get('virtual_site')]
    mapping['rings'] = []
    physical = {bead['name'] for bead in mapping['beads']}
    mapping['connections'] = [pair for pair in mapping['connections'] if set(pair) <= physical]
    mapping.update(schema_version=3, molecule_id='Maltose', molecule_snapshot=copy.deepcopy(context['snapshot']), name='Maltose-0-noVS')

    loaded = draft_model.load(mapping, molecule_root=PROJECT_ROOT / 'molecules')
    exported = mappings.export_files(loaded, context=context)

    assert loaded['name'] == 'Maltose-0-noVS'
    assert {'mapping.map', 'mapping.ndx', 'mapped.gro', 'model.json'} <= exported.keys()
    validation = mappings.validate(loaded, context=context)
    assert validation['issues']
    assert validation['can_export'] and validation['can_reuse']
    assert not validation['can_approve']
