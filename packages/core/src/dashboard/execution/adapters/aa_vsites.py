"""Build a pdb2gmx virtual-site topology for one AA molecule.

The AA pipeline normally consumes the molecule's stored ITP directly. A vsite run needs a topology the
force field can build: an RTP residue (from the ITP), the ligand's atom types and the MkVsites-derived
dummy types/constraints/`.vsd` entries added to a temporary copy of the force field, then
`gmx pdb2gmx -vsite <choice>`. Only the generated moleculetype, coordinates and the new atom types are
written into the run; the force field itself stays referenced where it lives.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ... import files
from ...models.molecules import rtp as rtp_builder
from ...models.molecules import vsites
from .. import tools
from ..environment import environment


class VsiteBuildError(ValueError):
    """A virtual-site topology cannot be built for this molecule and choice."""


@dataclass(frozen=True)
class VsiteTopology:
    molecule_itp: str
    molecule_gro: str
    atomtypes_rows: tuple[str, ...]
    constrainttypes_rows: tuple[str, ...]
    atom_count: int
    charge: float
    mass: float
    report: dict
    rtp_text: str
    command: tuple[str, ...]
    overlay: dict


@dataclass(frozen=True)
class _AtomTotal:
    count: int
    charge: float
    mass: float


def _atom_total(text: str) -> _AtomTotal:
    """The atoms section's count, charge sum and mass sum; a missing mass column is read from [ atomtypes ]."""
    section = ''
    atomtypes: dict[str, float] = {}
    atoms: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line or line.startswith('#'):
            continue
        directive = re.fullmatch(r'\[\s*(\S+)\s*\]', line)
        if directive:
            section = directive.group(1).lower()
            continue
        fields = line.split()
        if section == 'atomtypes' and len(fields) >= 3:
            atomtypes[fields[0]] = float(fields[2])
        elif section == 'atoms':
            atoms.append(fields)
    if not atoms:
        raise VsiteBuildError('the source topology has no [ atoms ] section')
    charge = 0.0
    mass = 0.0
    for fields in atoms:
        if len(fields) < 7:
            raise VsiteBuildError('a source atom row needs nr type resnr resid atom cgnr charge')
        charge += float(fields[6])
        if len(fields) > 7:
            mass += float(fields[7])
        elif fields[1] in atomtypes:
            mass += atomtypes[fields[1]]
        else:
            raise VsiteBuildError(f'atom type {fields[1]} has no mass in the topology')
    return _AtomTotal(len(atoms), charge, mass)


def _source_atomtypes(text: str) -> dict[str, tuple[str, ...]]:
    section = ''
    found: dict[str, tuple[str, ...]] = {}
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line or line.startswith('#'):
            continue
        directive = re.fullmatch(r'\[\s*(\S+)\s*\]', line)
        if directive:
            section = directive.group(1).lower()
            continue
        if section == 'atomtypes':
            fields = tuple(line.split())
            if len(fields) < 7:
                raise VsiteBuildError('a source [ atomtypes ] row needs type at.num mass charge ptype sigma epsilon')
            found[fields[0]] = fields
    return found


def _base_atomtypes(text: str) -> dict[str, tuple[str, ...]]:
    section = ''
    found: dict[str, tuple[str, ...]] = {}
    for raw in text.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line or line.startswith('#'):
            continue
        directive = re.fullmatch(r'\[\s*(\S+)\s*\]', line)
        if directive:
            section = directive.group(1).lower()
            continue
        if section == 'atomtypes':
            fields = tuple(line.split())
            if len(fields) >= 7:
                found[fields[0]] = fields
    return found


def _append_section(path: Path, section: str, rows: list[str]) -> None:
    """Insert rows at the end of `[ section ]`, or append the section when the file does not have it."""
    if not rows:
        return
    text = path.read_text()
    lines = text.splitlines()
    out: list[str] = []
    current = ''
    inserted = False
    for line in lines:
        directive = re.fullmatch(r'\[\s*(\S+)\s*\]', line.strip())
        if directive:
            if current == section and not inserted:
                out.extend(rows)
                inserted = True
            current = directive.group(1).lower()
        out.append(line)
    if current == section and not inserted:
        out.extend(rows)
    elif not inserted:
        out.extend(['', f'[ {section} ]', *rows])
    path.write_text('\n'.join(out) + '\n')


def _append_plain(path: Path, rows: list[str]) -> None:
    if not rows:
        return
    with path.open('a') as stream:
        stream.write('\n' + '\n'.join(rows) + '\n')


def _append_vsd(path: Path, groups: dict[str, list[str]]) -> None:
    """Add each dummy type's construction to its own group, keeping an existing group's other lines."""
    text = path.read_text() if path.is_file() else ''
    lines = text.splitlines()
    for name, rows in groups.items():
        header = f'[ {name} ]'
        if header in (line.strip() for line in lines):
            index = next(i for i, line in enumerate(lines) if line.strip() == header)
            insert_at = index + 1
            while insert_at < len(lines) and not lines[insert_at].strip().startswith('['):
                insert_at += 1
            lines[insert_at:insert_at] = rows
        else:
            lines += ['', header, *rows]
    path.write_text('\n'.join(lines).strip() + '\n')


def _overlay(force_field: Path, work: Path, *, source_text: str, report: dict, residue: str,
             rtp_text: str) -> dict:
    """A copy of the force field with the ligand types, dummy types, constraints and .vsd entries."""
    target = work / 'vsite.ff'
    shutil.copytree(force_field, target)
    source_types = _source_atomtypes(source_text)
    base_types = _base_atomtypes((target / 'ffnonbonded.itp').read_text())
    new_types: list[str] = []
    for name, fields in source_types.items():
        if name in base_types:
            if base_types[name][1:] != fields[1:]:
                raise VsiteBuildError(
                    f'atom type {name} already exists in {force_field.name} with different parameters; '
                    'a vsite topology cannot safely redefine it')
            continue
        new_types.append(name)
    dummy_lines = list((report.get('forcefield') or {}).get('dummy_masses') or [])
    dummy_names = [line.split()[0] for line in dummy_lines]
    for line in dummy_lines:
        name = line.split()[0]
        if name in base_types or name in source_types:
            raise VsiteBuildError(f'dummy atom type {name} collides with an existing type')
        new_types.append(name)
    if new_types:
        _append_section(target / 'ffnonbonded.itp', 'atomtypes',
                        [ ' '.join(source_types[name]) for name in new_types if name in source_types ]
                        + [line for line in dummy_lines if line.split()[0] not in source_types ])
        _append_plain(target / 'atomtypes.atp',
                      [f'{name} {source_types[name][2]}' for name in new_types if name in source_types]
                      + [f'{name} 0.00000' for name in dummy_names])
    constraints = list((report.get('forcefield') or {}).get('constraints') or []) \
        + list((report.get('forcefield') or {}).get('angle_constraints') or [])
    if constraints:
        _append_section(target / 'ffbonded.itp', 'constrainttypes', constraints)
    vsd_lines = list((report.get('forcefield') or {}).get('vsd') or [])
    groups: dict[str, list[str]] = {}
    for line in vsd_lines:
        dummy = line.split()[-1]
        match = re.fullmatch(r'M([A-Z][a-z]?)H(\d+)_\d+', dummy)
        if not match:
            raise VsiteBuildError(f'cannot map dummy type {dummy!r} to a .vsd group')
        group = f'{match.group(1)}H{match.group(2)}'
        if group not in ('CH3', 'NH3', 'NH2'):
            raise VsiteBuildError(f'the .vsd database has no construction for {group} ({dummy})')
        groups.setdefault(group, []).append(line)
    if groups:
        _append_vsd(target / 'aminoacids.vsd', groups)
    (target / 'vsite.rtp').write_text(rtp_text)
    rows = [ ' '.join(source_types[name]) for name in new_types if name in source_types ] + \
        [line for line in dummy_lines if line.split()[0] not in source_types]
    return {'atomtypes': new_types, 'atomtypes_rows': rows, 'constraints': constraints, 'vsd': vsd_lines}


def _run_pdb2gmx(work: Path, *, coordinates: Path, water: str, choice: str) -> tuple[Path, Path, tuple[str, ...]]:
    gmx = tools.tool_path('gmx')
    if gmx is None:
        raise VsiteBuildError('gmx is not available, so a vsite topology cannot be built')
    run = work / 'run'
    run.mkdir()
    command = (gmx, 'pdb2gmx', '-f', str(Path(coordinates).resolve()), '-o', 'out.gro', '-p', 'out.top',
               '-i', 'posre.itp', '-ff', 'vsite', '-water', water, '-vsite', choice)
    result = subprocess.run(command, cwd=run, input='\n', capture_output=True, text=True,
                            env=dict(environment(), GMXLIB=str(work)))
    if result.returncode != 0 or not (run / 'out.top').is_file() or not (run / 'out.gro').is_file():
        tail = [line for line in (result.stdout + result.stderr).splitlines()
                if 'Authorization required' not in line and 'hwloc/' not in line]
        raise VsiteBuildError('pdb2gmx refused the vsite topology: ' + ' / '.join(tail[-30:]))
    return run / 'out.gro', run / 'out.top', command


def _molecule_block(topology: str, residue: str) -> str:
    lines = topology.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == '[ moleculetype ]')
    except StopIteration as exc:
        raise VsiteBuildError('pdb2gmx wrote no [ moleculetype ] block') from exc
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith('#include') or stripped.startswith('; Include'):
            end = index
            break
    block = lines[start:end]
    name = next(i for i, line in enumerate(block) if i and line.strip() and not line.startswith(';'))
    parts = block[name].split()
    nrexcl = parts[1] if len(parts) > 1 else '3'
    block[name] = f'{residue} {nrexcl}'
    return '\n'.join(block) + '\n'


def _generated_total(block: str) -> _AtomTotal:
    section = ''
    atoms: list[list[str]] = []
    for raw in block.splitlines():
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        directive = re.fullmatch(r'\[\s*(\S+)\s*\]', line)
        if directive:
            section = directive.group(1).lower()
            continue
        if section == 'atoms':
            atoms.append(line.split())
    if not atoms:
        raise VsiteBuildError('the generated topology has no atoms')
    return _AtomTotal(len(atoms), sum(float(row[6]) for row in atoms), sum(float(row[7]) for row in atoms))


def build(*, source_topology: Path, coordinates: Path, force_field: Path, water: str, residue: str,
          choice: str) -> VsiteTopology:
    """Build the pdb2gmx topology for one molecule; raises `VsiteBuildError` with the reason."""
    if choice not in ('hydrogens', 'aromatics'):
        raise VsiteBuildError(f'unsupported virtual-site choice {choice!r}')
    text = source_topology.read_text(encoding='utf-8')
    report = vsites.derive_from_itp(source_topology, force_field=force_field)
    if not report.get('vsites') and not report.get('angle_constraints'):
        raise VsiteBuildError('MkVsites derived no virtual-site construct for this topology')
    rtp_text = rtp_builder.from_itp(text, residue=residue, source=str(source_topology))
    with tempfile.TemporaryDirectory(prefix='.vsite-') as temporary:
        work = Path(temporary)
        overlay = _overlay(force_field, work, source_text=text, report=report, residue=residue, rtp_text=rtp_text)
        gro, top, command = _run_pdb2gmx(work, coordinates=coordinates, water=water, choice=choice)
        block = _molecule_block(top.read_text(), residue)
        source_total = _atom_total(text)
        generated = _generated_total(block)
        if abs(source_total.charge - generated.charge) > 1e-3:
            raise VsiteBuildError(
                f'the vsite topology changes the net charge ({source_total.charge:g} -> {generated.charge:g})')
        if abs(source_total.mass - generated.mass) > 1e-2:
            raise VsiteBuildError(
                f'the vsite topology changes the total mass ({source_total.mass:g} -> {generated.mass:g})')
        return VsiteTopology(
            molecule_itp=block,
            molecule_gro=gro.read_text(),
            atomtypes_rows=tuple(overlay['atomtypes_rows']),
            constrainttypes_rows=tuple(overlay['constraints']),
            atom_count=generated.count,
            charge=generated.charge,
            mass=generated.mass,
            report=report,
            rtp_text=rtp_text,
            command=command,
            overlay=overlay,
        )


def write_artifacts(topology: VsiteTopology, molecule: Path, *, source: str, settings: dict) -> dict:
    """Write the generated files and the provenance JSON into the run's `common/molecule/`."""
    (molecule / 'molecule.itp').write_text(topology.molecule_itp)
    (molecule / 'molecule.gro').write_text(topology.molecule_gro)
    if topology.atomtypes_rows:
        (molecule / 'atomtypes.itp').write_text('[ atomtypes ]\n' + '\n'.join(topology.atomtypes_rows) + '\n')
    if topology.constrainttypes_rows:
        (molecule / 'constrainttypes.itp').write_text('[ constrainttypes ]\n' + '\n'.join(topology.constrainttypes_rows) + '\n')
    record = {
        'method': 'pdb2gmx + MkVsites',
        'choice': settings['vsite'],
        'source_topology': source,
        'command': list(topology.command),
        'rtp_sha256': hashlib.sha256(topology.rtp_text.encode()).hexdigest(),
        'report': topology.report,
        'overlay': topology.overlay,
        'generated': {
            'topology_sha256': hashlib.sha256(topology.molecule_itp.encode()).hexdigest(),
            'coordinates_sha256': hashlib.sha256(topology.molecule_gro.encode()).hexdigest(),
            'atom_count': topology.atom_count,
            'charge': topology.charge,
            'mass': topology.mass,
        },
    }
    files.atomic_json(molecule / 'vsite.json', record)
    return record

