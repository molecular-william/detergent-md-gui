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
from .identity import canonical_sha256, candidate_identity, content_identity
from .schema import (
    SIZES, LABELS, check_schema, new_draft, automatic_candidate,
)
from ..sugars.validation import derive_representation, validate_representation, representation_modes
from .graph import validate, require_usable, ring_site_preview
from .store import (
    storage_root, reviews_root, candidate_paths, get, list_candidates,
    save_draft, delete_draft, list_reviews, generate_variants, record_review,
)
from .exports import export_files
from ..molecules.packaged import ROOT, SOURCE, molecule, bead_types

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
