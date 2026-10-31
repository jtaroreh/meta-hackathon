import math

import pytest

from pursuit05 import table


def _pool(mean, se, n=6):
    return {"n": n, "mean": mean, "std": se * math.sqrt(n), "se": se}


def test_pooled_matches_screen_semantics():
    assert table.pooled([]) == {"n": 0, "mean": None, "std": None, "se": None}
    assert table.pooled([4.0]) == {"n": 1, "mean": 4.0, "std": 0.0, "se": None}
    got = table.pooled([1.0, 2.0, 3.0])
    assert got["n"] == 3
    assert got["mean"] == pytest.approx(2.0)
    assert got["std"] == pytest.approx(1.0)
    assert got["se"] == pytest.approx(1.0 / math.sqrt(3))


def test_joint_win_matches_screen_rule():
    pools_w = {
        "F": _pool(100.0, 1.0),
        "G": _pool(80.0, 1.0),
        "A": _pool(95.0, 1.0),
        "S": _pool(80.0, 1.0),
    }
    pools_i = {a: _pool(0.01, 0.001) for a in ("F", "G", "A", "S")}
    assert table.joint_win(pools_w, pools_i, "G") is True
    assert table.joint_win(pools_w, pools_i, "A") is False


def test_joint_win_sse_ignores_arms_outside_trio():
    pools_w = {
        "F": _pool(100.0, 1.0),
        "G": _pool(80.0, 1.0),
        "A": _pool(95.0, 1.0),
        "S": _pool(80.0, 1.0),
    }
    pools_i = {
        "F": _pool(0.01, 0.001),
        "G": _pool(0.0121, 0.001),
        "A": _pool(0.01, 0.001),
        "S": _pool(0.5, 10.0),
    }
    assert table.joint_win(pools_w, pools_i, "G") is False
    assert table.joint_win(pools_w, pools_i, "S") is False
    assert table.joint_win(pools_w, pools_i, "S", sse_arms=("F", "S")) is True


def test_joint_win_rejects_unknown_arms():
    pools_w = {"F": _pool(100.0, 1.0), "G": _pool(80.0, 1.0)}
    pools_i = {"F": _pool(0.01, 0.001), "G": _pool(0.01, 0.001)}
    with pytest.raises(KeyError):
        table.joint_win(pools_w, pools_i, "Z")


def test_render_arm_table_empty_rows_prints_header_only():
    out = table.render_arm_table([], ("F", "G"))
    assert out.strip().split() == ["cell", "F_W", "F_inf", "G_W", "G_inf"]
