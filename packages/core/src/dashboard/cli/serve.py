"""The console entry point: serve one loopback dashboard for the installed features.

`python -m dashboard` is the checkout's own form and keeps its fixed host/port. This is the installed form, where
the port and the workspace come from a launcher rather than a source constant: a second instance on one host needs
its own port, and `DASHBOARD_WORKSPACE` already selects its data root.
"""
from __future__ import annotations

import argparse
import os

from ..constants import HOST, PORT


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog='detergent-dashboard')
    parser.add_argument('--host', default=os.environ.get('DASHBOARD_HOST', HOST))
    parser.add_argument('--port', type=int, default=int(os.environ.get('DASHBOARD_PORT', PORT)))
    parser.add_argument('--features', default=os.environ.get('DASHBOARD_FEATURES', ''),
                        help='comma-separated feature names to load; default every installed feature')
    arguments = parser.parse_args(argv)
    # Before the app module is imported: it builds one application at import time.
    os.environ['DASHBOARD_FEATURES'] = arguments.features
    from ..app import create_app
    create_app().run(host=arguments.host, port=arguments.port, debug=False)


if __name__ == '__main__':
    main()
