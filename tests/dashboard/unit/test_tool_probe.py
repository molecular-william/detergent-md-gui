"""A readiness probe measures the tool, not the ambient environment it was started from.

The probe is the only thing standing between a run type and a broken run: `cg.py` reports what
`probe_tool` answers as the readiness line for `ff_inter` and `ff_assess`, and a stage then calls the
same tool with the same environment. It has to run the tool the way the tool's own install expects.

Measured, 2026-10-16, dashboard started from a wrapper whose environment carries the wrapper's own
`PYTHONPATH` (the agent runtime's `python3.14` site-packages):

    PYTHONPATH=/home/wee/.hermes/installs/.../venv/lib/python3.14/site-packages \\
        dashboard/.venv/bin/python -c "...probe_tool(tools.tool_path('ff_inter'))"
    -> ready=False, ImportError: cannot import name '_imaging' from 'PIL'
       (/home/wee/.hermes/installs/.../python3.14/site-packages/PIL/__init__.py)

with `ff_inter` and `fast_forward` themselves imported from the project's own python3.12 site-packages:
the interpreter was right, the injected search path was not. The probe was measuring the wrapper.

These tests use no real toolchain: a console script is two lines of python, so each case below is a
statement about the probe rather than about this machine's PATH or its installed tools.
"""
import os
import stat
import sys

import pytest

from dashboard.execution import environment as environment_module


@pytest.fixture(autouse=True)
def fresh_probe_answers():
    """`probe_tool` is memoised for the process; each case here builds a new executable."""
    environment_module.probe_tool.cache_clear()
    yield
    environment_module.probe_tool.cache_clear()


def executable_file(directory, name, text):
    """A file that can be exec'd, whatever its shebang names."""
    path = directory / name
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def python_console_script(directory, name='ff_inter', shebang='#!/nonexistent/interpreter/python',
                          stderr='', exit_code=0, final_line=''):
    """A python entry point whose shebang names an interpreter that does not exist here.

    That is the shape a venv's console script has once the venv moves: pip writes an absolute
    interpreter path into the first line, and nothing on the machine re-writes it. It is also the
    shape that makes the difference between `[executable]` and `[sys.executable, executable]`
    measurable without a real tool: only the second one can run this file.
    """
    body = ['import sys']
    if stderr:
        body.append(f'sys.stderr.write({stderr!r})')
    if final_line:
        body.append(f'print({final_line!r})')
    body.append(f'sys.exit({exit_code})')
    return executable_file(directory, name, shebang + '\n' + '\n'.join(body) + '\n')


def test_a_console_script_is_probed_under_the_interpreter_that_owns_it(tmp_path):
    """The shebang of a moved venv's console script can name an interpreter nobody has.

    The dashboard knows which interpreter it is running under and that is the one whose install the
    tool belongs to, so the probe runs the script with it rather than letting exec() fail on line 1.
    """
    script = python_console_script(tmp_path)
    ready, detail = environment_module.probe_tool(str(script))
    assert ready is True, detail
    assert detail == 'Executable and imports checked'


def test_a_console_script_is_probed_whatever_the_ambient_path_says(tmp_path, monkeypatch):
    """Readiness may not depend on the PATH the dashboard inherited.

    A tool that is resolved to an absolute path does not need a search path at all; a probe whose
    answer moves with the caller's PATH is measuring the caller.
    """
    script = python_console_script(tmp_path)
    monkeypatch.setenv('PATH', '/nonexistent-search-path')
    ready, detail = environment_module.probe_tool(str(script))
    assert ready is True, detail


def test_a_console_script_is_probed_whatever_its_caller_injected_into_the_search_path(tmp_path, monkeypatch):
    """A wrapper's PYTHONPATH must not follow the tool into a fresh interpreter.

    This is the measured failure above, in the small: the entry point reports the interpreter
    environment it got, and it must not see the caller's injection.
    """
    script = executable_file(tmp_path, 'ff_assess',
                             '#!/nonexistent/interpreter/python\n'
                             'import os, sys\n'
                             "injected = [k for k in ('PYTHONPATH', 'PYTHONHOME') if os.environ.get(k)]\n"
                             "sys.exit(1 if injected else 0)\n")
    monkeypatch.setenv('PYTHONPATH', str(tmp_path / 'elsewhere'))
    ready, detail = environment_module.probe_tool(str(script))
    assert ready is True, detail


def test_the_stage_environment_does_not_carry_the_callers_interpreter_injection(monkeypatch):
    """One environment for the probe and the stage, and neither inherits the caller's python path."""
    monkeypatch.setenv('PYTHONPATH', '/somewhere/else')
    monkeypatch.setenv('PYTHONHOME', '/somewhere/else')
    stage = environment_module.stage_environment()
    assert 'PYTHONPATH' not in stage and 'PYTHONHOME' not in stage


def test_a_compiled_binary_is_run_as_itself(tmp_path):
    """A non-python executable has no interpreter to substitute, so it is run directly.

    If the probe handed this file to python it would fail to parse it, so a `ready` answer here is
    the evidence that the python route is chosen from the file's own first line rather than by name.
    """
    binary = executable_file(tmp_path, 'gmx-not-python', '#!/bin/sh\nexit 0\n')
    ready, detail = environment_module.probe_tool(str(binary))
    assert ready is True, detail


def test_a_failing_probe_names_the_exit_status_and_the_first_error_line(tmp_path):
    """The reader of a readiness line gets the cause, not the last line the tool happened to emit."""
    script = python_console_script(
        tmp_path, stderr='warning: nothing to do with this\n'
                         'ImportError: cannot import name \'_imaging\' from \'PIL\'\n'
                         'the last line of the traceback, addressed to no one\n',
        exit_code=1)
    ready, detail = environment_module.probe_tool(str(script))
    assert ready is False
    assert detail.startswith('exited 1:'), detail
    assert "ImportError: cannot import name '_imaging' from 'PIL'" in detail
    assert 'the last line of the traceback' not in detail


def test_a_failing_probe_without_an_error_line_still_reports_what_it_said(tmp_path):
    script = python_console_script(tmp_path, name='ff_map', stderr='no parameters given\n',
                                   exit_code=3)
    ready, detail = environment_module.probe_tool(str(script))
    assert ready is False
    assert detail.startswith('exited 3:'), detail
    assert 'no parameters given' in detail


def test_the_probe_still_asks_gmx_for_its_own_help_flag(tmp_path):
    """`gmx -h` is the documented help form for GROMACS; every other tool takes `--help`."""
    argument_file = tmp_path / 'argument'
    for name, expected in (('gmx', '-h'), ('ff_inter', '--help')):
        tool = executable_file(tmp_path, name,
                               f'#!/bin/sh\necho "$1" > {argument_file}\nexit 0\n')
        assert environment_module.probe_tool(str(tool))[0] is True
        assert argument_file.read_text().strip() == expected, name


def test_an_executable_that_cannot_be_started_is_reported_not_raised(tmp_path):
    missing = tmp_path / 'not-here'
    ready, detail = environment_module.probe_tool(str(missing))
    assert ready is False
    assert str(missing) in detail


def test_the_probe_runs_the_script_it_was_given(tmp_path):
    """The script's own stdout is the tool's, and the interpreter is this process's."""
    script = python_console_script(tmp_path, name='ff_inter_probe_identity')
    assert os.access(script, os.X_OK)
    ready, _ = environment_module.probe_tool(str(script))
    assert ready is True
    assert environment_module.probe_tool(str(script))[0] is True  # memoised, same answer
    assert sys.executable  # the interpreter the probe substitutes is a real path
