"""Screen 04 payload: erasure + biased-noise hybrid decoding (stim + stdlib + numpy/scipy + pulp).

Screen-authored rotated-surface-code X-memory simulation with explicit
heralded erasure flags plus residual biased Pauli noise. Base syndromes
are sampled from a screen-built stim circuit (biased PAULI_CHANNEL_1 at
1q locations, independent biased 1q channels on both qubits after each
CNOT, flip-parametrised measurements); a classical per-shot overlay adds
heralded erasures (erasure rate == physical rate p, i.e. 95% conversion
of a p/0.95 leakage process, residue folded into the Pauli budget) with
uniform random Paulis propagated through the stabilizer adjacency, plus
matching observable flips. Arms: HYB (sequential flagged-hyperedge
peel + Union-Find cluster growth on the remainder, same routine as
the UF arm) vs MWPM-static (pulp MILP exact perfect matching on
static graph distances, X/Z subgraphs decoded separately, small subset
only, own per-solve time cap, timeouts recorded as skips) vs UF-static
(textbook Union-Find, X/Z decoded separately, erasure-unaware).
Bounded-exact pairing enumeration validates matching on a tiny syndrome
and must cap-hit on a d=9 target syndrome (limit-expiry). Detector
sampling uses compile_sampler + compile_m2d_converter with
separate_observables (compile_sampler returns measurements, NOT
detectors). Verdict is always unresolved-with-reason; classification is
coordinator-side.
"""

import argparse
import json
import math
import os
import time

SEEDS = (1, 2, 3, 4, 5)
DISTANCES = (5, 7, 9)
P_GRID = (0.002, 0.005, 0.010)
ETA = 10.0
N_SHOTS = 800
MWPM_SEEDS = (1,)
N_MWPM = 20
MWPM_TIMELIMIT_S = 2.0
ENUM_CAP = 20000
TINY_DEFECTS = 6
TARGET_MIN_DEFECTS = 14
TARGET_SCAN_SHOTS = 2000
CYCLE_BUDGET_MS = 50.0
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0


def transcribe_layers(d):
    import stim
    gen = stim.Circuit.generated("surface_code:rotated_memory_x",
                                 distance=d, rounds=1,
                                 after_clifford_depolarization=0.0)
    lines = str(gen).splitlines()
    data = []
    for l in lines:
        parts = l.split()
        if parts[0] == "RX" and len(parts) > 2:
            data = [int(x) for x in parts[1:]]
            break
    layers = []
    cur = []
    in_cnot = False
    for l in lines:
        parts = l.split()
        op = parts[0]
        if op in ("CNOT", "CX"):
            qs = [int(x) for x in parts[1:]]
            for k in range(0, len(qs) - 1, 2):
                cur.append((qs[k], qs[k + 1]))
            in_cnot = True
        elif op == "TICK":
            if in_cnot and cur:
                layers.append(cur)
                cur = []
                in_cnot = False
    per_stab = {}
    for li, layer in enumerate(layers):
        for a, b in layer:
            if b not in data and a in data:
                anc, other = b, a
            elif a not in data and b in data:
                anc, other = a, b
            else:
                continue
            per_stab.setdefault(anc, []).append((li, other))
    return data, per_stab


def logical_set(d, data):
    gen_lines = __import__("stim").Circuit.generated(
        "surface_code:rotated_memory_x",
        distance=d, rounds=1,
        after_clifford_depolarization=0.0)
    lines = str(gen_lines).splitlines()
    n_meas = 0
    mx_order = []
    for l in lines:
        parts = l.split()
        if parts[0] in ("M", "MX", "MR", "MRX"):
            qs = [int(x) for x in parts[1:]
                  if x.lstrip("-").isdigit()]
            n_meas += len(qs)
            if parts[0] == "MX" and len(qs) == len(data):
                mx_order = qs
    obs = None
    for l in lines:
        if l.startswith("OBSERVABLE_INCLUDE"):
            obs = l
    assert obs is not None and mx_order
    recs = [int(t[4:-1]) for t in obs.split()[1:]]
    return sorted(mx_order[r + len(mx_order)] for r in recs)


def layout(d):
    data, per_stab = transcribe_layers(d)
    import stim
    gen = stim.Circuit.generated("surface_code:rotated_memory_x",
                                 distance=d, rounds=1,
                                 after_clifford_depolarization=0.0)
    lines = str(gen).splitlines()
    hset = set()
    for l in lines:
        parts = l.split()
        if parts[0] == "H":
            hset.update(int(x) for x in parts[1:])
    stabs = []
    for anc, items in per_stab.items():
        typ = "X" if anc in hset else "Z"
        support = [other for (_, other) in items]
        slots = [li for (li, _) in items]
        stabs.append((typ, support, anc, slots))
    stabs.sort(key=lambda t: t[2])
    remap = {q: i for i, q in enumerate(data)}
    out = []
    for typ, sup, anc, slots in stabs:
        out.append((typ, [remap[q] for q in sup], slots))
    logiset = [remap[q] for q in logical_set(d, data)]
    return [remap[q] for q in data], out, logiset


def noise_1q(p):
    px = p / (ETA + 2.0)
    return (px, px, p * ETA / (ETA + 2.0))


def build_memory(d, rounds, p, injections=None):
    import stim
    data, stabs, logiset = layout(d)
    idx = build_index(d, rounds)
    det_of = idx["det_of"]
    ndata = len(data)
    px, py, pz = noise_1q(p)
    q = ndata
    synd = list(range(q, q + len(stabs)))
    q += len(stabs)
    c = stim.Circuit()
    for i in range(q):
        c.append("QUBIT_COORDS", [i], [])
    for dq in range(ndata):
        c.append("RX", [dq])
    if p:
        c.append("PAULI_CHANNEL_1", list(range(ndata)), [px, py, pz])
    c.append("TICK", [])
    nm = [0]
    synrec = {}

    def meas(qb, flip, xbasis):
        c.append("MX" if xbasis else "M", [qb],
                 [flip] if flip else [])
        k = nm[0]
        nm[0] += 1
        return k

    inj = {}
    for (ri, qq, pp) in (injections or []):
        inj.setdefault(ri, []).append((qq, pp))
    max_layer = 0
    for _, _, slots in stabs:
        max_layer = max(max_layer, max(slots))
    for r in range(rounds):
        for s, (typ, _, _) in enumerate(stabs):
            c.append("RX" if typ == "X" else "R", [synd[s]])
            if p:
                c.append("PAULI_CHANNEL_1", [synd[s]], [px, py, pz])
        c.append("TICK", [])
        for li in range(max_layer + 1):
            for s, (typ, pts, slots) in enumerate(stabs):
                if li not in slots:
                    continue
                a = synd[s]
                k = slots.index(li)
                dq = pts[k]
                if typ == "Z":
                    c.append("CNOT", [dq, a])
                else:
                    c.append("CNOT", [a, dq])
                if p:
                    c.append("PAULI_CHANNEL_1", [dq], [px, py, pz])
                    c.append("PAULI_CHANNEL_1", [a], [px, py, pz])
            c.append("TICK", [])
        for (qq, pp) in inj.get(r, []):
            c.append(pp, [qq])
        for s, (typ, _, _) in enumerate(stabs):
            synrec[(s, r)] = meas(synd[s], p, typ == "X")
        c.append("TICK", [])
    datarec = {}
    for dq in range(ndata):
        datarec[dq] = meas(dq, p, True)
    c.append("TICK", [])
    total = nm[0]

    def rec(k):
        return stim.target_rec(k - total)

    for s, (typ, _, _) in enumerate(stabs):
        for r in range(rounds):
            if det_of[s][r] < 0:
                continue
            if r == 0:
                c.append("DETECTOR", [rec(synrec[(s, 0)])], [])
            else:
                c.append("DETECTOR",
                         [rec(synrec[(s, r)]),
                          rec(synrec[(s, r - 1)])], [])
    for s, (typ, pts, _) in enumerate(stabs):
        if typ != "X":
            continue
        c.append("DETECTOR",
                 [rec(datarec[dq]) for dq in pts] +
                 [rec(synrec[(s, rounds - 1)])], [])
    obs = [rec(datarec[dq]) for dq in logiset]
    c.append("OBSERVABLE_INCLUDE", obs, [0])
    return c


def build_index(d, rounds):
    _, stabs, logiset = layout(d)
    n_stab = len(stabs)
    det_of = [[-1] * rounds for _ in range(n_stab)]
    k = 0
    for i, (typ, _, _) in enumerate(stabs):
        for r in range(rounds):
            if r == 0 and typ == "Z":
                continue
            det_of[i][r] = k
            k += 1
    fin_of = {}
    for i, (typ, _, _) in enumerate(stabs):
        if typ == "X":
            fin_of[i] = k
            k += 1
    n_det = k
    gid_typ = {}
    for i, (typ, _, _) in enumerate(stabs):
        for r in range(rounds):
            if det_of[i][r] >= 0:
                gid_typ[det_of[i][r]] = typ
    ndata = d * d
    xadj = [[] for _ in range(ndata)]
    zadj = [[] for _ in range(ndata)]
    for i, (typ, pts, _) in enumerate(stabs):
        for qq in pts:
            if typ == "Z":
                xadj[qq].append(i)
            else:
                zadj[qq].append(i)
    return {"stabs": stabs, "logiset": logiset, "n_stab": n_stab,
            "rounds": rounds, "det_of": det_of, "fin_of": fin_of,
            "n_det": n_det, "xadj": xadj, "zadj": zadj, "ndata": ndata,
            "gid_typ": gid_typ}


def build_graphs(idx, p):
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra
    stabs = idx["stabs"]
    rounds = idx["rounds"]
    det_of = idx["det_of"]
    px, py, pz = noise_1q(p)
    w_sx = -math.log(px + py)
    w_sz = -math.log(pz + py)
    w_sy = -math.log(py)
    w_t = -math.log(p)
    graphs = {}
    for sub, want in (("X", "Z"), ("Z", "X")):
        sub_stabs = [i for i, (typ, _, _) in enumerate(stabs)
                     if typ == want]
        g2l = {}
        nodes = []
        for i in sub_stabs:
            for r in range(rounds):
                if det_of[i][r] < 0:
                    continue
                g2l[det_of[i][r]] = len(nodes)
                nodes.append(det_of[i][r])
        nb = len(nodes)
        mechs = []
        adj = {v: [] for v in range(nb + 1)}
        edge_lookup = {}

        def add_edge(u, v, w, corr):
            adj[u].append((v, len(mechs)))
            adj[v].append((u, len(mechs)))
            edge_lookup[(min(u, v), max(u, v))] = len(mechs)
            mechs.append({"nodes": (u, v), "w": w, "corr": corr})

        for qq in range(idx["ndata"]):
            adj_st = idx["xadj"][qq] if sub == "X" else idx["zadj"][qq]
            corr = ("X" if sub == "X" else "Z", qq)
            w = w_sx if sub == "X" else w_sz
            for r in range(rounds):
                here = [g2l[det_of[i][r]] for i in adj_st
                        if det_of[i][r] >= 0]
                if len(here) == 2:
                    add_edge(here[0], here[1], w, (corr, r))
                elif len(here) == 1:
                    add_edge(here[0], nb, w, (corr, r))
        for i in sub_stabs:
            for r in range(rounds):
                ends = []
                if det_of[i][r] >= 0:
                    ends.append(g2l[det_of[i][r]])
                if r + 1 < rounds:
                    ends.append(g2l[det_of[i][r + 1]])
                if len(ends) == 2:
                    add_edge(ends[0], ends[1], w_t, (None, r))
                elif len(ends) == 1:
                    add_edge(ends[0], nb, w_t, (None, r))
        row, col, dat = [], [], []
        for u, nbrs in adj.items():
            best = {}
            for v, _ in nbrs:
                if u == v:
                    continue
                w = min(m["w"] for m in
                        (mechs[mj] for _, mj in nbrs if _ == v))
                if v not in best or w < best[v]:
                    best[v] = w
            for v, w in best.items():
                row.append(u)
                col.append(v)
                dat.append(w)
        mat = csr_matrix((dat, (row, col)),
                         shape=(nb + 1, nb + 1))
        dist, pred = dijkstra(mat, directed=False,
                              return_predecessors=True)
        graphs[sub] = {"nodes": nodes, "g2l": g2l, "nb": nb,
                       "mechs": mechs, "adj": adj,
                       "edge_lookup": edge_lookup,
                       "dist": np.asarray(dist),
                       "pred": np.asarray(pred)}
    return graphs


def sample_cell(d, rounds, p, shots, seed):
    import numpy as np
    c = build_memory(d, rounds, p)
    sampler = c.compile_sampler(seed=seed)
    m = sampler.sample(shots)
    conv = c.compile_m2d_converter()
    det, obs = conv.convert(measurements=m,
                            separate_observables=True)
    return (np.asarray(det, dtype=bool),
            np.asarray(obs, dtype=float).ravel().astype(int))


def round_cnots(idx):
    stabs = idx["stabs"]
    ndata = idx["ndata"]
    synd_base = ndata
    max_layer = 0
    for _, _, slots in stabs:
        max_layer = max(max_layer, max(slots))
    ops = []
    for li in range(max_layer + 1):
        for s, (typ, pts, slots) in enumerate(stabs):
            if li not in slots:
                continue
            k = slots.index(li)
            dq = pts[k]
            a = synd_base + s
            if typ == "Z":
                ops.append((dq, a))
            else:
                ops.append((a, dq))
    return ops


def build_kernels(idx):
    stabs = idx["stabs"]
    ndata = idx["ndata"]
    rounds = idx["rounds"]
    det_of = idx["det_of"]
    cnots = round_cnots(idx)
    datamask = (1 << ndata) - 1
    store = {}
    for qq in range(ndata):
        for b in (0, 1):
            fx = (1 << qq) if b == 0 else 0
            fz = (1 << qq) if b == 1 else 0
            syn = []
            frames = []
            for k in range(rounds):
                if k > 0:
                    fx &= datamask
                    fz &= datamask
                    for (cc, tt) in cnots:
                        if (fx >> cc) & 1:
                            fx ^= (1 << tt)
                        if (fz >> tt) & 1:
                            fz ^= (1 << cc)
                frames.append((fx, fz))
                fl = set()
                for i, (typ, pts, _) in enumerate(stabs):
                    par = 0
                    if typ == "X":
                        for qq2 in pts:
                            par ^= (fz >> qq2) & 1
                    else:
                        for qq2 in pts:
                            par ^= (fx >> qq2) & 1
                    if par:
                        fl.add(i)
                syn.append(fl)
            store[(qq, b)] = (syn, frames)
    return store


def kernel_tables(idx, store):
    det_of = idx["det_of"]
    fin_of = idx["fin_of"]
    rounds = idx["rounds"]
    logiset = idx["logiset"]
    stabs = idx["stabs"]

    def pat(qq, r, b):
        syn, frames = store[(qq, b)]
        out = set()
        for j in range(rounds - r):
            if j == 0:
                continue
            absr = r + j
            for i in syn[j]:
                prev = (i in syn[j - 1]) if j > 1 else False
                cur = True
                if cur ^ prev:
                    out.add(det_of[i][absr])
        _fxf, fzf = frames[rounds - 1 - r]
        if r <= rounds - 2:
            _fxp, fzp = frames[rounds - 2 - r]
        else:
            fzp = 0
        for i, (typ, pts, _) in enumerate(stabs):
            if typ != "X":
                continue
            rp = 0
            sp = 0
            for qq2 in pts:
                rp ^= (fzf >> qq2) & 1
                sp ^= (fzp >> qq2) & 1
            if rp ^ sp:
                out.add(fin_of[i])
        o = 0
        for qq2 in logiset:
            o ^= (fzf >> qq2) & 1
        return out, o

    xr = {}
    zr = {}
    yr = {}
    ox = {}
    oz = {}

    for qq in range(idx["ndata"]):
        for r in range(rounds):
            fx, oxb = pat(qq, r, 0)
            fz, ozb = pat(qq, r, 1)
            xr[(qq, r)] = sorted(fx)
            zr[(qq, r)] = sorted(fz)
            yr[(qq, r)] = sorted(fx | fz)
            ox[(qq, r)] = oxb
            oz[(qq, r)] = ozb
    return {"xr": xr, "zr": zr, "yr": yr, "ox": ox, "oz": oz}


def overlay_erasures(idx, ker, det, obs, p, rng):
    import numpy as np
    det = det.copy()
    obs = obs.copy()
    shots = det.shape[0]
    n = idx["ndata"]
    rounds = idx["rounds"]
    era = rng.random((shots, n, rounds)) < p
    pau = rng.integers(0, 4, size=(shots, n, rounds)).astype(np.int8)
    for qq in range(n):
        for r in range(rounds):
            m = era[:, qq, r]
            if not bool(m.any()):
                continue
            pm = pau[:, qq, r]
            xrows = m & ((pm == 1) | (pm == 2))
            zrows = m & ((pm == 3) | (pm == 2))
            if bool(xrows.any()) and ker["xr"][(qq, r)]:
                det[np.ix_(xrows, ker["xr"][(qq, r)])] ^= True
            if bool(zrows.any()) and ker["zr"][(qq, r)]:
                det[np.ix_(zrows, ker["zr"][(qq, r)])] ^= True
            if bool(xrows.any()) and ker["ox"][(qq, r)]:
                obs[xrows] ^= 1
            if bool(zrows.any()) and ker["oz"][(qq, r)]:
                obs[zrows] ^= 1
    flags = []
    for s in range(shots):
        qs, rs = np.nonzero(era[s])
        flags.append(set(zip(qs.tolist(), rs.tolist())))
    return det, obs, flags


def uf_decode(g, defects):
    nb = g["nb"]
    adj = g["adj"]
    mechs = g["mechs"]
    verts = set(defects) | ({nb} if nb in defects else set())
    parent = {v: v for v in verts}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for u, nbrs in adj.items():
        for v, _ in nbrs:
            if u in verts and v in verts:
                union(u, v)
    comp_of = {}
    for v in verts:
        comp_of.setdefault(find(v), {"verts": set(), "defs": set()})
        comp_of[find(v)]["verts"].add(v)
        if v in defects:
            comp_of[find(v)]["defs"].add(v)
    for _ in range(4 * (nb + 1) + 4):
        odd = [c for c in comp_of.values()
               if len(c["defs"]) % 2 == 1 and nb not in c["verts"]]
        if not odd:
            break
        grow = set()
        for c in odd:
            for v in c["verts"]:
                for w, _ in adj[v]:
                    grow.add(w)
        for w in grow:
            if w not in verts:
                verts.add(w)
                parent[w] = w
            for v in list(verts):
                if v != w:
                    for x, _ in adj[w]:
                        if x == v:
                            union(w, v)
                            break
        comp_of = {}
        for v in verts:
            comp_of.setdefault(find(v), {"verts": set(),
                                         "defs": set()})
            comp_of[find(v)]["verts"].add(v)
            if v in defects:
                comp_of[find(v)]["defs"].add(v)
    corrs = []
    for c in comp_of.values():
        verts_c = c["verts"]
        root = nb if nb in verts_c else min(verts_c)
        par = {root: None}
        pedge = {}
        stack = [root]
        while stack:
            u = stack.pop()
            for w, mj in adj[u]:
                if w in verts_c and w not in par:
                    par[w] = u
                    pedge[w] = mj
                    stack.append(w)
        cnt = {v: (1 if v in c["defs"] else 0) for v in verts_c}
        seen = set()

        def depth(v):
            d = 0
            while par.get(v) is not None:
                v = par[v]
                d += 1
            return d

        for v in sorted(verts_c, key=depth, reverse=True):
            if v == root or v in seen:
                continue
            seen.add(v)
            if cnt[v] % 2 == 1:
                mj = pedge[v]
                m = mechs[mj]
                if m["corr"][0] is not None:
                    (tqq, rr) = m["corr"]
                    corrs.append((tqq[0], tqq[1], rr))
                cnt[par[v]] += 1
    return corrs


def peel_decode(idx, graphs, ker, defects, erased):
    ty = idx["gid_typ"]
    uncovered = set(defects)
    corrs = []
    cands = []
    for (qq, rr) in erased:
        if (qq, rr) in ker["yr"]:
            cands.append((set(ker["yr"][(qq, rr)]),
                          ("Y", qq, rr), True))
        if (qq, rr) in ker["xr"]:
            cands.append((set(ker["xr"][(qq, rr)]),
                          ("X", qq, rr), False))
        if (qq, rr) in ker["zr"]:
            cands.append((set(ker["zr"][(qq, rr)]),
                          ("Z", qq, rr), False))
    cands.sort(key=lambda e: (e[1][2], e[1][1], e[1][0]))
    for pat, corr, joint in cands:
        new = pat & uncovered
        if len(new) < 2:
            continue
        if joint:
            xs = sum(1 for v in new if ty.get(v) == "Z")
            zs = sum(1 for v in new if ty.get(v) == "X")
            if xs < 1 or zs < 1:
                continue
        corrs.append(corr)
        uncovered -= pat
    for ssub, want in (("X", "Z"), ("Z", "X")):
        dd = set(graphs[ssub]["g2l"][v] for v in uncovered
                 if ty.get(v) == want)
        corrs.extend(uf_decode(graphs[ssub], dd))
    return corrs, 0


class MWPMTimeout(Exception):
    pass


def matching_solve(nodes, wmat, timelimit):
    import pulp
    k = len(nodes)
    if k == 0:
        return [], 0.0
    ids = list(range(k)) + ([k] if k % 2 == 1 else [])
    pairs = [(a, b) for ii, a in enumerate(ids)
             for b in ids[ii + 1:]]
    prob = pulp.LpProblem("match", pulp.LpMinimize)
    xs = prob.add_variable_dicts("e", pairs, cat="Binary")
    coeffs = {}
    for (a, b) in pairs:
        if a < k and b < k:
            w = float(wmat[nodes[a]][nodes[b]])
        elif a < k:
            w = float(wmat[nodes[a]][k])
        else:
            w = float(wmat[nodes[b]][k])
        if not math.isfinite(w):
            raise MWPMTimeout("non-finite matching weight")
        coeffs[(a, b)] = w
    prob.setObjective(sum(coeffs[pr] * xs[pr] for pr in pairs))
    for a in ids:
        prob.addConstraint(
            sum(xs[(a, b) if a < b else (b, a)] for b in ids
                if b != a) == 1)
    stats = prob.solve(pulp.COIN_CMD(msg=0, timeLimit=timelimit,
                                     threads=1))
    if "optimal" not in str(stats.status_str).lower():
        raise MWPMTimeout("status=%s" % stats.status_str)
    chosen = [pr for pr in pairs if xs[pr].value() > 0.5]
    return chosen, float(sum(coeffs[pr] for pr in chosen))


def pairing_weight(nodes, wmat, pairing):
    tot = 0.0
    for (a, b) in pairing:
        tot += float(wmat[nodes[a]][nodes[b]])
    return tot


def enumerate_pairings(nodes, wmat, cap, stop=None):
    state = {"nodes": 0, "best": None, "best_pair": None,
             "stopped": False}

    def rec(rem, acc, tot):
        state["nodes"] += 1
        if state["nodes"] > cap:
            return True
        if stop is not None and state["nodes"] % 512 == 0 \
                and stop():
            state["stopped"] = True
            return True
        if not rem:
            if state["best"] is None or tot < state["best"]:
                state["best"] = tot
                state["best_pair"] = list(acc)
            return False
        a = rem[0]
        for ii in range(1, len(rem)):
            b = rem[ii]
            w = float(wmat[nodes[a]][nodes[b]])
            rest = rem[1:ii] + rem[ii + 1:]
            done = rec(rest, acc + [(a, b)], tot + w)
            if done and (state["nodes"] > cap or
                         state["stopped"]):
                return True
        return False

    ids = list(range(len(nodes)))
    rec(ids, [], 0.0)
    if state["stopped"]:
        return {"status": "stopped-guard", "nodes": state["nodes"],
                "best": None, "pairing": None, "cap": cap}
    if state["nodes"] > cap or state["best"] is None:
        return {"status": "cap-hit", "nodes": state["nodes"],
                "best": None, "pairing": None, "cap": cap}
    return {"status": "solved", "nodes": state["nodes"],
            "best": state["best"], "pairing": state["best_pair"],
            "cap": cap}


def path_corr(g, u, v):
    pred = g["pred"]
    nb = g["nb"]
    if u == v:
        return []
    seq = [v]
    cur = v
    guard = 0
    while cur != u and guard <= nb + 1:
        cur = int(pred[u][cur])
        seq.append(cur)
        guard += 1
    if seq[-1] != u:
        return None
    seq = seq[::-1]
    out = []
    for a, b in zip(seq[:-1], seq[1:]):
        mj = g["edge_lookup"].get((min(a, b), max(a, b)))
        if mj is None:
            return None
        m = g["mechs"][mj]
        if m["corr"][0] is not None:
            (tqq, rr) = m["corr"]
            out.append((tqq[0], tqq[1], rr))
    return out


def mwpm_decode(g, defects, timelimit):
    nb = g["nb"]
    loc = sorted(g["g2l"][v] for v in defects)
    if not loc:
        return []
    nodes = loc + ([nb] if len(loc) % 2 == 1 else [])
    wmat = g["dist"]
    chosen, _ = matching_solve(nodes, wmat, timelimit)
    corrs = []
    for (a, b) in chosen:
        u = nodes[a]
        v = nodes[b]
        pc = path_corr(g, u, v)
        if pc is None:
            raise MWPMTimeout("disconnected pair")
        corrs.extend(pc)
    return corrs


def predict_flip(corrs, logiset):
    logi = set(logiset)
    f = 0
    for (typ, qq, _rr) in corrs:
        if typ in ("Z", "Y") and qq in logi:
            f ^= 1
    return f


def event_flips(ker, qq, r, pauli):
    flips = set()
    obs = 0
    if pauli in ("X", "Y"):
        flips.update(ker["xr"][(qq, r)])
        obs ^= ker["ox"][(qq, r)]
    if pauli in ("Z", "Y"):
        flips.update(ker["zr"][(qq, r)])
        obs ^= ker["oz"][(qq, r)]
    return flips, obs


def apply_corrs(idx, ker, defects, corrs):
    res = set(defects)
    for (typ, qq, r) in corrs:
        if r is None or r < 0:
            continue
        flips, _ = event_flips(ker, qq, r,
                               "X" if typ == "X"
                               else ("Z" if typ == "Z" else "Y"))
        for v in flips:
            if v in idx["gid_typ"]:
                if v in res:
                    res.discard(v)
                else:
                    res.add(v)
    return res


def manual_det_obs(idx, row):
    stabs = idx["stabs"]
    rounds = idx["rounds"]
    det_of = idx["det_of"]
    fin_of = idx["fin_of"]
    n_stab = idx["n_stab"]
    det = set()
    for s in range(n_stab):
        for r in range(rounds):
            gid = det_of[s][r]
            if gid < 0:
                continue
            a = r * n_stab + s
            if r == 0:
                v = row[a]
            else:
                v = row[a] ^ row[a - n_stab]
            if v:
                det.add(gid)
    base = rounds * n_stab
    for s, (typ, pts, _) in enumerate(stabs):
        if typ != "X":
            continue
        v = 0
        for qq in pts:
            v ^= row[base + qq]
        v ^= row[(rounds - 1) * n_stab + s]
        if v:
            det.add(fin_of[s])
    o = 0
    for qq in idx["logiset"]:
        o ^= row[base + qq]
    return det, int(o)


def graph_residual(g, defects_global, corrs):
    rev = {}
    for m in g["mechs"]:
        co, rr = m["corr"]
        if co is None:
            continue
        nodes = set(g["nodes"][v] for v in m["nodes"]
                    if v < g["nb"])
        rev.setdefault((co[0], co[1], rr), set()).update(nodes)
    res = set(defects_global)
    for (typ, qq, r) in corrs:
        for v in rev.get((typ, qq, r), set()):
            if v in res:
                res.discard(v)
            else:
                res.add(v)
    return res


def ler_stats(errs, n):
    import numpy as np
    a = np.asarray(errs, dtype=float)
    if n == 0:
        return {"n": 0, "ler": None, "se": None, "errors": 0}
    ler = float(a.sum() / n)
    se = float(math.sqrt(ler * (1.0 - ler) / n)) if n else None
    return {"n": int(n), "ler": ler, "se": se,
            "errors": int(a.sum())}


def self_tests():
    out = {"ran": True, "failed": []}
    try:
        import numpy as np
        _, stabs5, _ = layout(5)
        data5 = 5 * 5
        if len(stabs5) != data5 - 1:
            out["failed"].append("layout-counts-d5")
        idx3 = build_index(3, 3)
        n_x = sum(1 for (t, _, _) in idx3["stabs"] if t == "X")
        n_z = sum(1 for (t, _, _) in idx3["stabs"] if t == "Z")
        c3 = build_memory(3, 3, 0.0)
        if c3.num_detectors != idx3["n_det"]:
            out["failed"].append("detector-count")
        if c3.num_detectors != 8 * 3 - n_z + n_x:
            out["failed"].append("detector-count-shape")
        det0, obs0 = sample_cell(3, 3, 0.0, 200, 7)
        if bool(det0.any()) or bool(obs0.any()):
            out["failed"].append("noiseless-zeros")
        a1, b1 = sample_cell(5, 5, 0.005, 50, 11)
        a2, b2 = sample_cell(5, 5, 0.005, 50, 11)
        if not (np.array_equal(a1, a2) and np.array_equal(b1, b2)):
            out["failed"].append("determinism")
        if a1.shape[1] != build_index(5, 5)["n_det"]:
            out["failed"].append("m2d-shape")
        ker3 = kernel_tables(idx3, build_kernels(idx3))
        cn = build_memory(3, 3, 0.005)
        mn = cn.compile_sampler(seed=21).sample(200)
        cnv = cn.compile_m2d_converter()
        dn, on = cnv.convert(measurements=mn,
                             separate_observables=True)
        dn = np.asarray(dn, dtype=bool)
        on = np.asarray(on, dtype=int).ravel()
        for s in range(200):
            md, mo = manual_det_obs(
                idx3, np.asarray(mn[s], dtype=int))
            cd = set(np.flatnonzero(dn[s]))
            if md != cd or mo != int(on[s]):
                out["failed"].append("manual-converter-agree")
                break
        mbase = build_memory(3, 3, 0.0).compile_sampler(
            seed=5).sample(1)
        d0, o0 = manual_det_obs(
            idx3, np.asarray(mbase[0], dtype=int))
        for (qq, r, pp) in ((0, 0, "X"), (4, 1, "Z"), (8, 2, "Y"),
                            (3, 0, "Y"), (5, 2, "X"), (1, 1, "X"),
                            (7, 0, "Z"), (2, 2, "Y")):
            ci = build_memory(3, 3, 0.0,
                              injections=[(r, qq, pp)])
            m = ci.compile_sampler(seed=5).sample(1)
            d1, o1 = manual_det_obs(
                idx3, np.asarray(m[0], dtype=int))
            delta = d1 ^ d0
            want, wobs = event_flips(ker3, qq, r, pp)
            if delta != want or (o1 ^ o0) != wobs:
                out["failed"].append("propagate-%d-%d-%s" % (qq, r,
                                                             pp))
        c5 = build_memory(5, 5, 0.005)
        try:
            _deff = c5.shortest_graphlike_error()
        except ValueError:
            out["failed"].append("nondeterministic-circuit")
        except Exception as ex:
            out["failed"].append("deff-raise: %r" % ex)
        idx5 = build_index(5, 5)
        g5 = build_graphs(idx5, 0.005)
        ker5 = kernel_tables(idx5, build_kernels(idx5))
        for sub in ("X", "Z"):
            if uf_decode(g5[sub], set()) != []:
                out["failed"].append("uf-empty-%s" % sub)
        ch0, _ = peel_decode(idx5, g5, ker5, [], set([(0, 0)]))
        if ch0 != []:
            out["failed"].append("peel-empty")
        q0 = idx5["logiset"][0]
        fx, _ = event_flips(ker5, q0, 0, "Y")
        round_fx = sorted(v for v in fx if v in idx5["gid_typ"])
        ch, rd = peel_decode(idx5, g5, ker5, round_fx,
                             set([(q0, 0)]))
        if ("Y", q0, 0) not in ch:
            out["failed"].append("hyb-peel-Y")
        if predict_flip(ch, idx5["logiset"]) != 1:
            out["failed"].append("hyb-peel-obs")
        if rd != 0:
            out["failed"].append("hyb-peel-residual")
        if apply_corrs(idx5, ker5, set(round_fx), ch) != set():
            out["failed"].append("hyb-peel-cover")
        qx = None
        for qq in range(idx5["ndata"]):
            if len(ker5["xr"][(qq, 1)]) >= 2:
                qx = qq
                break
        if qx is None:
            out["failed"].append("no-x-case")
        else:
            fxx, _ = event_flips(ker5, qx, 1, "X")
            rfx = sorted(v for v in fxx if v in idx5["gid_typ"])
            chx, _ = peel_decode(idx5, g5, ker5, rfx,
                                 set([(qx, 1)]))
            if ("X", qx, 1) not in chx:
                out["failed"].append("hyb-peel-X")
            chu, _ = peel_decode(idx5, g5, ker5, rfx, set())
            if any(t == "Y" for (t, _, _) in chu):
                out["failed"].append("peel-unflagged-Y")
        mx = None
        mb = None
        for mj, m in enumerate(g5["X"]["mechs"]):
            if m["corr"][0] is None or len(m["nodes"]) != 2:
                continue
            if all(v < g5["X"]["nb"] for v in m["nodes"]):
                mx = (mj, m)
                break
            if mb is None and any(v >= g5["X"]["nb"]
                                  for v in m["nodes"]):
                mb = (mj, m)
        if mx is None:
            out["failed"].append("no-interior-edge")
        else:
            mj, m = mx
            gids = [g5["X"]["nodes"][v] for v in m["nodes"]]
            loc = [g5["X"]["g2l"][v] for v in gids]
            cu = uf_decode(g5["X"], set(loc))
            if graph_residual(g5["X"], set(gids), cu) != set():
                out["failed"].append("uf-interior-residual")
            single = loc[:1]
            cs = uf_decode(g5["X"], set(single))
            if graph_residual(
                    g5["X"],
                    set([g5["X"]["nodes"][single[0]]]),
                    cs) != set():
                out["failed"].append("uf-boundary-residual")
            cm = mwpm_decode(g5["X"], set([g5["X"]["nodes"][v]
                                           for v in loc]),
                             MWPM_TIMELIMIT_S)
            if graph_residual(g5["X"], set(gids), cm) != set():
                out["failed"].append("mwpm-interior-residual")
            if mb is not None:
                _, bmech = mb
                blocs = [v for v in bmech["nodes"]
                         if v < g5["X"]["nb"]]
                bgids = set(g5["X"]["nodes"][v] for v in blocs)
                cb = mwpm_decode(g5["X"], set(bgids),
                                 MWPM_TIMELIMIT_S)
                if not isinstance(cb, list):
                    out["failed"].append("mwpm-boundary-residual")
                else:
                    uloc = [g5["X"]["g2l"][v] for v in bgids]
                    unodes = uloc + [g5["X"]["nb"]]
                    _ch, w = matching_solve(
                        unodes, g5["X"]["dist"], MWPM_TIMELIMIT_S)
                    if abs(w - float(
                            g5["X"]["dist"][uloc[0]][g5["X"]["nb"]])) \
                            > 1e-9:
                        out["failed"].append(
                            "mwpm-boundary-weight")
        nodes6 = [0, 1, 2, 3, 4, 5]
        en = enumerate_pairings(nodes6, g5["X"]["dist"], ENUM_CAP)
        if en["status"] != "solved":
            out["failed"].append("tiny-not-solved")
        else:
            ch2, _ = matching_solve(nodes6, g5["X"]["dist"],
                                    MWPM_TIMELIMIT_S)
            pw = pairing_weight(nodes6, g5["X"]["dist"], ch2)
            if abs(pw - en["best"]) > 1e-6:
                out["failed"].append("pulp-enum-disagree")
    except MWPMTimeout:
        out["failed"].append("selftest-mwpm-timeout")
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def main():
    import numpy as np
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--data", required=True)
    ap.parse_args()
    outdir = os.getcwd()
    witdir = os.path.join(outdir, "witnesses")
    os.makedirs(witdir, exist_ok=True)
    t0 = time.perf_counter()

    def elapsed():
        return time.perf_counter() - t0

    def over():
        return elapsed() > WALL_GUARD_S

    skipped = []
    cells = {}
    cellrecs = []
    mwpmrecs = []
    gate3 = {"tiny": {}, "target": {}}
    selftest = self_tests()
    with open(os.path.join(witdir, "selftest.json"), "w") as f:
        json.dump(selftest, f, indent=1, default=str)

    def checkpoint(tag, payload):
        try:
            with open(os.path.join(witdir, "checkpoint-%s.json" % tag),
                      "w") as f:
                json.dump({"tag": tag, "wall_s": elapsed(),
                           "n_skipped": len(skipped),
                           "verdict": "unresolved-with-reason: partial "
                                      "checkpoint", **payload},
                          f, indent=1, default=str)
        except Exception:
            pass

    checkpoint("selftest", {"selftest_failed": selftest["failed"]})
    idx_cache = {}
    graph_cache = {}
    ker_cache = {}

    def get_idx(d):
        if d not in idx_cache:
            idx_cache[d] = build_index(d, d)
        return idx_cache[d]

    def get_graphs(d, p):
        if (d, p) not in graph_cache:
            graph_cache[(d, p)] = build_graphs(get_idx(d), p)
        return graph_cache[(d, p)]

    def get_ker(d):
        if d not in ker_cache:
            ker_cache[d] = kernel_tables(get_idx(d),
                                         build_kernels(get_idx(d)))
        return ker_cache[d]

    if over():
        gate3["tiny"] = {"status": "skipped-guard"}
        skipped.append({"what": "tiny-exact", "reason": "wall-guard"})
    else:
        idx5 = get_idx(5)
        g5x = get_graphs(5, P_GRID[1])["X"]
        nodes6 = [0, 1, 2, 3, 4, 5]
        en = enumerate_pairings(nodes6, g5x["dist"], ENUM_CAP, over)
        pulp_agree = None
        if en["status"] == "solved":
            try:
                ch2, _ = matching_solve(nodes6, g5x["dist"],
                                        MWPM_TIMELIMIT_S)
                pw = pairing_weight(nodes6, g5x["dist"], ch2)
                pulp_agree = bool(abs(pw - en["best"]) < 1e-6)
            except MWPMTimeout:
                pulp_agree = False
                skipped.append({"what": "tiny-pulp-cross",
                                "reason": "mwpm-timeout"})
        gate3["tiny"] = {"status": en["status"],
                         "nodes": en["nodes"], "cap": ENUM_CAP,
                         "best": en["best"],
                         "defects": len(nodes6),
                         "pulp_agree": pulp_agree}
    with open(os.path.join(witdir, "gate3_tiny.json"), "w") as f:
        json.dump(gate3["tiny"], f, indent=1, default=str)
    checkpoint("tiny", {"gate3tiny": gate3["tiny"]})

    if over():
        gate3["target"] = {"status": "skipped-guard"}
        skipped.append({"what": "target-enum",
                        "reason": "wall-guard"})
    else:
        idx9 = get_idx(9)
        ty9 = idx9["gid_typ"]
        found = None
        det9, _ = sample_cell(9, 9, P_GRID[-1], TARGET_SCAN_SHOTS,
                              999)
        for s in range(TARGET_SCAN_SHOTS):
            if over():
                break
            row = set(int(v) for v in np.flatnonzero(det9[s]))
            for sub, want in (("X", "Z"), ("Z", "X")):
                dd = sorted(v for v in row if v in ty9
                            and ty9[v] == want)
                if len(dd) >= TARGET_MIN_DEFECTS:
                    found = {"sub": sub, "defects": dd,
                             "shot": s}
                    break
            if found is not None:
                break
        if found is None:
            gate3["target"] = {"status": "no-qualifying-syndrome",
                               "scanned": TARGET_SCAN_SHOTS}
        else:
            g9 = get_graphs(9, P_GRID[-1])[found["sub"]]
            loc = sorted(g9["g2l"][v] for v in found["defects"])
            nodes = loc + ([g9["nb"]] if len(loc) % 2 == 1
                           else [])
            en9 = enumerate_pairings(nodes, g9["dist"], ENUM_CAP,
                                     over)
            gate3["target"] = {"status": en9["status"],
                               "nodes": en9["nodes"],
                               "cap": ENUM_CAP, "best": en9["best"],
                               "defects": len(found["defects"]),
                               "sub": found["sub"],
                               "distance": 9}
    with open(os.path.join(witdir, "gate3_target.json"), "w") as f:
        json.dump(gate3["target"], f, indent=1, default=str)
    checkpoint("targets", {"gate3target": gate3["target"]})

    hyb_sec = [0.0]
    hyb_n = [0]
    uf_sec = [0.0]
    uf_n = [0]
    mwpm_sec = [0.0]
    mwpm_n = [0]

    for d in DISTANCES:
        idx = get_idx(d)
        ty = idx["gid_typ"]
        logiset = idx["logiset"]
        ker = get_ker(d)
        for pi, p in enumerate(P_GRID):
            graphs = get_graphs(d, p)
            for seed in SEEDS:
                if over():
                    skipped.append(
                        {"what": "cell d%d-p%.4f-seed%d" % (d, p,
                                                            seed),
                         "reason": "wall-guard"})
                    continue
                sseed = d * 1000 + pi * 100 + seed
                det, obs = sample_cell(d, d, p, N_SHOTS, sseed)
                rng = np.random.default_rng(30000 + d * 1000 +
                                            pi * 100 + seed)
                det, obs, flags = overlay_erasures(idx, ker, det, obs,
                                                   p, rng)
                rec = {"d": d, "p": p, "seed": seed, "n": N_SHOTS,
                       "hyb": None, "uf": None}
                for arm in ("hyb", "uf"):
                    errs = []
                    tcell = time.perf_counter()
                    ndone = 0
                    resid = 0
                    for s in range(N_SHOTS):
                        if s % 64 == 0 and over():
                            break
                        row = set(int(v)
                                  for v in np.flatnonzero(det[s]))
                        grp = sorted(v for v in row if v in ty)
                        if arm == "hyb":
                            ch, rd = peel_decode(idx, graphs, ker,
                                                 grp, flags[s])
                            resid += rd
                            pred = predict_flip(ch, logiset)
                        else:
                            ch = []
                            for ssub, want in (("X", "Z"),
                                               ("Z", "X")):
                                dd = set(graphs[ssub]["g2l"][v]
                                         for v in grp
                                         if ty[v] == want)
                                ch.extend(uf_decode(graphs[ssub],
                                                    dd))
                            pred = predict_flip(ch, logiset)
                        errs.append(1 if pred != int(obs[s]) else 0)
                        ndone += 1
                    dt = time.perf_counter() - tcell
                    st = ler_stats(errs, ndone)
                    st["ms_per_shot"] = (1000.0 * dt / ndone
                                         if ndone else None)
                    st["n_resid"] = resid
                    st["n_evaluated"] = ndone
                    if ndone < N_SHOTS:
                        skipped.append(
                            {"what": "%s-d%d-p%.4f-seed%d-truncated"
                             % (arm, d, p, seed),
                             "reason": "wall-guard"})
                    rec[arm] = st
                    if arm == "hyb":
                        hyb_sec[0] += dt
                        hyb_n[0] += ndone
                    else:
                        uf_sec[0] += dt
                        uf_n[0] += ndone
                key = "d%d/p%.4f/seed%d" % (d, p, seed)
                cells[key] = rec
                cellrecs.append(rec)
                if seed in MWPM_SEEDS:
                    mrec = {"d": d, "p": p, "seed": seed,
                            "n": N_MWPM, "mwpm": None,
                            "hyb_sub": None}
                    try:
                        merrs = []
                        herrs = []
                        tcell = time.perf_counter()
                        ndone = 0
                        for s in range(N_MWPM):
                            if over():
                                break
                            row = set(int(v) for v in
                                      np.flatnonzero(det[s]))
                            grp = sorted(v for v in row
                                         if v in ty)
                            chx = mwpm_decode(
                                graphs["X"],
                                set(v for v in grp if ty[v] == "Z"),
                                MWPM_TIMELIMIT_S)
                            chz = mwpm_decode(
                                graphs["Z"],
                                set(v for v in grp if ty[v] == "X"),
                                MWPM_TIMELIMIT_S)
                            pred = predict_flip(chx + chz, logiset)
                            merrs.append(1 if pred != int(obs[s])
                                         else 0)
                            chh, _ = peel_decode(idx, graphs, ker,
                                                  grp, flags[s])
                            herrs.append(
                                1 if predict_flip(chh, logiset) !=
                                int(obs[s]) else 0)
                            ndone += 1
                        dt = time.perf_counter() - tcell
                        mst = ler_stats(merrs, ndone)
                        mst["ms_per_shot"] = (1000.0 * dt / ndone
                                              if ndone else None)
                        mst["n_evaluated"] = ndone
                        hst = ler_stats(herrs, ndone)
                        hst["n_evaluated"] = ndone
                        mrec["mwpm"] = mst
                        mrec["hyb_sub"] = hst
                        mwpm_sec[0] += dt
                        mwpm_n[0] += ndone
                        if ndone < N_MWPM:
                            skipped.append(
                                {"what": "mwpm-d%d-p%.4f-truncated"
                                 % (d, p), "reason": "wall-guard"})
                    except MWPMTimeout as ex:
                        skipped.append(
                            {"what": "mwpm-d%d-p%.4f-timeout" % (d,
                                                                p),
                             "reason": "mwpm-timeout: %s" % ex})
                    mwpmrecs.append(mrec)
        with open(os.path.join(witdir, "cells-d%d.json" % d), "w") as f:
            json.dump([r for r in cellrecs if r["d"] == d], f,
                      indent=1, default=str)
        checkpoint("corpus-d%d" % d, {"d": d})
    with open(os.path.join(witdir, "cells.json"), "w") as f:
        json.dump(cellrecs, f, indent=1, default=str)
    with open(os.path.join(witdir, "mwpm.json"), "w") as f:
        json.dump(mwpmrecs, f, indent=1, default=str)
    checkpoint("corpus", {"n_cells": len(cellrecs)})

    def pool(d, p, arm):
        errs = 0
        n = 0
        full = True
        for seed in SEEDS:
            rec = cells.get("d%d/p%.4f/seed%d" % (d, p, seed))
            if rec is None or rec.get(arm) is None:
                return None, False
            st = rec[arm]
            if st.get("n_evaluated") != N_SHOTS:
                full = False
            errs += st["errors"]
            n += st["n_evaluated"]
        if n == 0:
            return None, False
        ler = errs / n
        se = math.sqrt(ler * (1.0 - ler) / n)
        return {"ler": ler, "se": se, "errors": errs, "n": n}, full

    g1a_cells = []
    n_win = 0
    for d in DISTANCES:
        for p in P_GRID:
            h, hf = pool(d, p, "hyb")
            u, uf_ = pool(d, p, "uf")
            ok = (h is not None and u is not None and hf and uf_ and
                  (u["ler"] - h["ler"]) > 2.0 * math.sqrt(
                      u["se"] ** 2 + h["se"] ** 2))
            g1a_cells.append({"cell": "d%d/p%.4f" % (d, p),
                              "hyb": h, "uf": u, "pass": bool(ok)})
            if ok:
                n_win += 1
    mwpm_wins = 0
    mwpm_cells = []
    for mrec in mwpmrecs:
        mst = mrec.get("mwpm")
        hst = mrec.get("hyb_sub")
        ok = (mst is not None and hst is not None and
              mst.get("n_evaluated") == N_MWPM and
              hst.get("ler") is not None and
              mst.get("ler") is not None and
              hst["ler"] <= mst["ler"])
        mwpm_cells.append({"cell": "d%d/p%.4f" % (mrec["d"],
                                                  mrec["p"]),
                           "hyb_sub": hst, "mwpm": mst,
                           "pass": bool(ok)})
        if ok:
            mwpm_wins += 1
    mwpm_majority = bool(mwpm_cells and
                         mwpm_wins * 2 >= len(mwpm_cells) and
                         len(mwpm_cells) == 9)
    tiny_solved = gate3["tiny"].get("status") == "solved"
    pulp_agree = gate3["tiny"].get("pulp_agree") is True
    selftest_ok = bool(selftest.get("ran")) and \
        not selftest.get("failed")
    g1_ok = bool(n_win >= 1 and tiny_solved and pulp_agree and
                 selftest_ok and mwpm_majority)

    g2_ds = []
    g2_n = 0
    for d in DISTANCES:
        vals = []
        for p in P_GRID:
            h, hf = pool(d, p, "hyb")
            vals.append(h["ler"] if (h and hf) else None)
        ok = (len(vals) == 3 and all(v is not None for v in vals)
              and vals[0] < vals[1] < vals[2])
        g2_ds.append({"d": d, "lers": vals, "pass": bool(ok)})
        if ok:
            g2_n += 1
    g2_ok = bool(g2_n >= 2)

    target_cap = gate3["target"].get("status") == "cap-hit"
    g3pass = bool(tiny_solved and target_cap)

    complete = all(
        cells.get("d%d/p%.4f/seed%d" % (d, p, seed), {}).get(
            "hyb", {}).get("n_evaluated") == N_SHOTS and
        cells.get("d%d/p%.4f/seed%d" % (d, p, seed), {}).get(
            "uf", {}).get("n_evaluated") == N_SHOTS
        for d in DISTANCES for p in P_GRID for seed in SEEDS)
    mwpm_full = (len(mwpmrecs) == len(DISTANCES) * len(P_GRID) and
                 all((m.get("mwpm") or {}).get("n_evaluated") == N_MWPM
                     for m in mwpmrecs))
    tiny_attempted = gate3["tiny"].get("status") in (
        "solved", "cap-hit", "stopped-guard", "no-qualifying-syndrome")
    target_attempted = gate3["target"].get("status") in (
        "solved", "cap-hit", "stopped-guard", "no-qualifying-syndrome")
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and mwpm_full and tiny_attempted and
                 target_attempted and wall < WALL_LIMIT_S and clean)

    hyb_ms = (1000.0 * hyb_sec[0] / hyb_n[0]) if hyb_n[0] else None
    mwpm_ms = (1000.0 * mwpm_sec[0] / mwpm_n[0]) if mwpm_n[0] else None
    cycle_ok = bool(hyb_ms is not None and mwpm_ms is not None and
                    hyb_ms < mwpm_ms and hyb_ms < CYCLE_BUDGET_MS)
    pursue = bool(g1_ok and g2_ok and g3pass and g4_ok and
                  selftest_ok and n_win >= 2 and cycle_ok)
    reject = bool(complete and mwpm_full and tiny_solved and
                  pulp_agree and selftest_ok and n_win == 0 and
                  not mwpm_majority)
    if pursue:
        reason = "PURSUE-condition holds (hybrid 2SE wins vs UF in " \
            ">=2 cells + MWPM-subset majority + gates 1,2,3,4 + " \
            "self-tests ok + cycle budget); payload verdict stays " \
            "unresolved-with-reason, classification is coordinator-side."
    elif reject:
        reason = "REJECT-condition holds (complete cells, tiny solved " \
            "and pulp-matched, self-tests ok, no hybrid win vs UF " \
            "anywhere, no MWPM-subset majority); payload verdict " \
            "stays unresolved-with-reason, classification is " \
            "coordinator-side."
    else:
        reason = "UNRESOLVED + next experiment (hyb-vs-UF wins=%d/9 " \
            "mwpm-majority=%d/9 g1=%s g2=%s(%d/3) g3=%s(tiny %s " \
            "target %s) g4=%s selftest=%s cycle=%s complete=%s " \
            "skipped=%d; next: XZZX variant, wider bias sweep, " \
            "time-correlated erasure bursts)." % (
                n_win, mwpm_wins, g1_ok, g2_ok, g2_n, g3pass,
                gate3["tiny"].get("status"),
                gate3["target"].get("status"), g4_ok, selftest_ok,
                cycle_ok, complete and mwpm_full, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "n_win": n_win,
                  "cells": g1a_cells, "mwpm_majority": mwpm_majority,
                  "mwpm_wins": mwpm_wins, "mwpm_cells": mwpm_cells,
                  "tiny_solved": tiny_solved,
                  "pulp_agree": pulp_agree,
                  "selftest_ok": bool(selftest_ok)},
        "gate2": {"pass": bool(g2_ok), "n_d_pass": g2_n,
                  "distances": g2_ds},
        "gate3": {"pass": bool(g3pass), "tiny": gate3["tiny"],
                  "target": gate3["target"], "target_cap": target_cap},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "mwpm_full": bool(mwpm_full),
                  "tiny_attempted": bool(tiny_attempted),
                  "target_attempted": bool(target_attempted),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_condition": bool(pursue),
                       "reject_condition": bool(reject),
                       "cycle_ok": bool(cycle_ok),
                       "hyb_ms_per_shot": hyb_ms,
                       "mwpm_ms_per_shot": mwpm_ms,
                       "uf_ms_per_shot":
                       (1000.0 * uf_sec[0] / uf_n[0])
                       if uf_n[0] else None,
                       "selftest_ok": bool(selftest_ok)},
        "reason": reason,
    }
    results = {
        "screen": "04",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "rotated surface-code X-memory (stim 1.16.0, "
                     "screen-built circuit) + classical heralded-"
                     "erasure overlay (95% conversion) + residual "
                     "biased Pauli noise (Z:X:Y = 10:1:1)",
            "distances": list(DISTANCES),
            "rounds": "d per distance",
            "noise": {"p_grid": list(P_GRID), "bias_eta": ETA,
                      "erasure_rate": "p per qubit per round",
                      "conversion": 0.95},
            "seeds": list(SEEDS),
            "shots": {"hyb_uf": N_SHOTS, "mwpm_subset": N_MWPM,
                      "mwpm_seeds": list(MWPM_SEEDS)},
            "arms": {"hyb": "flagged X/Y/Z hyperedge peel "
                             "(exact propagated patterns, >=2 "
                             "defects, Y needs both sides) + "
                             "Union-Find cluster growth on the "
                             "remainder",
                     "mwpm": "pulp MILP exact matching, static "
                             "graph distances, X/Z separate, subset "
                             "only",
                     "uf": "textbook Union-Find, X/Z separate, "
                           "erasure-unaware"},
            "metrics": "logical error rate vs sampled observable; "
                       "mean per-shot decode wall time",
            "pareto": "PURSUE needs hybrid 2SE wins vs UF in >=2 "
                      "cells + MWPM-subset directional majority on "
                      "the SAME hybrid + cycle budget (hybrid faster "
                      "than MWPM and < 50 ms/shot)",
            "exact": "bounded-exact pairing enumeration (cap %d): "
                     "fixed 6-defect tiny syndrome solves + "
                     "pulp cross-check; d=9 >=14-defect sampled "
                     "syndrome must cap-hit" % ENUM_CAP,
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": cells,
        "mwpm": mwpmrecs,
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    main()
