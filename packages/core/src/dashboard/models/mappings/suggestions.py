"""Deterministic, explainable mapping suggestions."""
from __future__ import annotations

from copy import deepcopy

from .algorithms import DEFAULT as DEFAULT_ALGORITHM
from .algorithms import generate


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


def generate_baseline(context: dict, index: dict, algorithm: str = DEFAULT_ALGORITHM) -> dict:
    """Generate one deterministic preview; never writes a candidate file.

    The candidate itself is one of `algorithms`' builders, and `algorithms.generate` refuses to hand back
    a document this project's own validator rejects (`{available, reasons}` is what the route and the
    editor already read). `algorithm` defaults to the sugar-first connectivity path.
    """
    return generate(context, index, algorithm)
