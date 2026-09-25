"""Read-only molecule context for CG mapping editors.

This module reads canonical AA inputs without generating metadata or changing
the selected molecule directory.  Mapping identity and rendering consume this
normalized context instead of the historical DDM singleton.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from ..molecules import aa as aa_molecules
from .identity import canonical_sha256

_SECTION_RE = re.compile(r"^\s*\[\s*([^]]+)\s*\]")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _element(name: str) -> str | None:
    token = re.sub(r"[^A-Za-z]", "", name or "")
    if not token:
        return None
    token = token.upper()
    if token[:2] in {"CL", "BR"}:
        return token[:2].title()
    return token[0].upper()


def _parse_topology(expanded: str):
    section = ""
    atoms = {}
    bonds = []
    seen_bond_keys = set()
    for raw in expanded.splitlines():
        line = raw.split(";", 1)[0].strip()
        match = _SECTION_RE.match(line)
        if match:
            section = match.group(1).strip().lower()
            continue
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if section == "atoms":
            if len(fields) < 7:
                raise ValueError("molecule.itp: incomplete atom definition")
            index = int(fields[0])
            if index != len(atoms) + 1:
                raise ValueError("molecule.itp: atom IDs must be contiguous")
            charge = float(fields[6])
            mass = float(fields[7]) if len(fields) > 7 else None
            if not math.isfinite(charge) or (mass is not None and not math.isfinite(mass)):
                raise ValueError("molecule.itp: atom charge or mass is nonfinite")
            atoms[index] = {
                "name": fields[4],
                "residue": fields[3],
                "charge": charge,
                "mass": mass,
                "element": _element(fields[4]),
            }
        elif section in {"bonds", "constraints"} and len(fields) >= 2:
            a, b = int(fields[0]), int(fields[1])
            if a == b:
                continue
            key = tuple(sorted((a, b)))
            if key not in seen_bond_keys:
                seen_bond_keys.add(key)
                bonds.append({"a": key[0], "b": key[1], "order": 1,
                              "order_source": "itp"})
    if not atoms:
        raise ValueError("molecule.itp: expected a nonempty atoms section")
    return atoms, bonds


def _coordinate_records(folder: Path, inputs: dict):
    path = folder / inputs["coordinates"]
    raw = aa_molecules._read(path)
    text = raw.decode()
    if inputs["coordinate_format"] == "pdb":
        text = aa_molecules.pdb_gro(text)
    return aa_molecules._gro(text), raw


def _chemical_sources(folder: Path, inputs: dict):
    result = {}
    suffixes = {".mol2", ".sdf", ".smiles", ".smi"}
    coordinate_path = folder / inputs["coordinates"]
    topology_path = folder / inputs["topology"]
    roots = {topology_path.parent, coordinate_path.parent, folder}
    for root in sorted(roots):
        if not root.is_dir() or root.is_symlink():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink() or path == coordinate_path:
                continue
            if path.suffix.lower() in suffixes:
                try:
                    relative = path.relative_to(folder).as_posix()
                except ValueError:
                    continue
                result[relative] = aa_molecules._read(path)
    return result


def _chemical_projection(chemical: dict, atoms: list[dict]):
    """Return verified bond orders and 2D positions when a source maps cleanly."""
    if not chemical:
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem import rdDepictor
        for path, raw in sorted(chemical.items()):
            if path.lower().endswith(".mol2"):
                mol = Chem.MolFromMol2Block(raw.decode(), removeHs=False, sanitize=True)
            elif path.lower().endswith(".sdf"):
                mol = Chem.MolFromMolBlock(raw.decode(), removeHs=False, sanitize=True)
            else:
                continue
            if mol is None or mol.GetNumAtoms() != len(atoms):
                continue
            names = [atom.GetProp("_TriposAtomName") if atom.HasProp("_TriposAtomName") else atom.GetSymbol() for atom in mol.GetAtoms()]
            if names != [record["name"] for record in atoms]:
                continue
            rdDepictor.Compute2DCoords(mol, canonOrient=True, clearConfs=True)
            conformer = mol.GetConformer()
            positions = {index + 1: [float(conformer.GetAtomPosition(index).x),
                                      float(conformer.GetAtomPosition(index).y)]
                         for index in range(mol.GetNumAtoms())}
            orders = {tuple(sorted((bond.GetBeginAtomIdx() + 1, bond.GetEndAtomIdx() + 1))):
                      float(bond.GetBondTypeAsDouble()) for bond in mol.GetBonds()}
            return positions, orders, path
        return None
    except (ImportError, OSError, ValueError, RuntimeError, UnicodeError):
        return None


def as_structure(context: dict) -> dict:
    """Return the legacy {'atoms','bonds','source','bond_source'} adapter shape.

    Consumers that predate this module (mappings.validate, mapping_suggestions,
    carbohydrates.candidate) expect simple integer tuples for bonds rather than
    the richer {'a','b','order',...} records produced by build_context.
    """
    return {
        'atoms': context.get('atoms', []),
        'bonds': [[edge['a'], edge['b']] for edge in context.get('bonds', [])],
        'source': context.get('path', ''),
        'bond_source': context.get('path', ''),
    }


def build_context(root: Path, molecule_id: str) -> dict:
    """Build a validated, read-only mapping context for one molecule folder."""
    aa_molecules.validate_id(molecule_id)
    root = Path(root)
    folder = root / molecule_id
    if root.is_symlink() or folder.is_symlink() or not folder.is_dir():
        raise ValueError("Molecule directory is unavailable or is a symlink")
    inputs = aa_molecules.discover(folder)
    expanded, dependencies = aa_molecules.topology_tree(folder, inputs["topology"])
    topology_atoms, bonds = _parse_topology(expanded)
    coordinates, coordinate_raw = _coordinate_records(folder, inputs)
    if len(coordinates) != len(topology_atoms):
        raise ValueError("Coordinates and topology atom counts differ")
    atoms = []
    for index, (residue, name, xyz) in enumerate(coordinates, 1):
        topology = topology_atoms[index]
        if (residue, name) != (topology["residue"], topology["name"]):
            raise ValueError("Coordinates and topology atom order differ")
        element = topology["element"]
        mass = topology["mass"]
        heavy = mass is not None and mass > 2.0 if mass is not None else element not in {None, "H"}
        atoms.append({"id": index, "name": name, "residue": residue, "element": element,
                      "heavy": bool(heavy), "charge": topology["charge"],
                      "xyz": [float(v) for v in xyz],
                      "display_xy": [float(xyz[0]), float(xyz[1])]})
    known = {atom["id"] for atom in atoms}
    if any(edge["a"] not in known or edge["b"] not in known for edge in bonds):
        raise ValueError("Topology bond references an unknown atom")

    files = dict(dependencies)
    files[inputs["coordinates"]] = coordinate_raw
    metadata_path = folder / "metadata.json"
    if metadata_path.is_file() and not metadata_path.is_symlink():
        files["metadata.json"] = aa_molecules._read(metadata_path)
    chemical = _chemical_sources(folder, inputs)
    files.update(chemical)
    file_hashes = {name: _sha256(value) for name, value in sorted(files.items())}
    atom_order = [{key: atom[key] for key in ("id", "name", "residue", "element", "heavy")} for atom in atoms]
    atom_order_hash = canonical_sha256(atom_order)
    snapshot = {"files": file_hashes, "atom_order_sha256": atom_order_hash}
    snapshot["snapshot_sha256"] = canonical_sha256(snapshot)
    projection = _chemical_projection(chemical, atoms)
    if projection:
        positions, orders, source = projection
        for atom in atoms:
            atom["display_xy"] = positions[atom["id"]]
        for bond in bonds:
            key = (bond["a"], bond["b"])
            if key in orders:
                bond["order"] = orders[key]
                bond["order_source"] = "chemical"
    source_quality = {
        "bond_order": "chemical" if projection else "fallback",
        "chemical_sources": [projection[2]] if projection else sorted(chemical),
        "warnings": [] if projection else ["No verified chemical graph source found; bonds use ITP single-bond fallback."],
    }
    return {
        "molecule_id": molecule_id,
        "name": molecule_id,
        "path": f"molecules/{molecule_id}",
        "inputs": inputs,
        "atoms": atoms,
        "bonds": bonds,
        "source_quality": source_quality,
        "capabilities": {
            "manual": {"available": True, "reasons": []},
            "automatic": {"available": bool(projection), "reasons": [] if projection else ["A verified chemical graph source is required for automatic suggestions."]},
        },
        "snapshot": snapshot,
    }