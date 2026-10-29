"""Compatibility entry point for archived analysis commands."""
import sys

from .worker import execute

if __name__ == "__main__":
    execute(sys.argv[1])
