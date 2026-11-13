"""Read-only Martini fragment reference index for mapping suggestions."""
from __future__ import annotations

import re
from pathlib import Path

from ... import files
from .identity import canonical_sha256

TYPE_RE = re.compile(r"(?<![A-Za-z0-9])([STR]?[PQNCX][1-6][a-z]?)(?![A-Za-z0-9])")

#: One-entry memo for load_index, keyed on the source stamp. See files.memo.
_INDEX_CACHE = {}


def _size(bead_type: str) -> str:
    return bead_type[0] if bead_type[:1] in {"S", "T"} else "R"


def _record(fragment_id, bead_type, rank, path, locator, *, name=None, notes=None):
    return {
        "fragment_id": str(fragment_id), "type": bead_type, "size": _size(bead_type),
        "source_rank": rank, "name": name or str(fragment_id),
        "notes": notes or "", "references": [{"path": str(path), "sha256": files.sha256(path), "locator": locator}],
    }


def _parse_itp(path: Path, rank: int, source_name: str):
    records = []
    section = ""; molecule = None; seen = set()
    for line_number, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if line.startswith("["):
            section = line.strip("[] ").lower(); continue
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if section == "moleculetype":
            molecule = fields[0]
        elif section == "atoms" and len(fields) >= 2:
            bead_type = fields[1]
            if not TYPE_RE.fullmatch(bead_type) or (molecule, bead_type) in seen:
                continue
            seen.add((molecule, bead_type))
            records.append(_record(f"{source_name}:{molecule}:{bead_type}", bead_type, rank, path,
                                   f"line:{line_number}", name=molecule,
                                   notes="Martini topology bead type; atom attachment requires a verified AA mapping."))
    return records


def _parse_bible(path: Path):
    records = []
    try:
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True)
    except (ImportError, OSError, ValueError) as exc:
        return records, [f"Bible workbook unavailable: {exc}"]
    try:
        sheet = book["All"]
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
            name, tag, smiles, cgsmiles = row[:4]
            if not tag or not cgsmiles:
                continue
            for bead_type in sorted(set(TYPE_RE.findall(str(cgsmiles)))):
                records.append(_record(f"bible:{tag}:{bead_type}", bead_type, 3, path,
                                       f"All!row:{row_number}", name=str(name or tag),
                                       notes=f"M3-Bible CGSmiles fragment; SMILES={smiles or 'unrecorded'}"))
    finally:
        book.close()
    return records, []


def _source_specs(root):
    """The reference files the index reads, in rank order: (paths, parser returning (records, diagnostics))."""
    return (
        (sorted(path for path in (root / 'references').glob('martini_*_sugars_*.itp')
                if path.is_file() and not path.is_symlink()),
         lambda path: (_parse_itp(path, 1, 'sugars'), [])),
        ([root / 'references' / 'M3-Small-Molecules' / 'models' / 'martini_v3.0.0_small_molecules_v1.itp'],
         lambda path: (_parse_itp(path, 2, 'small-molecules'), [])),
        ([root / 'references' / 'M3-Bible' / 'src' / 'MartiniCGSmilesDB_v6.xlsx'], _parse_bible),
    )


def _source_paths(root):
    """The reference files the index reads, in the rank order it reads them."""
    return [path for paths, _parse in _source_specs(root) for path in paths]


def load_index(project_root: Path) -> dict:
    """Index known reference files without copying or mutating them.

    Cached on the source stamp -- every source path with its mtime and size -- so a repeat
    request does not re-hash and re-parse the corpus, and a changed source cannot be
    answered from an older index. Treat the returned index as read-only: it is shared.
    """
    root = Path(project_root)
    return files.memo(_INDEX_CACHE, files.stamp(_source_paths(root)), lambda: _build_index(root))


def _build_index(root: Path) -> dict:
    """Hash and parse every reference source. Called through load_index's memo."""
    root = Path(root); records = []; sources = []; diagnostics = []
    for rank, (paths, parse) in enumerate(_source_specs(root), 1):
        for path in paths:
            if path.is_symlink() or not path.is_file():
                continue
            sources.append({"path": str(path.relative_to(root)), "sha256": files.sha256(path), "rank": rank})
            parsed, notes = parse(path)
            records.extend(parsed); diagnostics.extend(notes)
    records.sort(key=lambda item: (item["source_rank"], item["fragment_id"]))
    index_payload = {"sources": sources, "records": records, "diagnostics": diagnostics}
    return index_payload | {"index_sha256": canonical_sha256(index_payload)}
