"""The PME policy: a reaction-field stage names no PME, and a PME scheme on it is refused, not recorded.

Run `6ed68979edf0` asked a CG production leg for `mdrun_pme: gpu`; its MDPs use `coulombtype = reaction-field`, so
GROMACS refused at mdrun startup ("Cannot compute PME interactions on a GPU ... Systems that do not use PME for
electrostatics") after a full minimisation. The New run form offered the scheme to every run type, the builder passed
it through, and the settings recorded a choice that could not act. The policy is now one answer: only atomistic
stages compute PME, the CG-family normalizers retire the three PME settings, and the builder emits neither `-pme` nor
`-pmefft` for a non-PME stage.
"""
import pytest
from dashboard.execution import workflow
from dashboard.execution.adapters import aa, cg, composition

DEVICE = {'mdrun_gpu': 0, 'mdrun_nb': 'gpu', 'mdrun_update': 'auto'}
RETIRED = {'mdrun_pme', 'mdrun_pmefft', 'mdrun_tunepme'}


@pytest.fixture
def gpu(monkeypatch):
    """A host that reports a device, so the offload brackets are built rather than skipped."""
    monkeypatch.setattr(aa.devices, 'present', lambda: True)
    return DEVICE


def test_a_non_pme_stage_gets_no_pme_or_fft_flag(gpu):
    """Both brackets: the equilibration one never had PME, and the production one must not add it here."""
    for stage in ('equilibration', 'production'):
        _, flags = aa.mdrun_command_flags(dict(gpu, mdrun_pme='auto', mdrun_pmefft='auto'), stage, 'mpi', pme=False)
        assert '-pme' not in flags and '-pmefft' not in flags, (stage, flags)


def test_an_aa_stage_still_places_pme_on_the_gpu(gpu):
    """The control: the AA production bracket is unchanged."""
    _, flags = aa.mdrun_command_flags(dict(gpu, mdrun_pme='auto', mdrun_pmefft='auto'), 'production', 'mpi')
    assert '-pme gpu' in flags and '-pmefft gpu' in flags


def test_a_pme_scheme_on_a_reaction_field_stage_is_refused(gpu):
    """A scheme that names a device is refused with the reason, before a command is written."""
    with pytest.raises(ValueError, match='reaction-field'):
        aa.mdrun_command_flags(dict(gpu, mdrun_pme='gpu'), 'production', 'mpi', pme=False)
    with pytest.raises(ValueError, match='reaction-field'):
        aa.mdrun_command_flags(dict(gpu, mdrun_pmefft='gpu'), 'production', 'mpi', pme=False)


def test_the_policy_follows_the_run_type_and_the_stage():
    """Atomistic stages compute PME; every CG-family leg is reaction-field."""
    assert workflow._uses_pme({'run_type': 'aa_only'}, 'AA NPT production') is True
    assert workflow._uses_pme({'run_type': 'cg'}, 'CG simulation') is False
    assert workflow._uses_pme({'run_type': 'cg'}, 'AA reference') is True
    assert workflow._uses_pme({'run_type': 'pdc'}, 'CG assessment') is False
    assert workflow._uses_pme({'run_type': 'osmotic'}, 'equilibration') is False
    assert workflow._uses_pme({}, 'CG simulation') is False


def test_the_cg_family_normalizers_retire_those_settings():
    """A CG run has no PME, so the three keys are not settings of it -- including on a retried old job."""
    cg_values = cg.normalize_settings(dict(DEVICE, mdrun_pme='gpu', mdrun_pmefft='gpu', mdrun_tunepme='on'))
    composition_values = composition.normalize_settings({'mdrun_gpu': 0, 'mdrun_pme': 'gpu',
                                                         'mdrun_pmefft': 'gpu', 'mdrun_tunepme': 'on'})
    assert not RETIRED & set(cg_values)
    assert not RETIRED & set(composition_values)
