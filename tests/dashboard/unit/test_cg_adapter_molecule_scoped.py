"""Molecule-scoped CG runs must consume a shared AA reference."""
import copy
import json
from pathlib import Path

import pytest

from dashboard.execution.adapters import cg
from dashboard.execution.adapters.cg_names import CGNames
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
