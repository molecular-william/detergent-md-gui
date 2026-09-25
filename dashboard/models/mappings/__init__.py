"""Public mapping API. Implementation lives in focused sub-modules.

Re-exports the schema and identity helpers (``schema``), graph validation
(``graph``), persistence and listing (``store``), format exports (``exports``),
reference lookup (``references``), suggestions (``suggestions``), the RDKit
depiction used by the mapping editor (``depiction``), and the packaged DDM
source graph (``packaged_ddm_source``) that historical callers use as their
default structure. The package boundary is the interface: callers that want a
single name import this package, and callers that need one concern import the
sub-module that owns it.
"""
from ..molecules.packaged import ROOT, SOURCE, bead_types, molecule
from ..sugars.validation import derive_representation, representation_modes, validate_representation
from .exports import export_files
from .graph import require_usable, ring_site_preview, validate
from .identity import candidate_identity, canonical_sha256, content_identity
from .schema import (
    LABELS,
    SIZES,
    automatic_candidate,
    check_schema,
    new_draft,
)
from .store import (
    candidate_paths,
    delete_draft,
    generate_variants,
    get,
    list_candidates,
    list_reviews,
    record_review,
    reviews_root,
    save_draft,
    storage_root,
)

__all__ = [
    'SIZES', 'LABELS',
    'candidate_identity', 'content_identity', 'canonical_sha256', 'check_schema', 'new_draft', 'automatic_candidate',
    'derive_representation', 'validate_representation', 'representation_modes',
    'validate', 'require_usable', 'ring_site_preview',
    'storage_root', 'reviews_root', 'candidate_paths', 'get', 'list_candidates',
    'save_draft', 'delete_draft', 'list_reviews', 'generate_variants', 'record_review',
    'export_files',
    'ROOT', 'SOURCE', 'molecule', 'bead_types',
]
