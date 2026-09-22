# Chemically Informed Bonded-State Generation

## Problem

The automatic bonded-state generator currently reads only reference `[atoms]`
and `[bonds]` sections. It selects a bond signature by bead-type pair, derives
all angles from the current mapped geometry, and never generates dihedrals.
This discards bonded terms already present in the repository's Martini and
molecule-specific reference topologies. Bonded-function metadata is also
duplicated between Python and JavaScript and reports incorrect units for some
GROMACS functions.

## Goals

1. Present one authoritative function specification with accurate descriptions,
   parameter labels, and units for the bonded functions supported by the UI.
2. Index reference bonds, angles, and dihedrals without mutating reference
   files, while preserving the existing `index["bonds"]` compatibility shape.
3. Select reference terms using bead chemistry and mapped graph context, with
   deterministic consensus and traceable provenance.
4. Use geometry only for a conservative angle fallback; never invent generic
   dihedrals without a reference term.
5. Keep generation deterministic, local, validated, and separate from the
   explicit Fast Forward/AA trajectory-fitting workflow.

## Non-goals

- Replacing Fast Forward or adding trajectory fitting to automatic generation.
- Inferring bonded parameters from force-field rules that are absent from the
  repository references.
- Changing constraints, virtual sites, exclusions, or mapping persistence
  semantics.
- Adding a new external dependency.

## Design

### Shared bonded-function metadata

`dashboard.models.bonded` will define a structured specification for each
supported section/function. The existing `FUNCTION_PARAMETER_LABELS` and
`FUNCTIONS` views will be derived from it so validation, API records, and
frontend fallback metadata stay consistent. Each specification includes a
short description and the units for each parameter:

- bonds function 1: harmonic; length in nm and force in kJ mol⁻¹ nm⁻².
- angles function 1: harmonic; angle in degrees and force in kJ mol⁻¹ rad⁻².
- angles function 2: GROMOS-96 cosine; angle in degrees and force in kJ mol⁻¹.
- angles function 10: restricted bending; angle in degrees and force in
  kJ mol⁻¹.
- dihedrals function 1: proper periodic; phase in degrees, force in kJ mol⁻¹,
  and multiplicity.
- dihedrals function 2: improper harmonic; phase in degrees and force in
  kJ mol⁻¹ rad⁻².
- dihedrals function 9: proper periodic multi-term; phase in degrees, force in
  kJ mol⁻¹, and multiplicity.

The API's `function_options` will expose the description and parameter labels;
the JavaScript fallback will mirror the same values for offline or legacy
responses.

### Reference index

`reference_bond_index()` will become a version-2 reference-term index. It will
parse `[atoms]`, `[bonds]`, `[angles]`, and `[dihedrals]` rows, retaining
function numbers, numeric parameters, source paths, line numbers, SHA-256
hashes, source rank, and occurrence counts.

Keys are canonicalized as follows:

- bonds: unordered type pair (`A|B`).
- angles: type triplet with the two endpoint orders treated as equivalent
  (`A|B|C` equals `C|B|A`).
- dihedrals: the lexicographically smaller of the forward and reversed type
  quadruples.

The legacy `index["bonds"][pair]` list remains available. New `angles` and
`dihedrals` maps use the same ordered signature records. A source rank is
derived deterministically from the path: molecule-specific paths containing
the mapped molecule name rank ahead of detergent-specific paths, which rank
ahead of generic Martini references. Ties use occurrence count and stable path
and line ordering.

### Matching and generation

For each mapped physical bead edge, the generator uses the canonical bead-type
pair and selects the highest-ranked deterministic reference signature. For
each mapped graph angle, it first matches the endpoint/central bead-type
triplet, then falls back to geometry with function 1 and the existing fallback
force when no reference angle is available. For each mapped length-three graph
path, it adds a dihedral only when the canonical bead-type quadruple has a
reference match.

The matcher includes bead size and graph context in candidate scoring where the
reference provides enough information, while preserving type-based matching as
the compatibility baseline. Conflicting signatures at the same specificity
are resolved by deterministic weighted consensus; the selected term records
the competing signatures and an ambiguity diagnostic. No reference match is a
per-term fallback and is explicitly recorded as such.

Every generated term includes provenance containing the selected reference
records, fallback status, confidence, and ambiguity details when applicable.
The overall provenance records the algorithm name/version and reference index
hash. Existing topology validation, constraints, virtual sites, exclusions,
and immutable reference handling remain unchanged.

## Error handling and compatibility

Malformed or unsupported reference rows produce diagnostics and do not abort
index construction. Non-finite parameters are ignored with diagnostics.
Generated terms continue to pass the existing bonded-function validation.
Older callers that inspect the bond index or term fields continue to work;
new fields are additive.

## Testing

Add focused tests for corrected metadata, reference angle/dihedral parsing,
canonicalization, source ranking, deterministic conflict resolution, reference
generation, geometry fallback, dihedral suppression without references, and
per-term provenance. Run the existing bonded model, generator, API, and browser
tests after the focused suite.
