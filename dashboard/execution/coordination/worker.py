"""Owned, cancellable subprocess groups and runtime resource monitoring."""
import os
import signal
import subprocess
import threading
import time
from . import resources
from .. import workflow

class Worker:
    """Signals only subprocess groups created by this worker, never stored PIDs."""
    def __init__(self, coordinator, run_dir=None):
        self.coordinator = coordinator
        self.cancel = threading.Event()
        self.run_dir = run_dir
        self.lease_file = None
        self.limit_error = None

    def execute(self, command, **kwargs):
        if self.cancel.is_set():
            raise workflow.Cancelled('Cancelled by user')
        kwargs.pop('check', None)
        if self.lease_file: kwargs['pass_fds'] = (self.lease_file.fileno(),)
        with subprocess.Popen(command, start_new_session=True, **kwargs) as process:
            last_check = time.monotonic()
            termination_time = None
            while process.poll() is None:
                if self.run_dir and time.monotonic()-last_check > 5:
                    try: resources.check_worker(self.run_dir, self.coordinator.RUNS, self.coordinator.limits())
                    except (OSError, ValueError) as exc:
                        self.limit_error = str(exc); self.cancel.set()
                    last_check = time.monotonic()
                if self.cancel.is_set():
                    if termination_time is None or time.monotonic() - termination_time > 3:
                        try:
                            os.killpg(process.pid, signal.SIGTERM if termination_time is None else signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        if termination_time is None:
                            termination_time = time.monotonic()
                time.sleep(0.05)
            if self.cancel.is_set():
                # A shell may exit on TERM before its children. Reap its group too.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if self.limit_error: raise RuntimeError(self.limit_error)
                raise workflow.Cancelled('Cancelled by user')
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
            return subprocess.CompletedProcess(command, process.returncode)

