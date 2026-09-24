# Dashboard development

Start at the repository root:

```bash
dashboard/.venv/bin/python -m dashboard
```

The dashboard binds to http://127.0.0.1:5000. Run one coordinator per workspace.
`python dashboard/app.py` remains a supported compatibility entry point.

Application source is grouped by responsibility:

- `app.py`, `paths.py`: application construction and path configuration.
- `execution/`: job coordination, stage execution, AA/CG preparation, tools and limits.
- `models/`: molecule inputs, mappings, bonded states, fragments and evidence gates.
- `models/composition_topology.py` and `models/compositions.py`: reference-backed
  sugar/tail assembly and immutable Molecule Combination snapshots.
- `analysis/`: isolated derived analyses and AA reference publication/verification.
- `web/`: HTTP routes, templates, native JavaScript modules and CSS.
- `cli/`: screening and bounded fresh-workspace reset.
- `store.py`, `files.py`: transactional persistence and safe filesystem operations.

Tests live in `tests/dashboard/`; shared fixtures isolate all writable stores.
For a fast edit loop, omit rendered-browser and subprocess/GROMACS checks. Run
the full suite or a focused group when the change crosses those boundaries:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -q
dashboard/.venv/bin/python -m pytest -q
dashboard/.venv/bin/python -m pytest tests/dashboard/unit -q
dashboard/.venv/bin/python -m pytest tests/dashboard/integration -q
dashboard/.venv/bin/python -m pytest -m browser -q
```

Browser tests require the installed Python Playwright package and Google Chrome.
The environment under `.venv/` includes the locally installed scientific tools;
do not relocate an existing virtual environment because launchers contain paths.

Process parallelism is optional. Install the test dependencies once:

```bash
dashboard/.venv/bin/python -m pip install -r requirements-dashboard-tests.txt
```

That file carries `pytest-xdist` (four workers for the fast suite, two for
browser tests, one for resource-heavy checks) plus `playwright` and `vermouth`,
which the browser and sugar-topology tests import directly.

Then use four workers for the fast suite, two for browser tests, and one for
resource-heavy checks:

```bash
dashboard/.venv/bin/python -m pytest -m 'not browser and not slow' -n 4 -q
dashboard/.venv/bin/python -m pytest -m browser -n 2 -q
dashboard/.venv/bin/python -m pytest -m slow -n 1 -q
```

The default serial commands above remain supported. Tests use process workers;
threaded test execution would race the module-level dashboard patches and worker
registries. Keep GROMACS and long-lived worker tests at one process unless the
machine has sufficient CPU, memory, and simulation-tool capacity.

See [the project guide](../docs/PROJECT_GUIDE.md) for operation, data locations,
backup, reset, and recovery. See [DDM calibration](../docs/DDM_CALIBRATION.md)
for scientific status and limits. Historical reports live under `reports/`, and
UI prototypes under `docs/design/prototypes/`.

Carbohydrate validation is launched from CG Bead Assignment for a completed
source run. The server derives either the TC4 mapping or the physical-only
ring-constrained mapping, then publishes an immutable analysis attempt. Geometry,
water-to-octanol transfer free energy, and concentration-dependent osmotic
pressure are reported independently. A setup check is diagnostic-only; an
evidence-complete report requires cited targets and the sampling minimums in the
carbohydrate validation design.
