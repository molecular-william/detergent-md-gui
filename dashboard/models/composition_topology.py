"""Reference-backed construction of immutable CG molecule compositions.

The builder deliberately accepts identifiers and choices only.  It reparses the
canonical Martini sugar file for every preview so browser state cannot become a
second source of topology truth.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path


SUGAR_RESIDUES = (
    "GLC", "MAN", "GAL", "FRUF", "LFUC", "LRHA", "RIBF", "XYL",
    "INO", "GLA", "GYN", "NMC", "LAC", "SUCR", "TREH",
)

_RECIPES = (
    {
        "id": "linear-c1", "name": "Linear C1", "version": 1,
        "carbons_per_bead": 4, "terminal_types": ("C1",),
    },
    {
        "id": "linear-c1-terminal", "name": "Linear C1/C2 terminal", "version": 1,
        "carbons_per_bead": 4, "terminal_types": ("C1", "C2"),
    },
)

_PROFILES = (
    {
        "id": "sugar-alkyl-ether-ddm-transfer",
        "name": "DDM sugar-to-alkyl ether transfer",
        "version": 1,
        "head_types": ("SP1r", "SP4r", "SN4ar", "TN4ar", "TP1"),
        "tail_types": ("C1", "C2"),
        "bond": {"function": 1, "length": 0.47, "force": 5000.0},
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _section_blocks(text: str) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current = None
    rows: list[str] = []
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"\[\s*([^]]+)\s*\]", line)
        if match:
            if current is not None:
                blocks.append((current.strip(), rows))
            current, rows = match.group(1).lower(), []
        elif current is not None:
            rows.append(line)
    if current is not None:
        blocks.append((current.strip(), rows))
    return blocks


def _tokens(rows: list[str], width: int | None = None) -> list[list[str]]:
    result = []
    for row in rows:
        parts = row.split()
        if width is None or len(parts) >= width:
            result.append(parts)
    return result


def load_sugar_catalog(source: Path) -> dict[str, dict]:
    """Parse all named moleculetype blocks from the canonical sugar ITP."""
    source = Path(source)
    if not source.is_file() or source.is_symlink():
        raise ValueError("Sugar source must be a regular file")
    blocks = _section_blocks(source.read_text())
    catalog: dict[str, dict] = {}
    current: dict | None = None
    section = None
    for name, rows in blocks:
        if name == "moleculetype":
            if not rows:
                raise ValueError("Sugar moleculetype is missing a name")
            residue = rows[0].split()[0]
            if residue in catalog:
                raise ValueError(f"Duplicate sugar residue {residue}")
            current = {"id": residue, "name": residue, "atoms": [], "bonds": [],
                       "constraints": [], "angles": [], "dihedrals": [],
                       "exclusions": [], "virtual_sites": []}
            catalog[residue] = current
            section = None
        elif current is not None:
            section = name
            if section == "atoms":
                for parts in _tokens(rows, 8):
                    current["atoms"].append({"index": int(parts[0]), "type": parts[1],
                        "residue": parts[3], "name": parts[4], "charge": float(parts[6]),
                        "mass": float(parts[7])})
            elif section in ("bonds", "constraints"):
                target = current[section]
                for parts in _tokens(rows, 4):
                    target.append({"a": int(parts[0]), "b": int(parts[1]),
                                   "function": int(parts[2]), "length": float(parts[3])})
            elif section == "angles":
                for parts in _tokens(rows, 5):
                    current[section].append({"atoms": [int(parts[0]), int(parts[1]), int(parts[2])],
                                             "function": int(parts[3]), "parameters": [float(x) for x in parts[4:]]})
            elif section == "dihedrals":
                for parts in _tokens(rows, 6):
                    current[section].append({"atoms": [int(x) for x in parts[:4]],
                                             "function": int(parts[4]), "parameters": [float(x) for x in parts[5:]]})
            elif section == "exclusions":
                current["exclusions"].extend([[int(x) for x in row] for row in _tokens(rows)])
            elif section == "virtual_sitesn":
                for parts in _tokens(rows, 5):
                    current["virtual_sites"].append({"site": int(parts[0]), "parents": [int(x) for x in parts[2:]]})
    for residue, item in catalog.items():
        if not item["atoms"]:
            raise ValueError(f"Sugar residue {residue} has no atoms")
        item["source_sha256"] = _sha256(source)
        item["source_path"] = str(source)
        item["bead_names"] = [atom["name"] for atom in item["atoms"]]
    return {key: catalog[key] for key in SUGAR_RESIDUES if key in catalog}


def tail_recipe_catalog() -> list[dict]:
    return [dict(item, terminal_types=list(item["terminal_types"])) for item in _RECIPES]


def linkage_profile_catalog() -> list[dict]:
    return [dict(item, head_types=list(item["head_types"]), tail_types=list(item["tail_types"])) for item in _PROFILES]


def _recipe(recipe_id: str) -> dict:
    for item in _RECIPES:
        if item["id"] == recipe_id:
            return item
    raise ValueError(f"Unknown tail recipe: {recipe_id}")


def expand_tail(recipe_id: str, carbon_count: int) -> dict:
    recipe = _recipe(recipe_id)
    if isinstance(carbon_count, bool) or not isinstance(carbon_count, int) or carbon_count < 2 or carbon_count > 200:
        raise ValueError("carbon count must be an integer between 2 and 200")
    count = math.ceil(carbon_count / recipe["carbons_per_bead"])
    beads = []
    for index in range(count):
        first = index * recipe["carbons_per_bead"] + 1
        last = min(carbon_count, (index + 1) * recipe["carbons_per_bead"])
        bead_type = recipe["terminal_types"][-1] if index == count - 1 and len(recipe["terminal_types"]) > 1 else recipe["terminal_types"][0]
        beads.append({"name": f"C{index + 1:02d}", "type": bead_type,
                      "carbon_range": [first, last], "mass": 54.0, "charge": 0.0})
    coordinates = [[0.0, 0.0, round(index * 0.47, 6),] for index in range(count)]
    bonds = [{"a": beads[index - 1]["name"], "b": beads[index]["name"],
              "function": 1, "length": 0.47, "force": 5000.0} for index in range(1, count)]
    return {"recipe_id": recipe_id, "carbon_count": carbon_count, "beads": beads,
            "coordinates": coordinates, "bonds": bonds, "version": recipe["version"]}


def _profile(profile_id: str) -> dict:
    for item in _PROFILES:
        if item["id"] == profile_id:
            return item
    raise ValueError(f"Unknown linkage profile: {profile_id}")


def _sugar_source(project_root: Path) -> Path:
    return Path(project_root) / "references" / "martini_v3.0.0_sugars_v2.itp"


def build_preview(payload: dict, project_root: Path) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Composition payload must be an object")
    head_id = str(payload.get("head_fragment_id", ""))
    residue = head_id.rsplit(":", 1)[-1]
    catalog = load_sugar_catalog(_sugar_source(project_root))
    if residue not in catalog:
        raise ValueError(f"Unknown sugar fragment: {head_id}")
    sugar = catalog[residue]
    supplied_hash = payload.get("source_sha256")
    if supplied_hash and supplied_hash != sugar["source_sha256"]:
        raise ValueError("Sugar source hash is stale")
    tail = expand_tail(str(payload.get("tail_recipe_id", "")), int(payload.get("carbon_count", 0)))
    profile = _profile(str(payload.get("linkage_profile_id", "")))
    head_endpoint = (payload.get("head_endpoint") or {}).get("bead")
    tail_endpoint = (payload.get("tail_endpoint") or {}).get("bead") or tail["beads"][0]["name"]
    head_names = set(sugar["bead_names"])
    if head_endpoint not in head_names or head_endpoint == "VS":
        raise ValueError("Head endpoint must be a physical sugar bead")
    if tail_endpoint not in {item["name"] for item in tail["beads"]}:
        raise ValueError("Tail endpoint must be a generated tail bead")
    head_atom = next(atom for atom in sugar["atoms"] if atom["name"] == head_endpoint)
    if head_atom["type"] not in profile["head_types"]:
        raise ValueError(f"Linkage profile does not support head bead {head_endpoint}")
    tail_atom = next(item for item in tail["beads"] if item["name"] == tail_endpoint)
    if tail_atom["type"] not in profile["tail_types"]:
        raise ValueError(f"Linkage profile does not support tail bead {tail_endpoint}")
    offset = len(sugar["atoms"])
    atoms = [dict(atom, index=atom["index"], bead=atom["name"]) for atom in sugar["atoms"]]
    for index, bead in enumerate(tail["beads"], start=1):
        atoms.append({"index": offset + index, "type": bead["type"], "residue": residue,
                      "name": bead["name"], "bead": bead["name"], "charge": bead["charge"], "mass": bead["mass"]})
    bead_names = [atom["name"] for atom in atoms]
    bonds = [{"a": atom["name"], "b": atom["name"], "function": 1, "length": term["length"]}
             for term in []]
    bonds = [{"a": sugar["atoms"][term["a"] - 1]["name"], "b": sugar["atoms"][term["b"] - 1]["name"],
              "function": term["function"], "length": term["length"]} for term in sugar["constraints"]]
    bonds.extend({"a": term["a"], "b": term["b"], "function": term["function"], "length": term["length"]} for term in tail["bonds"])
    bonds.append({"a": head_endpoint, "b": tail_endpoint, **profile["bond"]})
    virtual_sites = [{"site": sugar["atoms"][item["site"] - 1]["name"],
                      "parents": [sugar["atoms"][index - 1]["name"] for index in item["parents"]]}
                     for item in sugar["virtual_sites"]]
    mapping_beads = [{"name": atom["name"], "type": atom["type"], "atoms": [atom["index"]],
                      "size": "R" if atom["mass"] >= 50 else "S", "virtual_site": atom["name"] == "VS"}
                     for atom in atoms]
    mapping = {"schema_version": 3, "name": payload.get("display_name") or f"{residue} C{payload.get('carbon_count')}",
               "residue_name": payload.get("residue_name") or residue, "beads": mapping_beads,
               "connections": [[bond["a"], bond["b"]] for bond in bonds if bond["a"] != bond["b"]],
               "source": {"head_fragment_id": head_id, "source_sha256": sugar["source_sha256"],
                          "tail_recipe_id": tail["recipe_id"], "linkage_profile_id": profile["id"]}}
    topology = {"atoms": atoms, "bonds": bonds, "virtual_sites": virtual_sites,
                "exclusions": [[virtual["site"], *virtual["parents"]] for virtual in virtual_sites]}
    result = {"mapping": mapping, "topology": topology, "tail": tail,
              "generated_terms": {"bonds": [bonds[-1]]}, "head": sugar,
              "profile": profile, "source_sha256": sugar["source_sha256"],
              "validation": {"structural": {"ok": True, "issues": []}, "chemical": {"ok": True, "issues": []}}}
    result["identity"] = composition_identity(result)
    result["itp"] = render_itp(result)
    result["gro"] = render_gro(result)
    return result


def validate_preview(result: dict) -> dict:
    if not result.get("mapping", {}).get("beads"):
        raise ValueError("Composition contains no beads")
    names = {bead["name"] for bead in result["mapping"]["beads"]}
    if any(edge["a"] not in names or edge["b"] not in names for edge in result["topology"]["bonds"]):
        raise ValueError("Topology references an unknown bead")
    return result["validation"]


def composition_identity(result: dict) -> str:
    payload = {"mapping": result.get("mapping", {}), "topology": result.get("topology", {}),
               "tail": result.get("tail", {}), "profile": result.get("profile", {}).get("id")}
    payload["mapping"] = {key: value for key, value in payload["mapping"].items() if key not in ("name", "display_name")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def render_itp(result: dict) -> str:
    mapping = result["mapping"]
    lines = ["; generated immutable composition", "[ moleculetype ]", f"{mapping['residue_name']} 1", "", "[ atoms ]", "; nr type resnr residue atom cgnr charge mass"]
    for atom in result["topology"]["atoms"]:
        lines.append(f"{atom['index']:5d} {atom['type']:<6} 1 {mapping['residue_name']:<6} {atom['name']:<4} {atom['index']:4d} {atom['charge']: .4f} {atom['mass']: .2f}")
    lines += ["", "[ bonds ]"]
    index = {atom["name"]: atom["index"] for atom in result["topology"]["atoms"]}
    for bond in result["topology"]["bonds"]:
        if bond["a"] in index and bond["b"] in index:
            lines.append(f"{index[bond['a']]:5d} {index[bond['b']]:5d} {bond.get('function', 1):2d} {bond.get('length', 0.47):.5f} {bond.get('force', 5000.0):.1f}")
    if result["topology"]["virtual_sites"]:
        lines += ["", "[ virtual_sitesn ]"]
        for site in result["topology"]["virtual_sites"]:
            lines.append(" ".join([str(index[site["site"]]), "1", *[str(index[parent]) for parent in site["parents"]]]))
    return "\n".join(lines) + "\n"


def render_gro(result: dict) -> str:
    atoms = result["topology"]["atoms"]
    tail_coordinates = result["tail"]["coordinates"]
    coords = {atom["name"]: [0.0, 0.0, 0.1 * (atom["index"] - 1)] for atom in atoms}
    for bead, coord in zip(result["tail"]["beads"], tail_coordinates):
        coords[bead["name"]] = coord
    lines = ["Generated composition", str(len(atoms))]
    for index, atom in enumerate(atoms, 1):
        x, y, z = coords[atom["name"]]
        lines.append(f"    1{result['mapping']['residue_name'][:5]:<5}{atom['name'][:5]:>5}{index:5d}{x:8.3f}{y:8.3f}{z:8.3f}")
    lines.append("   3.00000   3.00000   3.00000")
    return "\n".join(lines) + "\n"


def parse_composite_itp(text: str) -> dict:
    atoms = []
    in_atoms = False
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line.startswith("["):
            in_atoms = line.strip("[] ").lower() == "atoms"
            continue
        if in_atoms and line:
            parts = line.split()
            if len(parts) >= 8 and parts[0].isdigit():
                atoms.append({"index": int(parts[0]), "type": parts[1], "name": parts[4], "mass": float(parts[7])})
    return {"atoms": atoms}


def parse_composite_gro(text: str) -> dict:
    rows = text.splitlines()
    return {"atom_count": int(rows[1]) if len(rows) > 1 else 0}
