"""The prepare step's rules: PDB2PQR rebuilds the residues a deposited structure left incomplete, and protonates it.

The plan's step 1 (`docs/superpowers/plans/2026-10-12-pdc-new-run-panel.md`) and MemProtMD's own Energy Minimise
route, which is `PDB -> PDB2PQR -> minimisation`. What this module runs is the first half of that route, and the
half the coarse-grained path actually needs.

**Why it exists here rather than inside the placement.** A structure whose file is missing side-chain atoms has
coarse-grained beads with no position at all: Martini places a bead at the mean of the atoms it is built from, and
vermouth cannot place one built from atoms that are not there. Measured on 4iar (2026-10-14): 20 of its 928 beads
are `nan` -- the side-chain beads of 9 lysines, 6 arginines and one tryptophan -- and `pdc_placement` refuses the
whole build, because a belt placed against a protein no distance can be measured to is not a belt. The fix is the
missing atoms, not a placement that tolerates their absence.

**The rebuild is a tested implementation's, not one written here.** PDB2PQR's own forced-field templates rebuild
missing heavy atoms and add the hydrogens its protonation states need; measured on the same structure, it reported
312 missing atoms across 25 residues, built 104 heavy atoms to fill them, and logged two backbone gaps
(`ALA A 190 -> SER A 197`, `ILE A 339 -> TRP A 345`). Its `--pdb-output` is a PDB holding no charges or radii, which
is the artifact this step wants: the PQR's charges are meaningless to Martini and nothing here consumes them.

**The source's own statements travel with the prepared structure.** `pdb2pqr` writes no `REMARK` records -- measured
on 4iar, its `--pdb-output` held 0 of the source's 161 header lines -- and the membrane a belt is placed in is read
from the file martinize2 is handed (`micelle.frame`). So the source's non-coordinate records are carried over, the
same rule `pdc_import.filter_chains` keeps them by, and a stated bilayer survives the step instead of silently
becoming the sphere.

**What it deliberately does not do:** the energy minimisation the plan's step names. That route is atomistic
(`charmm36` + water + ions), where this pipeline is coarse-grained and has no atomistic force field to minimise in --
and the chain already carries a CG `Energy minimisation` leg in front of its assessment leg, which relaxes the built
system. So this step is the rebuild and the protonation, and the relaxation is the leg that exists.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

#: The tool, as declared and as it answers on the search path (`execution/tools.search_path` puts this workspace's
#: own virtualenv first, so a `pdb2pqr` installed for this application is the one that answers).
TOOL = 'pdb2pqr'
#: The force field the rebuild and the protonation come from. CHARMM because the atomistic half of this repository
#: is CHARMM36, so the topologies a deposited structure is completed against are the ones the rest of it uses --
#: and the choice matters here for the templates, not for the charges, which nothing coarse-grained consumes.
FORCE_FIELD = 'CHARMM'

#: What the stage and the preview both write, and both read back: the file martinize2 is handed.
PREPARED_NAME = 'protein_prepared.pdb'
#: The polymer the preparer is handed: the deposited file with its `HETATM` records dropped and the run's chain
#: selection applied (`pdc_import.filter_chains`), because a ligand or a crystallisation additive is not a residue
#: any force field can place, and martinize2 deletes the whole molecule for one it cannot.
INPUT_NAME = 'protein_input.pdb'
#: The tool's own second output. Kept because it is what the tool was asked for and what a reader may want to
#: compare against; nothing in this pipeline reads its charges or radii.
PQR_NAME = 'prepared.pqr'
#: The step's record: the command, the tool and its version, the atoms it built, and its wall time.
RECORD_NAME = 'prepare_protein.json'
#: The tool's own log, verbatim. Every number in the record comes from here rather than from a count of this
#: module's own making.
LOG_NAME = 'pdb2pqr.log'

#: `INFO:Added atom CE to residue LYS A 1085 at coordinates ...` -- one line per heavy atom the rebuild built.
_ADDED = re.compile(r'^INFO:Added atom (\S+) to residue (\S+) ?([A-Za-z0-9]?) ?(-?\d+) at coordinates', re.MULTILINE)
#: `WARNING:Missing atom CG in residue ARG A 76` -- the tool's own measure of what the input was missing, which is
#: the honest answer to "did this structure need the step at all".
_MISSING = re.compile(r'^WARNING:Missing atom (\S+) in residue (\S+) ?([A-Za-z0-9]?) ?(-?\d+)', re.MULTILINE)
#: `WARNING:Gap in backbone detected between ALA A 190 and SER A 197!` -- a chain break, which no rebuild can
#: fill: what it means for a run is that two residues that are not neighbours in space may look adjacent.
_GAP = re.compile(r'^WARNING:Gap in backbone detected between (\S+) ([A-Za-z0-9]?) ?(\d+) and (\S+) ([A-Za-z0-9]?) ?(\d+)',
                  re.MULTILINE)
_VERSION = re.compile(r'PDB2PQRS? v?([0-9][0-9.]*)')


class PreparationRefused(RuntimeError):
    """The step was asked for and could not run -- the tool is missing, or it exited non-zero.

    A refusal rather than a skip, and named as one: the run asked for this structure to be prepared, so a run that
    carried on without it would coarse-grain a structure the caller did not ask to coarse-grain.
    """


def resolve_tool(config=None):
    """The preparer, resolved where every other tool is, or `None` when it cannot be honoured.

    Through `execution/tools.py` rather than a `shutil.which` of this module's own, so the resolved path is the one
    the run records and a machine without the tool gets no substitute for it.
    """
    from .. import tools

    return tools.tool_path(TOOL, config)


def command(input_path, output_pdb, output_pqr, *, executable=TOOL) -> list[str]:
    """The command that rebuilds, protonates and writes a PDB the coarse-graining can read.

    `--keep-chain` because a deposited assembly's chains are how a subunit selection is spelled, and a tool that
    drops the column hands the build a file whose chains cannot be checked against the selection at all.
    `--pdb-output` because the PQR is for electrostatics and the next step wants coordinates.
    """
    return [str(executable), f'--ff={FORCE_FIELD}', '--keep-chain', '--pdb-output', str(output_pdb),
            str(input_path), str(output_pqr)]


#: The record types that are the structure, rather than a statement about it. Everything else a file carries --
#: its `REMARK`s above all, which is where an OPM structure states its membrane -- is carried over by
#: `carry_statements`.
COORDINATE_RECORDS = ('ATOM', 'HETATM', 'TER', 'END', 'MASTER', 'ANISOU', 'CONECT')


def statements(text) -> list[str]:
    """The lines of a structure that are not coordinates: what a prepared file has to be given back."""
    return [line for line in str(text).splitlines() if line[:6].strip().upper() not in COORDINATE_RECORDS]


def carry_statements(source_text, prepared_text) -> str:
    """A prepared structure with the source's own non-coordinate records in front of its coordinates.

    The tool's output is coordinates and nothing else, so the file martinize2 is handed would otherwise state no
    membrane and the belt would be placed as the sphere. Lines the prepared file already carries are not repeated,
    and the records are written in the order the source carried them.
    """
    body = str(prepared_text).splitlines()
    present = {line.rstrip() for line in body}
    head = [line for line in statements(source_text) if line.rstrip() not in present]
    return '\n'.join(head + body) + ('\n' if body or head else '')


def log_record(log_text) -> dict:
    """What the tool's own log says: the version, the atoms it built, and the gaps it could not fill.

    Every number a run records about this step is read here, from the lines the tool wrote, so a record cannot claim
    an atom that was never built or miss one that was.
    """
    added = _ADDED.findall(str(log_text))
    missing = _MISSING.findall(str(log_text))
    gaps = _GAP.findall(str(log_text))
    version = _VERSION.search(str(log_text))
    return {
        'tool_version': version.group(1) if version else None,
        'heavy_atoms_added': len(added),
        # By residue, in the order the tool reported them, because "which residue was incomplete" is the question a
        # reader has about a structure whose build refused.
        'residues_rebuilt': list(dict.fromkeys(f'{residue} {chain} {number}'.replace('  ', ' ')
                                              for _, residue, chain, number in added)),
        'missing_atoms_reported': len(missing),
        'missing_residues_reported': len(dict.fromkeys(f'{residue} {chain} {number}'.replace('  ', ' ')
                                                       for _, residue, chain, number in missing)),
        'gaps': [f'{first} {chain_a} {number_a} -> {second} {chain_b} {number_b}'
                 for first, chain_a, number_a, second, chain_b, number_b in gaps],
    }


def atom_count(text) -> int:
    """A structure's coordinate records, for the before-and-after the record states."""
    return sum(1 for line in str(text).splitlines() if line[:6].strip() in ('ATOM', 'HETATM'))


def version(executable):
    """The tool's own version string, read from the executable that was resolved rather than from this interpreter.

    A resolved path is verified before use and it is not this process: a different `pdb2pqr` on the path could be a
    different release with a different rebuild, so the version a run records is the one that ran.
    """
    try:
        result = subprocess.run([str(executable), '--version'], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION.search(f'{result.stdout}\n{result.stderr}')
    return match.group(1) if match else None


def prepare(source, directory, *, chains=None, executable=None, timeout=1800) -> dict:
    """Rebuild and protonate `source` into `directory`, and answer with the record or the reason.

    The answer is `{'ok': False, 'reason': ...}` for every way this can fail -- the tool is not resolvable, it exited
    non-zero, it wrote no structure, it took longer than `timeout` -- and the full record when it ran. A caller that
    asked for the step and got `ok: False` refuses; a caller that did not ask never gets here.

    `chains` is the run's own selection, applied by the same reader the build applies it with, so the preparer is
    handed the polymer the build would have coarse-grained and not the file's ligands with it.
    """
    from . import pdc_import

    # Absolute, and measured rather than defensive: PDB2PQR derives its own log file from the PQR path it is handed,
    # and a *relative* one makes it write the log at a path of its own construction -- measured: a relative
    # `--pdb-output .../prepared.pqr` had it look for
    # `<dir>/<dir>/prepared.log` and exit 1 before reading a single atom. The stage resolves its directory before it
    # gets here; this is the same rule for a caller that does not, so the preparer writes where it was asked to.
    source = Path(source).resolve()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        return {'ok': False, 'reason': f'the protein to prepare is not a file: {source}'}
    text = source.read_text(errors='replace')
    filtered = pdc_import.filter_chains(text, chains)
    input_path = directory / INPUT_NAME
    input_path.write_text(filtered)
    if not any(line[:6].strip() == 'ATOM' for line in filtered.splitlines()):
        return {'ok': False, 'reason': f'there is no protein to prepare: {source.name} holds no coordinate records',
                'skipped': True}

    resolved = str(executable or resolve_tool() or '')
    if not resolved:
        return {'ok': False, 'reason': f'{TOOL} is not resolvable on this machine, and it is the tool this step '
                                       f'rebuilds a structure\'s missing atoms and protonates it with'}
    prepared_path, pqr_path, log_path = directory / PREPARED_NAME, directory / PQR_NAME, directory / LOG_NAME
    argv = command(input_path, prepared_path, pqr_path, executable=resolved)
    started = time.perf_counter()
    try:
        with log_path.open('w') as handle:
            result = subprocess.run(argv, cwd=directory, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'reason': f'{TOOL} did not finish within {timeout} s', 'command': argv,
                'log': str(log_path), 'seconds': round(time.perf_counter() - started, 3)}
    except OSError as exc:
        return {'ok': False, 'reason': f'{TOOL} could not be run: {exc}', 'command': argv, 'seconds':
                round(time.perf_counter() - started, 3)}
    seconds = round(time.perf_counter() - started, 3)
    log_text = log_path.read_text(errors='replace')
    if result.returncode != 0 or not prepared_path.is_file():
        return {'ok': False, 'reason': f'{TOOL} exited {result.returncode} and wrote no {PREPARED_NAME}',
                'command': argv, 'log': str(log_path), 'log_tail': '\n'.join(log_text.splitlines()[-20:]),
                'seconds': seconds}

    carried = carry_statements(input_path.read_text(errors='replace'), prepared_path.read_text(errors='replace'))
    prepared_path.write_text(carried)
    before, after = atom_count(input_path.read_text(errors='replace')), atom_count(carried)
    record = log_record(log_text)
    added = after - before
    return {
        'ok': True, 'tool': TOOL, 'executable': resolved, 'force_field': FORCE_FIELD,
        'tool_version': record['tool_version'] or version(resolved), 'command': argv,
        'input': str(input_path), 'path': str(prepared_path), 'pqr': str(pqr_path), 'log': str(log_path),
        'seconds': seconds, 'atoms_before': before, 'atoms_after': after, 'atoms_added_total': added,
        # The hydrogen count is arithmetic on the tool's own two answers, and it is stated only when that arithmetic
        # holds: a tool that also dropped an atom would otherwise be recorded as having added one fewer hydrogen
        # than it did, and a record with a made-up number in it is worse than one with a `null`.
        'hydrogens_added': added - record['heavy_atoms_added'] if added >= record['heavy_atoms_added'] else None,
        'statements_carried': len(statements(input_path.read_text(errors='replace'))),
        **record,
    }
