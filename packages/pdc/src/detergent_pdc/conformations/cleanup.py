"""Forgetting the stored libraries built from a mapping that is being deleted.

A library records the mapping candidate it was built from (`detergent.mapping_sha256`), which is the same byte digest
the mapping store reports, so deleting a mapping or its parameterization can find and remove the shapes made from it.
Nothing here rebuilds or rewrites: a library that is unreadable is left alone, because that is not proof it was this
mapping's, and an empty digest deletes nothing rather than everything.
"""
from __future__ import annotations

from . import library


def forget_mapping(workspace, mapping_sha256):
    """Delete every verified stored library built from this mapping digest and return their keys.

    `available` is the store's one reader of "verified": a directory whose document or sidecar cannot be checked is
    not in its list, so it is never a candidate here. The digest is normalised the way the store records it; an empty
    or missing one is answered with `[]` before the store is read, so a caller without a digest can never mean
    "every library".
    """
    digest = str(mapping_sha256 or '').strip().lower()
    if not digest:
        return []
    removed = []
    for entry in library.available(workspace):
        if entry['mapping_sha256'] != digest:
            continue
        try:
            library.delete(workspace, entry['key'])
        except (KeyError, OSError, ValueError):
            # The directory changed between listing and deletion, or the store now holds the key twice. Either way it
            # is not a library this call provably removed, so the report leaves it out instead of guessing.
            continue
        removed.append(entry['key'])
    return removed
