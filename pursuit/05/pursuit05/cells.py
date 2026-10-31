"""Cells, the registry that builds and caches them, and the data split."""

from __future__ import annotations

from dataclasses import dataclass

from pursuit05 import screen

TRAIN_SEEDS = (1, 2, 3)
TEST_SEEDS = (4, 5)
HOLDOUT_N = 12


@dataclass(frozen=True)
class Cell:
    stage_idx: int
    n: int
    T: int
    rate_idx: int
    p: float
    seed: int

    @property
    def cell_id(self) -> str:
        return f"{self.n}/{self.p}/{self.seed}"

    @property
    def is_test(self) -> bool:
        return self.seed in TEST_SEEDS


def _full_checks(n: int) -> int:
    return n + (n // 4 + (1 if n % 4 else 0))


def parse_cell_id(cell_id: str) -> Cell:
    try:
        n_s, p_s, seed_s = cell_id.split("/")
        n, seed = int(n_s), int(seed_s)
        p = float(p_s)
        stage_idx = screen.SIZES.index(n)
        rate_idx = screen.P_ERRS.index(p)
        if seed not in screen.SEEDS:
            raise ValueError(seed)
    except (ValueError, AttributeError):
        raise ValueError(f"unknown cell {cell_id!r}") from None
    return Cell(stage_idx, n, screen.T_OF[n], rate_idx, p, seed)


class CellRegistry:
    def __init__(self) -> None:
        self._cells = tuple(
            Cell(si, n, screen.T_OF[n], pi, p, seed)
            for si, n in enumerate(screen.SIZES)
            for pi, p in enumerate(screen.P_ERRS)
            for seed in screen.SEEDS
        )
        self._pre: dict[Cell, dict] = {}

    def all_cells(self) -> list[Cell]:
        return list(self._cells)

    def train_cells(self) -> list[Cell]:
        return [c for c in self._cells if c.seed in TRAIN_SEEDS]

    def test_cells(self) -> list[Cell]:
        return [c for c in self._cells if c.seed in TEST_SEEDS]

    def holdout_cells(self) -> list[Cell]:
        return [c for c in self._cells if c.n == HOLDOUT_N]

    def select(
        self,
        seeds: tuple[int, ...] | None = None,
        stages: tuple[int, ...] | None = None,
    ) -> list[Cell]:
        return [
            c
            for c in self._cells
            if (seeds is None or c.seed in seeds) and (stages is None or c.n in stages)
        ]

    def find(self, cell_id: str) -> Cell:
        want = parse_cell_id(cell_id)
        for cell in self._cells:
            if cell == want:
                return cell
        raise ValueError(f"unknown cell {cell_id!r}")

    def pre(self, cell: Cell) -> dict:
        cached = self._pre.get(cell)
        if cached is None:
            built = screen.build_cell(
                cell.n,
                drop=screen.drop_one(cell.stage_idx, cell.seed, _full_checks(cell.n)),
            )
            cached = screen.precompute(built, list(range(built["C"])), cell.T)
            self._pre[cell] = cached
        return cached


def split_label(seeds: tuple[int, ...]) -> str:
    if set(seeds) == set(TRAIN_SEEDS):
        return "train"
    if set(seeds) == set(TEST_SEEDS):
        return "test"
    return "selected"
