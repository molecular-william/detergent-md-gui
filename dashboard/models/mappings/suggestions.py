"""Deterministic, explainable mapping suggestions."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .. import carbohydrates
from .context import as_structure

def _candidate_types(index, atom_count):
    size = "R" if atom_count >= 4 else "S" if atom_count == 3 else "T"
    records = [item for item in index.get("records", []) if item.get("size") == size]
    unique = {}
    for item in records:
        unique.setdefault(item["type"], item)
    return [unique[key] for key in sorted(unique, key=lambda key: (unique[key]["source_rank"], key))]


def suggest_bead(context: dict, atom_ids: list[int], index: dict) -> dict:
    selected = set(atom_ids)
    atoms = {atom["id"]: atom for atom in context.get("atoms", [])}
    if not selected or any(atom_id not in atoms or not atoms[atom_id].get("heavy") for atom_id in selected):
        return {"suggestions": [], "warnings": ["Select one or more known heavy atoms."]}
    elements = sorted(atoms[atom_id].get("element") or "?" for atom_id in selected)
    oxygens = elements.count("O")
    suggestions = []
    for record in _candidate_types(index, len(selected))[:3]:
        source_rank = record["source_rank"]
        evidence = "exact-context" if source_rank == 1 and oxygens else "fragment-match" if source_rank < 3 else "heuristic"
        suggestions.append({"size": record["size"], "type": record["type"],
                            "reason": f"{len(selected)} heavy atoms ({', '.join(elements)}); {record['name']} reference match.",
                            "confidence": evidence, "references": deepcopy(record["references"]),
                            "fragment_id": record["fragment_id"]})
    if not suggestions:
        size = "R" if len(selected) >= 4 else "S" if len(selected) == 3 else "T"
        suggestions.append({"size": size, "type": None,
                            "reason": "No verified functional-group match; review bead chemistry manually.",
                            "confidence": "heuristic", "references": [], "fragment_id": None})
    warnings = []
    if not context.get("source_quality", {}).get("bond_order") == "chemical":
        warnings.append("Bond-order-dependent reference matches are unavailable for graph fallback input.")
    return {"suggestions": suggestions, "warnings": warnings}


def _connected_groups(context):
    atoms = {atom["id"]: atom for atom in context.get("atoms", []) if atom.get("heavy")}
    adjacency = {atom_id: set() for atom_id in atoms}
    for edge in context.get("bonds", []):
        if edge["a"] in adjacency and edge["b"] in adjacency:
            adjacency[edge["a"]].add(edge["b"]); adjacency[edge["b"]].add(edge["a"])
    remaining = set(atoms); groups = []
    while remaining:
        seed = min(remaining); group = {seed}; remaining.remove(seed); frontier = set(adjacency[seed]) & remaining
        while frontier and len(group) < 4:
            atom_id = min(frontier); frontier.discard(atom_id)
            if atom_id not in remaining: continue
            group.add(atom_id); remaining.remove(atom_id); frontier |= adjacency[atom_id] & remaining
        groups.append(sorted(group))
    return groups


def generate_baseline(context: dict, index: dict) -> dict:
    """Generate one deterministic preview; never writes a candidate file."""
    if not context.get("capabilities", {}).get("automatic", {}).get("available"):
        return {"available": False, "candidate": None,
                "reasons": context.get("capabilities", {}).get("automatic", {}).get("reasons", [])}
    structure = as_structure(context)
    try:
        candidate = carbohydrates.candidate(structure, context["molecule_id"])
    except (ValueError, KeyError) as exc:
        return {"available": False, "candidate": None, "reasons": [str(exc)]}
    if candidate is None:
        groups = _connected_groups(context)
        beads = []
        for index_number, group in enumerate(groups, 1):
            suggestion = suggest_bead(context, group, index)["suggestions"][0]
            size = suggestion["size"]
            beads.append({"name": f"BEAD{index_number:02d}", "size": size,
                          "type": suggestion["type"], "atoms": group,
                          "suggestion": suggestion})
        candidate = {"name": f"{context['molecule_id']} generic graph draft", "beads": beads,
                     "rings": [], "connections": [], "schema_version": 3,
                     "molecule_id": context["molecule_id"],
                     "molecule_snapshot": deepcopy(context["snapshot"]),
                     "status": "candidate-unvalidated", "martini_version": "3",
                     "source_structure": context.get("path", ""),
                     "limitations": ["No verified molecule-specific sugar or fragment template matched."]}
    else:
        candidate = deepcopy(candidate)
        candidate["schema_version"] = 3
        candidate["molecule_id"] = context["molecule_id"]
        candidate["molecule_snapshot"] = deepcopy(context["snapshot"])
    algorithm = {"name": "in-house-sugar-first-graph", "version": "1",
                 "parameters": {"max_group_heavy_atoms": 4, "tie_break": "ascending-aa-id"},
                 "reference_index_sha256": index.get("index_sha256")}
    candidate["provenance"] = {**candidate.get("provenance", {}), "origin": "automatic",
                                "algorithm": algorithm, "references": [
                                    reference for bead in candidate.get("beads", [])
                                    for reference in bead.get("suggestion", {}).get("references", [])]}
    candidate.pop("file", None); candidate.pop("sha256", None); candidate.pop("validation", None)
    return {"available": True, "candidate": candidate, "reasons": []}
