"""The MDP writer's parity gate: every reviewed profile renders the map it was reviewed as.

Phase 3, T3.1 of `docs/plans/2026-10-27-run-lifecycle-refactor.md`: a profile may replace a template or an adapter
patch only when its file parses to the same settings. Comments and formatting are ignored -- the comparison is the
key/value map GROMACS reads. The AA maps below are written out literally; the CG and pdc profiles are compared with
the shipped template files, patched by the literal changes this test states. The values a profile leaves for the run
are supplied the way its adapter computes them.

The two legacy builders these tests used to compare against (`aa.mdp`, `cg.mdp_integration`,
`environment.update_mdp`) are gone: the reviewed profile is the one implementation, and a literal map is the
independent statement of what it must produce.
"""
import math
import shutil
from dataclasses import replace

import pytest
from dashboard import paths
from dashboard.execution import forcefields
from dashboard.execution.adapters import aa, cg
from dashboard.execution.mdp import PROFILES, render, write_mdp
from dashboard.execution.mdp.writer import formatted
from detergent_pdc.execution.adapters import pdc
from detergent_validation.execution.adapters import osmotic_mdp

ROOT = paths.DEFAULT.project_root
TEMPLATES = ROOT / 'resources/templates'
FF_TEMPLATE = TEMPLATES / 'small_mols_fast_forward'
CG_INPUTS = FF_TEMPLATE / '4_CG_sim/inputs'
PDC_TEMPLATES = TEMPLATES / 'protein_detergent'

AA_KINDS = {'ions': 'aa-ions-v1', 'em': 'aa-em-v1', 'nvt': 'aa-nvt-v1', 'npt': 'aa-npt-v1',
            'production': 'aa-production-v1'}
AA_DURATION = {'aa-nvt-v1': 'aa_nvt_ps', 'aa-npt-v1': 'aa_npt_ps', 'aa-production-v1': 'aa_production_ps'}


# --------------------------------------------------------------------------------------------------------------------
# The comparison: an MDP as a key/value map, and a literal expected map.
# --------------------------------------------------------------------------------------------------------------------

def parsed(text):
    """The MDP's settings: comments dropped, names folded (`xtc_grps`/`xtc-grps`/`Xtc-Grps` are one name), last wins."""
    settings = {}
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line or '=' not in line:
            continue
        key, value = (part.strip() for part in line.split('=', 1))
        settings[key.lower().replace('_', '-')] = ' '.join(value.split())
    return settings


def equivalent(left, right):
    """Formatting differences -- `4.0` against `4`, `4.5e-5` against `4.5e-05` -- are not physics differences."""
    if len(left.split()) == 1 and len(right.split()) == 1:
        try:
            return float(left) == float(right)
        except ValueError:
            pass
    return left == right


#: The three neighbour-list keys the CG dynamics profiles own deliberately, against templates that were written for a
#: 20-step list with a pinned 1.35 nm buffer.
NEIGHBOURS = ('nstlist', 'verlet-buffer-tolerance', 'rlist')


def assert_same(profile, expected_text, values=None, ignore=()):
    """One profile against a literal map: same keys, same values, nothing extra on either side."""
    produced = parsed(render(profile, values))
    expected = parsed(expected_text) if isinstance(expected_text, str) else dict(expected_text)
    for key in ignore:
        produced.pop(key, None)
        expected.pop(key, None)
    assert produced.keys() == expected.keys(), (
        f'{profile}: only in the literal map: {sorted(set(expected) - set(produced))}; '
        f'only in the profile: {sorted(set(produced) - set(expected))}')
    differing = {key: (expected[key], produced[key]) for key in expected
                 if not equivalent(expected[key], produced[key])}
    assert differing == {}, f'{profile}: {differing}'


def apply_changes(path, changes):
    """Patch a copied template with literal changes, the way prepare used to patch it."""
    lines = path.read_text().splitlines()
    normalized = lambda value: value.strip().lower().replace('_', '-')
    wanted = {normalized(key): str(value) for key, value in changes.items()}
    seen = set()
    for index, line in enumerate(lines):
        key = normalized(line.split('=', 1)[0])
        if key in wanted:
            lines[index] = f'{key} = {wanted[key]}'
            seen.add(key)
    lines.extend(f'{key} = {value}' for key, value in wanted.items() if key not in seen)
    path.write_text('\n'.join(lines) + '\n')


def patched(tmp_path, name, changes, source=None):
    """Copy the template the build copies, then apply the literal changes this run makes."""
    target = tmp_path / name
    shutil.copy2(source or CG_INPUTS / name, target)
    apply_changes(target, changes)
    return target


def cg_integration(steps):
    """The literal changes the CG half makes to its template: durations, cadence and the run's fixed seed."""
    return {'nsteps': steps, 'nstlog': 100, 'nstenergy': 100, 'gen-seed': 20260911,
            'nstxtcout': 100, 'xtc-precision': 1000}


# --------------------------------------------------------------------------------------------------------------------
# AA-only stages: the reviewed maps, written literally.
# --------------------------------------------------------------------------------------------------------------------

AA_EXPECTED = {
    'aa-ions-v1': {'cutoff-scheme': 'Verlet', 'vdwtype': 'Cut-off', 'vdw-modifier': 'Force-switch', 'rlist': '1.2',
                   'rvdw': '1.2', 'rvdw-switch': '1', 'coulombtype': 'Cut-off', 'rcoulomb': '1.2',
                   'dispcorr': 'no', 'constraints': 'all-bonds', 'nstlist': '20', 'pbc': 'xyz',
                   'constraint-algorithm': 'lincs', 'verlet-buffer-tolerance': '-1', 'integrator': 'steep',
                   'nsteps': '0', 'emtol': '1000', 'emstep': '0.01'},
    'aa-em-v1': {'cutoff-scheme': 'Verlet', 'vdwtype': 'Cut-off', 'vdw-modifier': 'Force-switch', 'rlist': '1.2',
                 'rvdw': '1.2', 'rvdw-switch': '1', 'coulombtype': 'PME', 'rcoulomb': '1.2', 'dispcorr': 'no',
                 'constraints': 'all-bonds', 'nstlist': '20', 'pbc': 'xyz', 'constraint-algorithm': 'lincs',
                 'verlet-buffer-tolerance': '-1', 'integrator': 'steep', 'nsteps': '20000', 'emtol': '1000',
                 'emstep': '0.01'},
    'aa-nvt-v1': {'cutoff-scheme': 'Verlet', 'vdwtype': 'Cut-off', 'vdw-modifier': 'Force-switch', 'rlist': '1.2',
                  'rvdw': '1.2', 'rvdw-switch': '1', 'coulombtype': 'PME', 'rcoulomb': '1.2', 'dispcorr': 'no',
                  'constraints': 'all-bonds', 'nstlist': '20', 'pbc': 'xyz', 'constraint-algorithm': 'lincs',
                  'verlet-buffer-tolerance': '-1', 'integrator': 'md', 'dt': '0.002', 'nsteps': '50000',
                  'continuation': 'no', 'tcoupl': 'V-rescale', 'tc-grps': 'System', 'tau-t': '1', 'ref-t': '303.15',
                  'gen-vel': 'yes', 'gen-temp': '303.15', 'gen-seed': '20260917', 'ld-seed': '20260917',
                  'pcoupl': 'no', 'nstxout-compressed': '5000', 'nstenergy': '500', 'nstlog': '500'},
    'aa-npt-v1': {'cutoff-scheme': 'Verlet', 'vdwtype': 'Cut-off', 'vdw-modifier': 'Force-switch', 'rlist': '1.2',
                  'rvdw': '1.2', 'rvdw-switch': '1', 'coulombtype': 'PME', 'rcoulomb': '1.2', 'dispcorr': 'no',
                  'constraints': 'all-bonds', 'nstlist': '20', 'pbc': 'xyz', 'constraint-algorithm': 'lincs',
                  'verlet-buffer-tolerance': '-1', 'integrator': 'md', 'dt': '0.002', 'nsteps': '500000',
                  'continuation': 'yes', 'tcoupl': 'V-rescale', 'tc-grps': 'System', 'tau-t': '1', 'ref-t': '303.15',
                  'gen-vel': 'no', 'gen-temp': '303.15', 'gen-seed': '20260917', 'ld-seed': '20260917',
                  'pcoupl': 'C-rescale', 'nstxout-compressed': '5000', 'nstenergy': '500', 'nstlog': '500',
                  'pcoupltype': 'isotropic', 'tau-p': '5', 'ref-p': '1', 'compressibility': '4.5e-5'},
    'aa-production-v1': {'cutoff-scheme': 'Verlet', 'vdwtype': 'Cut-off', 'vdw-modifier': 'Force-switch',
                         'rlist': '1.2', 'rvdw': '1.2', 'rvdw-switch': '1', 'coulombtype': 'PME', 'rcoulomb': '1.2',
                         'dispcorr': 'no', 'constraints': 'all-bonds', 'nstlist': '20', 'pbc': 'xyz',
                         'constraint-algorithm': 'lincs', 'verlet-buffer-tolerance': '-1', 'integrator': 'md',
                         'dt': '0.002', 'nsteps': '5000000', 'continuation': 'yes', 'tcoupl': 'V-rescale',
                         'tc-grps': 'System', 'tau-t': '1', 'ref-t': '303.15', 'gen-vel': 'no',
                         'gen-temp': '303.15', 'gen-seed': '20260917', 'ld-seed': '20260917',
                         'pcoupl': 'Parrinello-Rahman', 'nstxout-compressed': '5000', 'nstenergy': '500',
                         'nstlog': '500', 'pcoupltype': 'isotropic', 'tau-p': '5', 'ref-p': '1',
                         'compressibility': '4.5e-5'},
}


def aa_values(profile, settings):
    if profile in ('aa-ions-v1', 'aa-em-v1'):
        return {'force_field': settings['force_field']}
    interval = max(1, round(settings['output_interval_ps'] / 0.002))
    values = {'force_field': settings['force_field'],
              'nsteps': round(settings[AA_DURATION[profile]] / 0.002),
              'ref-t': settings['temperature_k'], 'gen-temp': settings['temperature_k'],
              'gen-seed': settings['aa_seed'], 'ld-seed': settings['aa_seed'],
              'nstxout-compressed': interval, 'nstenergy': min(interval, 500), 'nstlog': min(interval, 500)}
    if profile != 'aa-nvt-v1':
        values['ref-p'] = settings['pressure_bar']
    return values


def test_aa_profiles_pin_the_reviewed_maps():
    settings = aa.normalize_settings({'force_field': forcefields.DEFAULT})
    for profile in AA_KINDS.values():
        assert_same(profile, AA_EXPECTED[profile], aa_values(profile, settings))


def test_the_aa_stage_settings_reach_their_own_mdp():
    """dt changes the step count, not the duration; nstlist and the buffer tolerance are each stage's own.

    The defaults above are the reviewed numbers, so the parity maps stay untouched. This is the other half: a run
    that names a stage's numbers writes them into that stage's file and doubles its step count at half the timestep.
    """
    changed = aa.normalize_settings({'aa_nvt_dt_fs': 1, 'aa_npt_dt_fs': 1, 'aa_production_dt_fs': 1,
                                     'aa_nvt_nstlist': 10, 'aa_npt_nstlist': 40,
                                     'aa_production_verlet_buffer_tolerance': 0.01})
    default = aa.normalize_settings({})
    nstlist = {'aa-nvt-v1': '10', 'aa-npt-v1': '40', 'aa-production-v1': '20'}
    for profile in AA_DURATION:
        before = parsed(render(profile, aa.mdp_values(default, profile)))
        after = parsed(render(profile, aa.mdp_values(changed, profile)))
        assert after['dt'] == '0.001', profile
        assert int(after['nsteps']) == 2 * int(before['nsteps']), profile
        assert int(after['nstxout-compressed']) == 2 * int(before['nstxout-compressed']), profile
        assert after['nstenergy'] == after['nstlog'] == '500', profile
        assert after['nstlist'] == nstlist[profile], profile
        # A stage that named none keeps the reviewed buffer tolerance.
        assert after['verlet-buffer-tolerance'] == (
            '0.01' if profile == 'aa-production-v1' else '-1'), profile


def test_an_aa_verlet_buffer_tolerance_of_exactly_zero_is_refused_by_name():
    """GROMACS itself refuses it, so the run that would reach grompp with it is refused here, naming the setting."""
    for stage in ('nvt', 'npt', 'production'):
        with pytest.raises(ValueError, match=rf'aa_{stage}_verlet_buffer_tolerance.*exactly 0'):
            aa.normalize_settings({f'aa_{stage}_verlet_buffer_tolerance': 0})


def test_a_cg_verlet_buffer_tolerance_of_exactly_zero_is_refused():
    """The CG production file has no pinned rlist for -1, so its domain starts above zero rather than at it."""
    with pytest.raises(ValueError, match=r'CG Verlet buffer tolerance .* must be between 0.001 and 0.1'):
        cg.normalize_settings({'verlet_buffer_tolerance': 0})


# --------------------------------------------------------------------------------------------------------------------
# CG half: `cg.prepare` patches the shipped templates.
# --------------------------------------------------------------------------------------------------------------------

def current_cg_dynamics(tmp_path, settings, name):
    """The eq/md file as `cg.prepare` writes it, and the numbers it supplies, both from the template's own dt."""
    path = patched(tmp_path, f'{name}.mdp', cg_integration({'eq': 5000, 'md': 25000}[name]))
    apply_changes(path, {'gen-seed': settings['cg_seed'], 'ld-seed': settings['cg_seed'],
                         'gen-temp': settings['temperature_k']})
    dt = float(parsed(path.read_text())['dt'])
    values = {'nsteps': round(settings['cg_equil_ps' if name == 'eq' else 'cg_production_ps'] / dt),
              'nstxtcout': max(1, round(settings['output_interval_ps'] / dt)),
              'ref-t': settings['temperature_k'], 'gen-temp': settings['temperature_k'],
              'gen-seed': settings['cg_seed'], 'ld-seed': settings['cg_seed']}
    apply_changes(path, {key: values[key] for key in ('nsteps', 'ref-t', 'nstxtcout')})
    return path.read_text(), values


CG_RUN = {'cg_equil_ps': 20.0, 'cg_production_ps': 200.0, 'temperature_k': 310.0,
          'output_interval_ps': 5.0, 'cg_seed': 12345}


@pytest.mark.parametrize('overrides', (None, CG_RUN))
def test_cg_profiles_match_prepare_patches(tmp_path, overrides):
    settings = cg.normalize_settings(overrides)
    initial = patched(tmp_path, 'initial.mdp', {'nsteps': 0}, FF_TEMPLATE / '3_initial_CG/initial.mdp')
    assert_same('cg-initial-v1', initial.read_text())
    minimisation = patched(tmp_path, 'minimization.mdp', {'nsteps': 20000, 'define': ''})
    assert_same('cg-minimization-v1', minimisation.read_text())
    for name, profile in (('eq', 'cg-equilibration-v1'), ('md', 'cg-production-v1')):
        expected, values = current_cg_dynamics(tmp_path, settings, name)
        assert_same(profile, expected, values, ignore=NEIGHBOURS)


def test_cg_dynamics_states_the_reviewed_neighbour_list():
    """`nstlist = 40` with a computed buffer, and no pinned `rlist`, in every CG file that integrates.

    The decision and the measurement behind it are in `profiles.py`; this pins that no profile drifts back to the
    template's 20 steps, and that a pinned `rlist` cannot come back with it -- 1.35 nm was the 20-step buffer.
    """
    dynamics = ('cg-equilibration-v1', 'cg-production-v1', 'pdc-nvt-v1', 'pdc-npt-v1',
                'pdc-restart-equilibration-v1')
    for profile in dynamics:
        settings = PROFILES[profile].settings
        assert settings['nstlist'] == 40, profile
        assert settings['verlet-buffer-tolerance'] == 0.005, profile
        assert 'rlist' not in settings, profile
    # The two CG production profiles leave the neighbour list to the run; its defaults are the same 40 / 0.005 /
    # 1.35, so an untouched run is still the reviewed list rather than a pinned one.
    for profile in ('pdc-assessment-v1', 'pdc-extension-v1'):
        numbers = pdc._mdp_run_values(profile, pdc.settings_from({}))
        assert numbers['nstlist'] == 40 and numbers['verlet-buffer-tolerance'] == 0.005
        assert 'rlist' not in numbers, 'the profile does not own a pinned neighbour cut-off'
    # A minimisation integrates nothing, so the pdc one keeps the pinned list it always had.
    assert PROFILES['pdc-minimisation-v1'].settings['rlist'] == 1.35


def test_a_run_value_the_profile_fixes_is_refused():
    """An override would be one reviewed profile run under another's name."""
    with pytest.raises(ValueError, match='nsteps'):
        render('aa-em-v1', {'nsteps': 5})


def test_a_missing_run_number_is_refused_instead_of_written_as_none():
    with pytest.raises(ValueError, match='nsteps'):
        render('aa-nvt-v1', {'force_field': forcefields.DEFAULT})


def test_the_force_field_block_is_read_at_render_time(monkeypatch):
    entry = forcefields.entry()
    monkeypatch.setitem(forcefields.ENTRIES, 'rendered-test-field',
                        replace(entry, mdp={**entry.mdp, 'rlist': 3.0}))
    assert parsed(render('aa-em-v1', {'force_field': 'rendered-test-field'}))['rlist'] == '3'
    assert 'rlist' not in PROFILES['aa-em-v1'].settings
    assert 'constraints' not in PROFILES['aa-em-v1'].settings


# --------------------------------------------------------------------------------------------------------------------
# PDC legs: three templates, the genion fix-up, and the production/extension legs built from the CG template.
# --------------------------------------------------------------------------------------------------------------------

def test_pdc_leg_profiles_match_the_templates_and_their_stamps(tmp_path):
    minimisation = patched(tmp_path, 'minimisation.mdp', {'nsteps': 500}, PDC_TEMPLATES / 'minimisation.mdp')
    assert_same('pdc-minimisation-v1', minimisation.read_text(), {'nsteps': 500})
    nvt = patched(tmp_path, 'nvt.mdp', {'nsteps': 10000, 'gen-seed': 42}, PDC_TEMPLATES / 'nvt.mdp')
    assert_same('pdc-nvt-v1', nvt.read_text(), {'nsteps': 10000, 'gen-seed': 42}, ignore=NEIGHBOURS)
    npt = patched(tmp_path, 'npt.mdp', {'nsteps': 900000}, PDC_TEMPLATES / 'npt.mdp')
    assert_same('pdc-npt-v1', npt.read_text(), {'nsteps': 900000}, ignore=NEIGHBOURS)


def test_the_pdc_ions_profile_is_the_genion_fix_up():
    """The fix-up mdp had no template: it was a string in `pdc`, and these six keys are its whole definition."""
    assert parsed(render('pdc-ions-v1')) == {'integrator': 'steep', 'nsteps': '0', 'cutoff-scheme': 'Verlet',
                                             'rlist': '1.1', 'coulombtype': 'reaction-field', 'epsilon-r': '15'}


def test_pdc_production_profiles_match_the_adapter(tmp_path):
    stage = tmp_path / '2_assessment'
    stage.mkdir()
    steps = round(100 * 1000 / 0.02)
    numbers = pdc.settings_from({})
    assessment = patched(stage, 'assessment.mdp', cg_integration(steps), CG_INPUTS / 'md.mdp')
    assert_same('pdc-assessment-v1', assessment.read_text(),
                pdc._mdp_run_values('pdc-assessment-v1', numbers, {'nsteps': steps}), ignore=NEIGHBOURS)
    extension = patched(stage, 'extension.mdp', {'gen-vel': 'no'}, assessment)
    assert_same('pdc-extension-v1', extension.read_text(),
                pdc._mdp_run_values('pdc-extension-v1', numbers, {'nsteps': steps}), ignore=NEIGHBOURS)


def test_pdc_restart_profiles_match_the_unpatched_templates():
    """The removal path copies these two files as they are, so the profile is the template's map exactly."""
    assert_same('pdc-restart-minimization-v1', (CG_INPUTS / 'minimization.mdp').read_text())
    assert_same('pdc-restart-equilibration-v1', (CG_INPUTS / 'eq.mdp').read_text(), ignore=NEIGHBOURS)


# --------------------------------------------------------------------------------------------------------------------
# Osmotic series: `osmotic_mdp.osmotic_mdps` builds all three from the run's temperature, durations and interval.
# --------------------------------------------------------------------------------------------------------------------

TEMPERATURE = 308.15


@pytest.mark.parametrize('production_ps, equilibration_ps, interval_ps', (
    (osmotic_mdp.DEFAULT_PRODUCTION_PS, osmotic_mdp.DEFAULT_EQUILIBRATION_PS, osmotic_mdp.DEFAULT_OUTPUT_INTERVAL_PS),
    (2000.0, 1000.0, 5.0),
))
def test_osmotic_profiles_match_osmotic_mdps(production_ps, equilibration_ps, interval_ps):
    mdps = osmotic_mdp.osmotic_mdps(temperature=TEMPERATURE, solute_molecules=2, production_ps=production_ps,
                                    equilibration_ps=equilibration_ps, output_interval_ps=interval_ps)
    assert_same('osmotic-minimization-v1', mdps['minimization'])
    for stage, dt, steps, profile in (
            ('equilibration', osmotic_mdp.EQUILIBRATION_DT, math.ceil(equilibration_ps / osmotic_mdp.EQUILIBRATION_DT),
             'osmotic-equilibration-v1'),
            ('production', osmotic_mdp.PRODUCTION_DT, round(production_ps / osmotic_mdp.PRODUCTION_DT),
             'osmotic-production-v1')):
        stride = round(interval_ps / dt)
        values = {'nsteps': steps, 'nstxtcout': stride, 'nstenergy': stride,
                  'ref-t': TEMPERATURE, 'gen-temp': TEMPERATURE}
        assert_same(profile, mdps[stage], values)


# --------------------------------------------------------------------------------------------------------------------
# The writer's own contract.
# --------------------------------------------------------------------------------------------------------------------

def test_every_profile_is_registered_under_its_versioned_name():
    for name, profile in PROFILES.items():
        assert profile.version == name
        assert name.endswith('-v1'), f'{name} carries no version'
    assert {'aa-nvt-v1', 'cg-equilibration-v1', 'pdc-assessment-v1', 'osmotic-production-v1'} <= set(PROFILES)


def test_write_mdp_writes_the_rendered_file(tmp_path):
    path = write_mdp('pdc-ions-v1', tmp_path / 'ions.mdp')
    assert path == tmp_path / 'ions.mdp'
    assert path.read_text() == render('pdc-ions-v1')


def test_values_are_formatted_the_way_gromacs_reads_them():
    assert formatted(4.5e-5) == '4.5e-05'
    assert formatted(0.002) == '0.002'
    assert formatted(5000) == '5000'
    assert formatted(True) == 'yes' and formatted(False) == 'no'
    assert formatted('') == ''


def test_an_unknown_profile_is_refused_by_name():
    with pytest.raises(ValueError, match='unknown MDP profile'):
        render('nvt-cg-v1')


def test_an_empty_define_is_written_as_a_cleared_define():
    text = render('cg-minimization-v1')
    line = next(line for line in text.splitlines() if line.split(';')[0].strip().startswith('define'))
    assert line.split(';')[0].rstrip() == 'define ='
    assert parsed(text)['define'] == ''


def test_pdc_production_keeps_the_cadence_the_run_sent(tmp_path):
    """The panel's numbers reach the assessment file unchanged, even when the leg is 1 us or longer."""
    numbers = pdc.settings_from({'nstlog': 100, 'nstenergy': 250, 'nstxtcout': 100})
    steps = round(1_000_000.0 / 0.02)
    text = render('pdc-assessment-v1', pdc._mdp_run_values('pdc-assessment-v1', numbers, {'nsteps': steps}))
    written = parsed(text)

    assert (written['nstlog'], written['nstenergy'], written['nstxtcout']) == ('100', '250', '100')


def test_cg_production_options_replace_only_what_the_run_names():
    """The Other run options are overrides, not a second profile.

    The reviewed profile keeps a value for every option the form offers, so a run that names none writes the
    reviewed file byte for byte; a named one replaces that option and nothing else. `rlist` is the one option the
    reviewed file deliberately omits (GROMACS sizes it), so it appears only when pinned.
    """
    settings = cg.normalize_settings(None)
    untouched = render('cg-production-v1', cg.mdp_values(settings, 'cg-production-v1'))
    # The same file the profile rendered before the settings existed: only the run's own numbers, no override keys.
    base = {'nsteps': round(settings['cg_production_ps'] / 0.02),
            'nstxtcout': max(1, round(settings['output_interval_ps'] / 0.02)),
            'ref-t': settings['temperature_k'], 'gen-temp': settings['temperature_k'],
            'gen-seed': settings['cg_seed'], 'ld-seed': settings['cg_seed']}
    assert untouched == render('cg-production-v1', base)
    assert 'rlist' not in parsed(untouched)

    chosen = cg.normalize_settings({'nstlog': 500, 'nstenergy': 250, 'nstxtcout': 400, 'xtc_precision': 750,
                                    'nstcomm': 50, 'nstlist': 30, 'verlet_buffer_tolerance': 0.002,
                                    'rlist': 1.25, 'rcoulomb': 1.0, 'rvdw': 1.0, 'tau_t': 0.5, 'tau_p': 8.0,
                                    'compressibility': 4e-5})
    written = parsed(render('cg-production-v1', cg.mdp_values(chosen, 'cg-production-v1')))
    assert written['nstlog'] == '500' and written['nstenergy'] == '250'
    assert written['nstxtcout'] == '400' and written['xtc-precision'] == '750'
    assert written['nstcomm'] == '50' and written['nstlist'] == '30'
    assert written['verlet-buffer-tolerance'] == '0.002' and written['rlist'] == '1.25'
    assert written['rcoulomb'] == '1' and written['rvdw'] == '1'
    assert written['tau-t'] == '0.5' and written['tau-p'] == '8' and written['compressibility'] == '4e-05'
    # The one option the run did not name keeps the reviewed value.
    assert written['gen-temp'] == str(settings['temperature_k'])

    # The equilibration leg keeps its own reviewed cadence: an override belongs to production only.
    assert cg.mdp_values(chosen, 'cg-equilibration-v1').get('nstlog') is None
    # Only the declared variable options are overrideable; the rest is the reviewed physics.
    with pytest.raises(ValueError, match='takes no run value'):
        render('cg-production-v1', {'dt': 0.01})


def test_the_cg_production_form_starts_on_the_reviewed_numbers():
    """Any drift between the form's defaults and the profile would silently change an untouched run."""
    numbers = cg._production_defaults()
    settings = PROFILES['cg-production-v1'].settings
    for setting, mdp in cg.PRODUCTION_OVERRIDES.items():
        if mdp in settings and isinstance(settings[mdp], (int, float)):
            assert numbers[setting] == settings[mdp], setting
        else:
            assert setting not in numbers, setting
    # The two the profile leaves to GROMACS have no default: an empty control is the reviewed rule.
    assert 'rlist' not in numbers and 'nstxtcout' not in numbers


def test_a_run_may_name_the_constraint_set_the_force_field_block_writes():
    """The entry's constraints are the protocol default, not a setting the run cannot reach.

    The force-field entry pins `all-bonds` (the paper's choice, not the manual's `h-bonds`), and that stays the
    default an untouched run renders. A run that names another value gets it in every AA MDP -- including the two
    legs that only make a box -- because the constraint set is one property of the atomistic half.
    """
    entry = forcefields.entry()
    for profile in AA_KINDS.values():
        values = aa.mdp_values(aa.normalize_settings({'constraints': 'h-bonds'}), profile)
        assert parsed(render(profile, values))['constraints'] == 'h-bonds', profile
        # The default is the entry's own value, and both force fields state the same one.
        untouched = aa.mdp_values(aa.normalize_settings({}), profile)
        assert parsed(render(profile, untouched))['constraints'] == entry.constraints, profile


def test_the_constraint_set_defaults_to_the_force_fields_and_refuses_an_unlisted_one():
    """One vocabulary of values for the control, and the entry -- not a copied literal -- decides the default."""
    from dashboard.execution import forcefields

    assert aa.normalize_settings({})['constraints'] == forcefields.entry().constraints
    assert aa.normalize_settings({'constraints': 'none'})['constraints'] == 'none'
    with pytest.raises(ValueError, match='constraints must be one of none, h-bonds, all-bonds'):
        aa.normalize_settings({'constraints': 'all-angles'})
