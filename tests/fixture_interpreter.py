"""Test interpreter wrapper for the unmodified production run.sh."""
import sys

from tests.fixture_cli import main

if sys.argv[1:4] != ["-B", "-m", "tools.overnight.run_one"]:
    raise RuntimeError("unexpected test interpreter command")
sys.argv = [sys.argv[0], *sys.argv[4:]]
raise SystemExit(main())
