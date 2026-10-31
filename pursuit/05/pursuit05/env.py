from __future__ import annotations

import numpy as np
import pufferlib
from gymnasium.spaces import Box, Discrete

OBS_SIZE = 7
_EMPTY_INFO: dict = {}


def draw_trajectories(pre: dict, p: float, n: int, rng) -> tuple:
    big_l = float(pre["L1"])
    p0 = (1.0 - p) ** big_l
    p1 = big_l * p * (1.0 - p) ** (big_l - 1.0) if pre["L1"] else 0.0
    p2 = (
        (big_l * (big_l - 1.0) / 2.0) * p**2 * (1.0 - p) ** (big_l - 2.0)
        if pre["L1"] >= 2
        else 0.0
    )
    tot = p0 + p1 + p2
    cumq = np.cumsum([p0 / tot, p1 / tot, p2 / tot])
    w = np.searchsorted(cumq, rng.random(n), side="right")
    rows = np.zeros(n, dtype=np.int64)
    m1 = w == 1
    m2 = w == 2
    if m1.any():
        rows[m1] = rng.integers(0, pre["L1"], size=int(m1.sum()))
    if m2.any():
        rows[m2] = rng.integers(0, len(pre["fw2"]), size=int(m2.sum()))
    return w, rows


def rollout_loaded(env, w_all, rows_all, act_fn) -> list:
    """Step explicit trajectories to completion.

    act_fn(obs, s, w, rows) returns one action per agent. Episodes
    drain fully per chunk, so no autoreset censoring skews the set.
    """
    w_all = np.asarray(w_all)
    rows_all = np.asarray(rows_all)
    n_ep = len(w_all)
    outs: list = [None] * n_ep
    nag = env.num_agents
    t = env.pre["T"]
    for lo in range(0, n_ep, nag):
        m = min(nag, n_ep - lo)
        w = np.zeros(nag, dtype=np.int64)
        rows = np.zeros(nag, dtype=np.int64)
        w[:m] = w_all[lo : lo + m]
        rows[:m] = rows_all[lo : lo + m]
        env.load_episodes(w, rows)
        ever = np.zeros(nag, dtype=bool)
        for s in range(t):
            _, _, term, _, infos = env.step(act_fn(env.observations, s, w, rows))
            first = term & ~ever
            for a in np.nonzero(first)[0].tolist():
                if a < m:
                    outs[lo + a] = (
                        infos[a]["spent"],
                        infos[a]["accepted"],
                        infos[a]["logical"],
                    )
            ever |= term
    assert all(o is not None for o in outs)
    return outs


class CultivationAbort(pufferlib.PufferEnv):
    """Abort-policy env: one episode is one trajectory draw."""

    def __init__(
        self,
        pre: dict,
        p: float,
        stage_id: int = 0,
        rate_id: int = 0,
        num_agents: int = 1,
        beta: float = 1.0,
        lam: float = 5000.0,
        buf=None,
        seed: int = 0,
    ) -> None:
        self.pre = pre
        self.p = p
        self.stage_id = stage_id
        self.rate_id = rate_id
        self.beta = beta
        self.lam = lam
        self.num_agents = num_agents
        self.single_observation_space = Box(
            low=0, high=50, shape=(OBS_SIZE,), dtype=np.float32
        )
        self.single_action_space = Discrete(2)
        super().__init__(buf)
        self._w = np.zeros(num_agents, dtype=np.int64)
        self._row = np.zeros(num_agents, dtype=np.int64)
        self._k = np.zeros(num_agents, dtype=np.int64)
        self._log = np.zeros(num_agents, dtype=bool)
        self._rng = np.random.default_rng(seed)
        self.reset()

    def _draw_into(self, idx: np.ndarray) -> None:
        n = len(idx)
        if not n:
            return
        w, row = draw_trajectories(self.pre, self.p, n, self._rng)
        self._w[idx] = w
        m1 = w == 1
        m2 = w == 2
        self._row[idx] = row
        log = np.zeros(n, dtype=bool)
        log[m1] = True
        if m2.any():
            log[m2] = self.pre["nt2"][row[m2]]
        self._log[idx] = log
        self._k[idx] = 0

    def _write_obs(self) -> None:
        t = self.pre["T"]
        n = self.num_agents
        cw = np.zeros((n, t - 1))
        m1 = self._w == 1
        m2 = self._w == 2
        if m1.any():
            cw[m1] = self.pre["cw1"][self._row[m1]]
        if m2.any():
            cw[m2] = self.pre["cw2"][self._row[m2]]
        upto = np.minimum(self._k + 1, t - 1)
        keep = np.arange(3)[None, :] < upto[:, None]
        pad = np.zeros((n, 3))
        pad[:, : t - 1] = cw
        obs = self.observations
        obs[:, 0] = self._k
        obs[:, 1:4] = np.where(keep, pad, 0.0)
        obs[:, 4] = self.stage_id
        obs[:, 5] = self.rate_id
        obs[:, 6] = t

    def load_episodes(self, w: np.ndarray, rows: np.ndarray) -> None:
        """Replace the current draw with explicit trajectories."""
        w = np.asarray(w, dtype=np.int64)
        rows = np.asarray(rows, dtype=np.int64)
        if w.shape != (self.num_agents,) or rows.shape != (self.num_agents,):
            raise ValueError("w and rows must match num_agents")
        if bool((w < 0).any() or (w > 2).any()):
            raise ValueError("w must be in {0, 1, 2}")
        if bool(((w == 1) & ((rows < 0) | (rows >= self.pre["L1"]))).any()):
            raise ValueError("w1 row out of range")
        if bool(
            ((w == 2) & ((rows < 0) | (rows >= len(self.pre["fw2"])))).any()
        ):
            raise ValueError("w2 row out of range")
        self._w[:] = w
        self._row[:] = rows
        self._log[:] = False
        self._log[w == 1] = True
        m2 = w == 2
        if m2.any():
            self._log[m2] = self.pre["nt2"][rows[m2]]
        self._k[:] = 0
        self._write_obs()

    def reset(self, seed=None):
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self._draw_into(np.arange(self.num_agents))
        self._write_obs()
        self.rewards[:] = 0.0
        self.terminals[:] = False
        self.truncations[:] = False
        return self.observations, []

    def step(self, actions):
        t = self.pre["T"]
        vf = self.pre["Vf"]
        spent = self.pre["spent"]
        act = np.asarray(actions, dtype=np.int64).reshape(self.num_agents)
        final = self._k == t - 1
        cap = np.where(final, vf, spent[np.minimum(self._k, t - 2)])
        prev = np.where(self._k > 0, spent[self._k - 1], 0.0)
        rew = -(cap - prev) / vf
        accept = (act == 1) & final
        rew[accept] += self.beta
        rew[accept & self._log] -= self.lam
        self.rewards[:] = rew.astype(np.float32)
        done = ((act == 1) & ~final) | final
        self.terminals[:] = done
        self.truncations[:] = False
        spent_out = np.where(final, vf, spent[np.minimum(self._k, t - 2)])
        infos = [
            (
                {
                    "spent": float(spent_out[a]),
                    "accepted": bool(accept[a]),
                    "logical": bool(accept[a] and self._log[a]),
                }
                if done[a]
                else _EMPTY_INFO
            )
            for a in range(self.num_agents)
        ]
        self._k[~done] += 1
        self._draw_into(np.nonzero(done)[0])
        self._write_obs()
        return self.observations, self.rewards, self.terminals, self.truncations, infos

    def close(self) -> None:
        """Release env resources; lets vector close terminate workers."""
