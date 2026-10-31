from __future__ import annotations

from typing import Protocol

import numpy as np
import pufferlib
from gymnasium.spaces import Box, Discrete

OBS_SIZE = 7
CW_COLS = 3


def binomial_masses(l1: int, p: float) -> tuple:
    big_l = float(l1)
    p0 = (1.0 - p) ** big_l
    p1 = big_l * p * (1.0 - p) ** (big_l - 1.0) if l1 else 0.0
    p2 = (
        (big_l * (big_l - 1.0) / 2.0) * p**2 * (1.0 - p) ** (big_l - 2.0)
        if l1 >= 2
        else 0.0
    )
    return p0, p1, p2, max(0.0, 1.0 - p0 - p1 - p2)


class ActFn(Protocol):
    def __call__(
        self, obs: np.ndarray, s: int, w: np.ndarray, rows: np.ndarray
    ) -> np.ndarray: ...


def draw_trajectories(pre: dict, p: float, n: int, rng) -> tuple:
    p0, p1, p2, _ = binomial_masses(pre["L1"], p)
    tot = p0 + p1 + p2
    cumq = np.cumsum([p0 / tot, p1 / tot, p2 / tot])
    cumq[-1] = 1.0
    w = np.searchsorted(cumq, rng.random(n), side="right")
    rows = np.zeros(n, dtype=np.int64)
    m1 = w == 1
    m2 = w == 2
    if m1.any():
        rows[m1] = rng.integers(0, pre["L1"], size=int(m1.sum()))
    if m2.any():
        rows[m2] = rng.integers(0, len(pre["fw2"]), size=int(m2.sum()))
    return w, rows


def rollout_loaded(env, w_all, rows_all, act_fn: ActFn) -> list:
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
        ret = np.zeros(nag)
        for s in range(t):
            _, rew, term, _, infos = env.step(
                act_fn(env.observations, s, w, rows)
            )
            ret += rew
            first = term & ~ever
            for a in np.nonzero(first)[0].tolist():
                if a < m:
                    outs[lo + a] = (
                        infos[a]["spent"],
                        infos[a]["accepted"],
                        infos[a]["logical"],
                        float(ret[a]),
                    )
            ever |= term
    missing = [i for i, o in enumerate(outs) if o is None]
    if missing:
        raise ValueError(f"episodes never finished: {missing[:8]}")
    return outs


def scripted_actions(obs: np.ndarray, ath, fth: int, t: int) -> np.ndarray:
    n = obs.shape[0]
    k = obs[:, 0].astype(np.int64)
    act = np.zeros(n, dtype=np.int64)
    mid = np.nonzero(k < t - 1)[0]
    if len(mid):
        act[mid] = (
            obs[mid][:, 1 : 1 + CW_COLS][np.arange(len(mid)), k[mid]]
            > np.asarray(ath)[k[mid]]
        ).astype(np.int64)
    fin = np.nonzero(k == t - 1)[0]
    if len(fin):
        act[fin] = (obs[fin][:, t - 1] <= fth).astype(np.int64)
    return act


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
        if pre["T"] - 1 > CW_COLS:
            raise ValueError(f"T={pre['T']} exceeds {CW_COLS} cw columns")
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
        keep = np.arange(CW_COLS)[None, :] < upto[:, None]
        pad = np.zeros((n, CW_COLS))
        pad[:, : t - 1] = cw
        obs = self.observations
        obs[:, 0] = self._k
        obs[:, 1 : 1 + CW_COLS] = np.where(keep, pad, 0.0)
        obs[:, 4] = self.stage_id
        obs[:, 5] = self.rate_id
        obs[:, 6] = t

    def load_episodes(self, w: np.ndarray, rows: np.ndarray) -> None:
        w = np.asarray(w)
        rows = np.asarray(rows)
        if not np.issubdtype(w.dtype, np.integer) or not np.issubdtype(
            rows.dtype, np.integer
        ):
            raise ValueError("w and rows must be integer arrays")
        w = w.astype(np.int64)
        rows = rows.astype(np.int64)
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
        self.rewards[:] = 0.0
        self.terminals[:] = False
        self.truncations[:] = False

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
        raw = np.asarray(actions)
        if raw.dtype.kind == "f" and bool((raw != raw.astype(np.int64)).any()):
            raise ValueError("actions must be integral")
        act = raw.astype(np.int64).reshape(-1)
        if act.shape != (self.num_agents,):
            raise ValueError(
                f"{act.shape[0]} actions for {self.num_agents} agents"
            )
        if bool(((act != 0) & (act != 1)).any()):
            raise ValueError("actions must be in {0, 1}")
        final = self._k == t - 1
        ck = np.zeros(self.num_agents, dtype=np.int64)
        m1 = self._w == 1
        m2 = self._w == 2
        mid = ~final
        if bool((m1 & mid).any()):
            ck[m1 & mid] = self.pre["cw1"][self._row[m1 & mid], self._k[m1 & mid]]
        if bool((m2 & mid).any()):
            ck[m2 & mid] = self.pre["cw2"][self._row[m2 & mid], self._k[m2 & mid]]
        act[mid & (ck == 0)] = 0
        fw = np.zeros(self.num_agents, dtype=np.int64)
        if bool(m1.any()):
            fw[m1] = self.pre["fw1"][self._row[m1]]
        if bool(m2.any()):
            fw[m2] = self.pre["fw2"][self._row[m2]]
        act[final & (fw == 0)] = 1
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
                else {}
            )
            for a in range(self.num_agents)
        ]
        self._k[~done] += 1
        self._draw_into(np.nonzero(done)[0])
        self._write_obs()
        return self.observations, self.rewards, self.terminals, self.truncations, infos

    def close(self) -> None:
        """Release env resources; lets vector close terminate workers."""
