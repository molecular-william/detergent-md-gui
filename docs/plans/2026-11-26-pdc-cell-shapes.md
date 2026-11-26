# PDC: offer the validation panel's unit cells

Status: built (2026-11-26, the user's request)

## The request

"Add different unit cells for PDC simulations." The user pointed at the **detergent-validation** New run panel:
offer **those** unit cells here too. In that panel the `Box shape` control offers, all sized by one minimum image
distance d:

| value | label |
|---|---|
| `cubic` | Cube · 1.000 d³ |
| `dodecahedron` | Rhombic dodecahedron (xy-square) · 0.707 d³ |
| `dodecahedron-hexagon` | Rhombic dodecahedron (xy-hexagon) · 0.707 d³ |
| `octahedron` | Truncated octahedron · 0.770 d³ |

The user's other two answers: **the box is automatic** when a shape is chosen (no manual angles), and the pressure
coupling is **left entirely alone** (the form's existing NPT coupling control is not touched; the shape does not
switch it).

## Decisions

- The current **rectangular** cell stays the default and unchanged; the four validation shapes are added. Existing
  runs, presets and clones without `box_shape` remain rectangular, byte for byte.
- Every offered shape has |a| = |b| = |c| = d. For a PDC build the rectangular rule still computes the required
  x/y/z, and the shape's **d = max(required x, y, z)**: the smallest single image distance that contains the
  rectangular requirement, which is the same conservative rule the validation panel's `check_fit` uses.
- A non-rectangular shape **ignores the Initial box x/y/z fields** (the form hides them); the box derives from the
  protein/belt and the Box margin, which still applies. Rectangular keeps the current fields and widening notes.
- The cell vectors are the exact ones GROMACS `editconf` produces (measured on the installed 2026.3 build):
  - cubic: a=(d,0,0), b=(0,d,0), c=(0,0,d).
  - dodecahedron (xy-square): a=(d,0,0), b=(0,d,0), c=(d/2,d/2,d/√2).
  - dodecahedron-hexagon: a=(d,0,0), b=(d/2,d√3/2,0), c=(d/2,d/(2√3),d√(2/3)).
  - octahedron (truncated): a=(d,0,0), b=(d/3,2√2d/3,0), c=(-d/3,√2d/3,d√(2/3)).
- The .gro box line carries the nine GROMACS values; Insane's adapter already passes three or nine through
  (`-box` and `-pbc keep`).
- The RDF/analysis cutoff keeps using `min(box_nm)/2`; for these shapes every vector has length d, so that is
  exactly d/2 and remains a correct bound.

## What changes

- `pdc_box`: `SHAPES`, `DEFAULT_SHAPE`, and `cell(shape, [x, y, z])` -> `{shape, vectors, lengths, minimum_image_nm}`.
  Rectangular is the diagonal cell.
- `pdc_build`: reads `box_shape`; computes the rectangular requirement as now, then the cell; centres on the cell
  centre `(a+b+c)/2`; writes the nine-value .gro; records `box_vectors_nm`, `box_minimum_image_nm`, `box_shape` (and
  `box_nm` stays the three vector lengths).
- `pdc_preview`: same box rule, basis vectors, a cell-aware molecule wrap and mark bounds check, and the preview
  cell drawn from the three vectors (the JS box drawing gains a vector path).
- The New run form/JS: a `Box shape` select in the box group (rectangular default + the four labels), hidden
  Initial x/y/z and Auto when a shape is chosen, the shape in the preview query/payload, and a cell line in the
  preview summary (`octahedron cell · d = 18.2 nm`).
- `pdc.py`: `DEFAULTS['box_shape']='rectangular'`, `CHOICE_SPECS['box_shape']`; the settings filter keeps it.
- Help text in `setting_help.py`.
- Admission (`feature._box_warnings`) ignores stated x/y/z when a shape is chosen (they are derived).

## Not in scope

- No pressure-coupling switch or warning (the user chose "leave it entirely alone").
- No user-entered triclinic angles/vectors.
- No change to the initial insertion box (it stays the rectangular insertion aid); the shape applies to the final
  simulation cell.

## Tests

- `pdc_box.cell`: every shape's vector lengths, volumes (1.000/0.707/0.707/0.770 d³), rectangular unchanged, unknown
  shape refused.
- Build: a shaped run writes a nine-value .gro box with the expected vectors and centres on the cell centre.
- Preview: basis carries the vectors/minimum image; the cell drawing uses them; the wrap keeps molecules whole and
  inside the shaped cell; the rectangular path unchanged (hash/pinned tests).
- Form: default rectangular, the four options, the shape in the preview query, x/y/z hidden for a shape.
- Admission: a shaped payload's ignored x/y/z does not widen or refuse.
- Existing pinned placement/box tests still pass (rectangular default).

## Built and measured

- `pdc_box.cell`: the four validation shapes' exact vectors (volumes 1.000/0.707/0.707/0.770 d³), rectangular
  unchanged, unknown/non-positive refused.
- The build: a shaped run writes the nine-value .gro box, centres on the cell centre, and reports `box_shape`,
  `box_vectors_nm` and `box_minimum_image_nm`; the rectangular path's pinned tests still pass.
- The preview: the same basis/vectors, fractional molecule wrap and mark bounds, and a parallelepiped drawn from the
  vectors.
- The form: default rectangular; the four labels; a shaped selection hides the three lengths and the Auto, shows the
  hint, and posts/queues `box_shape`; the route passes it and refuses an unknown shape with a 400.
- Checks: full fast 3,223 passed / 1 xfailed; full browser 431 passed; pdc fast 880 / 1 xfailed; ruff clean.
