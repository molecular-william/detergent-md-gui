#!/usr/bin/env python3
"""Create a hash-aware legacy inventory; deletion requires a reviewed report."""
import argparse
import json
from pathlib import Path

from dashboard.cli import migration


def main():
    parser=argparse.ArgumentParser(description='Inventory dashboard/reference artifacts without deleting them')
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    report=migration.inventory(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream: json.dump(report, stream, indent=2); stream.write('\n')
    print(f"Inventoried {len(report['entries'])} files; review classifications before deletion.")
if __name__ == '__main__': main()
