import argparse
from pathlib import Path

from pursuit05 import screen
from pursuit05.cli import cmd_reproduce


def test_all_cells_match_screen_record(capsys):
    rc = cmd_reproduce(argparse.Namespace(cell=None))
    out = capsys.readouterr().out
    assert rc == 0
    last = out.strip().splitlines()[-1]
    assert last.startswith("reproduced 45/45 cells")
    dw = float(last.split("max |dW| = ")[1].split(",")[0])
    dinf = float(last.split("max |dinf| = ")[1])
    assert dw < 1e-9
    assert dinf < 1e-9


def test_only_screen_imports_run05():
    root = Path(__file__).resolve().parents[1] / "pursuit05"
    offenders = sorted(
        p.name
        for p in root.glob("*.py")
        if p.name != "screen.py" and "import run05" in p.read_text()
    )
    assert offenders == []


def test_tiny_cell_hand_bound():
    tiny = screen.build_cell(6, tiny=True, drop=())
    pre = screen.precompute(tiny, list(range(tiny["C"])), 3)
    assert pre["L1"] == 72
    assert int((pre["fw1"] <= 0).sum()) == 0
