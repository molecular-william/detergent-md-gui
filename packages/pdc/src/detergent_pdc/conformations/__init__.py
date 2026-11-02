"""Detergent conformations: a fixed-size library of whole molecules taken from micelle-only runs.

Every detergent used to be stamped from one template, so a micelle was one shape repeated. CHARMM-GUI draws each
detergent from a pool of configurations taken from micelle simulations, and this package is that pool: a canonical,
verifiable file of K whole molecules per detergent, selected to cover the shapes the sources visited, in each
molecule's own local frame (head at the origin, head-ward axis along +z).

The package is pure functions over files -- no stage, no route, no flag:

* `sources` validates the runs a library may be built from (completed, protein-free `pdc` runs whose detergent
  signature agrees) and resolves each one's production trajectory;
* `extract` reads one trajectory, makes each molecule whole and drops the ones a frame cannot support;
* `select` picks exactly K molecules by a deterministic stratified median split;
* `library` writes the canonical file, its sidecar digest and the store layout, and resolves a spec by building or by
  key.

`python -m detergent_pdc.conformations build|show` is the operator's way in. A run records the resolved key and
digest; see `docs/plans/2026-11-02-detergent-conformation-library.md`.
"""
from .extract import candidates, producer
from .library import (
                      DEFAULT_SIZE,
                      DESCRIPTORS,
                      FORMAT,
                      MAX_SIZE,
                      METHOD,
                      Conformations,
                      Library,
                      available,
                      build,
                      canonical_bytes,
                      key_for,
                      key_of_document,
                      load,
                      normalise_spec,
                      resolve,
                      store,
                      store_dir,
                      store_root,
                      verify,
)
from .select import stratified
from .sources import sources

__all__ = [
    'FORMAT', 'METHOD', 'DESCRIPTORS', 'DEFAULT_SIZE', 'MAX_SIZE',
    'Conformations', 'Library',
    'normalise_spec', 'sources', 'key_for', 'key_of_document', 'resolve', 'build', 'available', 'load', 'verify',
    'store', 'store_dir', 'store_root', 'canonical_bytes', 'candidates', 'producer', 'stratified',
]
