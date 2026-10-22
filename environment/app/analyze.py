#!/usr/bin/env python3
"""Station entry point: analyse one measured run directory."""

import json
import sys

from thermalkit.io import read_run
from thermalkit.quick import estimate


def main(argv):
    if len(argv) != 2:
        print("usage: python3 analyze.py <run_dir>", file=sys.stderr)
        return 2
    run = read_run(argv[1])
    result = estimate(run)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
