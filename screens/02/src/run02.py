"""Screen 02 scale-up payload: flag-gadget schedule search at d=3/5/7 (stim + stdlib + numpy).

Scale-up of the certified d=3 screen (canonical 120 CNOTs/16 ancillas vs
exact 72 CNOTs/8 ancillas at d_eff=3, 256/256, greedy 4/5 seeds, random
valid fraction 0.0067, LER tracking across p in {0.002,0.005,0.010}).
Design: sizes d in {3 (certified anchor), 5, 7}; seeds 1-5. Arms per
size: canonical/static schedule, random control, greedy optimizer,
annealed optimizer (d=3 arm structure extended to d=5/d=7); exact
flag-subset enumeration on d=3 (256/256 solves); per-stabilizer capped
enumeration at d=5-class (must cap-hit); d=7 transfer = transcribed
order + zero flags (the d=3 exact-optimum pattern) lifted to d=7 plus
random probes and short greedy/SA refinement. Metric: CNOT/ancilla
overhead at preserved d_eff + LER tracking at matched p.
Load-bearing rules (each with a dedicated self-test): (1) layout
TRANSCRIBED from stim.Circuit.generated("surface_code:rotated_memory_x")
via transcribe() (hand-tiling breaks commutation); (2) FULL-BRACKET
flags (open before first data CNOT, close after last); (3) LER via
compile_sampler() + compile_m2d_converter(separate_observables=True).
Verdict is always unresolved-with-reason; classification is
coordinator-side. Deterministic given seeds (rerun byte-identical
excluding wall_s).
"""

import argparse
import itertools
import json
import math
import os
import time

SEEDS = (1, 2, 3, 4, 5)
P_NOISE = 0.005
ROUNDS = 3
P_GRID = (0.002, 0.005, 0.010)
N_SHOTS = 20000
D_SIZES = (3, 5, 7)
N_RANDOM_SEED_D3 = 60
N_RANDOM_SEED_D5 = 20
N_RANDOM_SEED_D7 = 8
GREEDY_ITERS_D3 = 60
GREEDY_ITERS_D5 = 20
GREEDY_ITERS_D7 = 10
SA_ITERS_D3 = 50
SA_ITERS_D5 = 20
SA_ITERS_D7 = 10
SA_T0 = 1.0
SA_ALPHA = 0.97
ENUM_CAP_EVALS = 150
WALL_GUARD_S = 300.0
WALL_LIMIT_S = 500.0
SALT_D3_RANDOM = 11
SALT_D3_GREEDY = 13
SALT_D3_SA = 17
SALT_D3_SA_NP = 19
SALT_D5_RANDOM = 21
SALT_D5_GREEDY = 23
SALT_D5_SA = 27
SALT_D5_SA_NP = 29
SALT_D7_RANDOM = 31
SALT_D7_GREEDY = 33
SALT_D7_SA = 37
SALT_D7_SA_NP = 39
ANCHOR_CANON3_CNOTS = 120
ANCHOR_CANON3_ANC = 16
ANCHOR_BEST3_CNOTS = 72
ANCHOR_GREEDY3_HITS = 4
EXACT_TOTAL_D3 = 256
NEXT_EXPERIMENT = "NEXT_EXPERIMENT: scale to d=9 with depth-regularized " \
    "joint order+flag search under hardware-calibrated noise, with " \
    "exact-synthesis timeout probes at d=9."


def layout(d):
    return transcribe(d)


def transcribe(d):
    import stim
    data, per_stab = transcribe_layers(d)
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


def logical_set(d, data):
    import stim
    gen = stim.Circuit.generated("surface_code:rotated_memory_x",
                                 distance=d, rounds=1,
                                 after_clifford_depolarization=0.0)
    lines = str(gen).splitlines()
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


def canonical_schedule(stabs):
    return [(tuple(range(len(pts))), True)
            for _, pts, _ in stabs]


def transfer_schedule(stabs):
    return [(tuple(range(len(pts))), False)
            for _, pts, _ in stabs]


def count_cnots(c):
    n = 0
    for l in str(c).splitlines():
        if l.startswith("CNOT") or l.startswith("CX"):
            n += len(l.split()) // 2
    return n


def evaluate(d, rounds, p, sched):
    import stim
    try:
        c = build_memory(d, rounds, p, sched)
    except Exception as ex:
        return {"ok": False, "why": "build-raise: %r" % ex,
                "d_eff": None, "cnots": None, "ancillas": None}
    ndata = d * d
    nq = c.num_qubits
    anc = nq - ndata
    cnots = count_cnots(c)
    try:
        e = c.shortest_graphlike_error()
        deff = int(len(e))
    except ValueError:
        return {"ok": False, "why": "nondeterministic",
                "d_eff": None, "cnots": cnots, "ancillas": anc}
    except Exception as ex:
        return {"ok": False, "why": "eval-raise: %r" % ex,
                "d_eff": None, "cnots": cnots, "ancillas": anc}
    return {"ok": True, "why": None, "d_eff": deff, "cnots": cnots,
            "ancillas": anc}


def all_options(n):
    import itertools as _it
    opts = []
    for perm in _it.permutations(range(n)):
        opts.append((tuple(perm), False))
        opts.append((tuple(perm), True))
    return opts


def sched_key(sched):
    return tuple((tuple(o), bool(f)) for o, f in sched)


def random_schedule(stabs, rng):
    out = []
    for _, pts, _ in stabs:
        n = len(pts)
        order = tuple(rng.sample(range(n), n))
        fl = bool(rng.randrange(2))
        out.append((order, fl))
    return out


def mutate_single(stabs, parent_sched, rng):
    site = int(rng.randrange(len(stabs)))
    _, site_pts, _ = stabs[site]
    n = len(site_pts)
    site_order = list(parent_sched[site][0])
    site_flag = parent_sched[site][1]
    if bool(rng.randrange(2)):
        pos_a = int(rng.randrange(n))
        pos_b = int(rng.randrange(n))
        site_order[pos_a], site_order[pos_b] = \
            site_order[pos_b], site_order[pos_a]
    else:
        site_flag = not site_flag
    child_sched = [(tuple(o), bool(f)) for o, f in parent_sched]
    child_sched[site] = (tuple(site_order), bool(site_flag))
    return child_sched


def pair_mutate(stabs, parent_sched, rng):
    site_a = int(rng.randrange(len(stabs)))
    site_b = int(rng.randrange(len(stabs) - 1))
    if site_b >= site_a:
        site_b += 1
    child_sched = [(tuple(o), bool(f)) for o, f in parent_sched]
    for site in (site_a, site_b):
        _, site_pts, _ = stabs[site]
        n = len(site_pts)
        site_order = list(child_sched[site][0])
        site_flag = child_sched[site][1]
        if bool(rng.randrange(2)):
            pos_a = int(rng.randrange(n))
            pos_b = int(rng.randrange(n))
            site_order[pos_a], site_order[pos_b] = \
                site_order[pos_b], site_order[pos_a]
        else:
            site_flag = not site_flag
        child_sched[site] = (tuple(site_order), bool(site_flag))
    return child_sched


def mutate_wide(stabs, parent_sched, rng):
    if int(rng.randrange(3)) == 0:
        return pair_mutate(stabs, parent_sched, rng)
    return mutate_single(stabs, parent_sched, rng)


def better(a, b):
    if b is None:
        return True
    if a is None:
        return False
    if a["d_eff"] != b["d_eff"]:
        return (a["d_eff"] or -1) > (b["d_eff"] or -1)
    return (a["cnots"] or 10 ** 9) < (b["cnots"] or 10 ** 9)


def threshold_ler(d, rounds, p, sched, shots, seed):
    import stim
    import numpy as np
    c = build_memory(d, rounds, p, sched)
    sampler = c.compile_sampler(seed=seed)
    m = sampler.sample(shots)
    conv = c.compile_m2d_converter()
    _, obs = conv.convert(measurements=m, separate_observables=True)
    o = np.asarray(obs, dtype=float).ravel()
    ler = float(o.mean())
    se = float(math.sqrt(ler * (1.0 - ler) / o.size)) if o.size else None
    return {"ler": ler, "se": se, "shots": int(o.size)}


def grad_ok(rows):
    vals = [r["ler"] for r in rows]
    return (len(vals) == 3 and all(v is not None for v in vals) and
            vals[0] < vals[1] < vals[2])


def bracket_events_from_circuit(d, sched):
    data, stabs, _ = layout(d)
    ndata = len(data)
    nstab = len(stabs)
    synd_of = {}
    flag_of = {}
    q = ndata
    for s in range(nstab):
        synd_of[s] = q
        q += 1
        _, want_flag = sched[s]
        if want_flag:
            flag_of[s] = q
            q += 1
    support_of = {}
    for s, (_, pts, _) in enumerate(stabs):
        support_of[s] = set(pts)
    c = build_memory(d, ROUNDS, 0.0, sched)
    pre_meas = []
    for l in str(c).splitlines():
        parts = l.split()
        if parts[0] in ("M", "MX"):
            break
        pre_meas.append(parts)
    blocks = []
    cur = []
    for parts in pre_meas:
        if parts[0] == "TICK":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(parts)
    cnot_blocks = [b for b in blocks
                   if any(p[0] in ("CNOT", "CX") for p in b)]
    max_layer = 0
    for _, _, slots in stabs:
        max_layer = max(max_layer, max(slots))
    round0 = cnot_blocks[:max_layer + 1]
    events = {s: [] for s in range(nstab)}
    for block in round0:
        for parts in block:
            if parts[0] not in ("CNOT", "CX"):
                continue
            qs = [int(x) for x in parts[1:]]
            pairs = [qs[k:k + 2] for k in range(0, len(qs) - 1, 2)]
            for pair in pairs:
                if len(pair) != 2:
                    continue
                for s in range(nstab):
                    a = synd_of[s]
                    if s in flag_of and set(pair) == {a, flag_of[s]}:
                        if not any(e[0] == "data" for e in events[s]):
                            events[s].append(("open",))
                        else:
                            events[s].append(("close",))
                    elif ((pair[0] == a and pair[1] in support_of[s]) or
                            (pair[1] == a and pair[0] in support_of[s])):
                        events[s].append(("data",))
    return events


def is_full_bracket(events):
    for s, evs in events.items():
        kinds = [e[0] for e in evs]
        if "open" not in kinds or "close" not in kinds:
            return False
        if kinds[0] != "open" or kinds[-1] != "close":
            return False
    return True


def is_middle_bracket(events):
    for s, evs in events.items():
        kinds = [e[0] for e in evs]
        if "open" in kinds and "close" in kinds:
            first_data = kinds.index("data") if "data" in kinds else None
            if first_data is not None and kinds.index("open") > first_data:
                return True
    return False


def weight_histogram(stabs):
    hist = {}
    for _, pts, _ in stabs:
        hist[len(pts)] = hist.get(len(pts), 0) + 1
    return hist


def max_pair_support(stabs):
    best = 0
    for i in range(len(stabs)):
        for j in range(i + 1, len(stabs)):
            joint = set(stabs[i][1]) | set(stabs[j][1])
            if len(joint) > best:
                best = len(joint)
    return best


def self_tests():
    out = {"ran": True, "failed": [], "checks": {}}
    try:
        data3, stabs3, _ = layout(3)
        data5, stabs5, _ = layout(5)
        data7, stabs7, _ = layout(7)
        if len(stabs3) != 8 or len(data3) != 9:
            out["failed"].append("layout-counts-d3")
        if len(stabs5) != 24 or len(data5) != 25:
            out["failed"].append("layout-counts-d5")
        if len(stabs7) != 48 or len(data7) != 49:
            out["failed"].append("layout-counts-d7")
        out["checks"]["layout"] = {"d3": (len(data3), len(stabs3)),
                                   "d5": (len(data5), len(stabs5)),
                                   "d7": (len(data7), len(stabs7))}
        for tag, stabs in (("d3", stabs3), ("d5", stabs5),
                           ("d7", stabs7)):
            for i in range(len(stabs)):
                for j in range(i + 1, len(stabs)):
                    (t1, p1, _), (t2, p2, _) = stabs[i], stabs[j]
                    if t1 != t2 and len(set(p1) & set(p2)) % 2 == 1:
                        out["failed"].append("commute-%s-%d-%d"
                                            % (tag, i, j))
        out["checks"]["commute"] = True
        sched3 = canonical_schedule(stabs3)
        r1 = evaluate(3, ROUNDS, P_NOISE, sched3)
        r2 = evaluate(3, ROUNDS, P_NOISE, sched3)
        if r1 != r2:
            out["failed"].append("determinism")
        if not r1["ok"] or r1["d_eff"] != 3:
            out["failed"].append("canonical-valid")
        if (r1["cnots"] != ANCHOR_CANON3_CNOTS or
                r1["ancillas"] != ANCHOR_CANON3_ANC):
            out["failed"].append("anchor-canonical-numbers")
        out["checks"]["anchor_canonical"] = {
            "cnots": r1["cnots"], "ancillas": r1["ancillas"],
            "d_eff": r1["d_eff"]}
        import random as _rnd
        rng = _rnd.Random(0)
        ords = []
        for typ, p, sl in stabs3:
            o = list(range(len(p)))
            rng.shuffle(o)
            ords.append((tuple(o), True))
        r3 = evaluate(3, ROUNDS, P_NOISE, ords)
        if r3.get("d_eff") is None and r3.get("why") is None:
            out["failed"].append("eval-shape")
        _, per_stab3 = transcribe_layers(3)
        stim_layers3 = _stim_layers(3)
        gen_ok = True
        for anc, items in per_stab3.items():
            for li, other in items:
                if li >= len(stim_layers3):
                    gen_ok = False
                    continue
                layer = stim_layers3[li]
                if ((anc, other) not in layer and
                        (other, anc) not in layer):
                    gen_ok = False
        hand_differs = False
        for anc, items in per_stab3.items():
            true_slots = sorted(li for (li, _) in items)
            if true_slots != list(range(len(items))):
                hand_differs = True
        if not gen_ok:
            out["failed"].append("transcribe-fidelity")
        if not hand_differs:
            out["failed"].append("hand-tiling-differs")
        out["checks"]["transcribe"] = {"fidelity": bool(gen_ok),
                                       "hand_differs": bool(hand_differs)}
        canon_events = bracket_events_from_circuit(3, sched3)
        if not is_full_bracket(canon_events):
            out["failed"].append("bracket-full")
        if is_middle_bracket(canon_events):
            out["failed"].append("bracket-not-middle")
        synth_middle = {0: [("data",), ("open",), ("data",),
                            ("close",)],
                        1: [("open",), ("data",), ("close",)]}
        if is_full_bracket(synth_middle):
            out["failed"].append("bracket-predicate-vacuous")
        if not is_middle_bracket(synth_middle):
            out["failed"].append("bracket-predicate-blind")
        out["checks"]["bracket"] = True
        import stim as _stim
        c3 = build_memory(3, ROUNDS, P_NOISE, sched3)
        sampler = c3.compile_sampler(seed=0)
        m = sampler.sample(100)
        conv = c3.compile_m2d_converter()
        _, obs = conv.convert(measurements=m, separate_observables=True)
        if m.shape[1] != c3.num_measurements:
            out["failed"].append("sampler-is-measurements")
        if obs.shape[1] != c3.num_observables or c3.num_observables != 1:
            out["failed"].append("converter-is-detectors")
        if not c3.num_measurements > c3.num_observables:
            out["failed"].append("detector-vs-measurement")
        out["checks"]["detector_vs_measurement"] = {
            "n_measurements": int(c3.num_measurements),
            "n_observables": int(c3.num_observables)}
        if not grad_ok([{"ler": 0.01}, {"ler": 0.05}, {"ler": 0.10}]):
            out["failed"].append("grad-positive-control")
        if grad_ok([{"ler": 0.05}, {"ler": 0.05}, {"ler": 0.10}]):
            out["failed"].append("grad-flat-control")
        if grad_ok([{"ler": 0.10}, {"ler": 0.05}, {"ler": 0.01}]):
            out["failed"].append("grad-decreasing-control")
        if grad_ok([{"ler": 0.01}, {"ler": None}, {"ler": 0.10}]):
            out["failed"].append("grad-none-control")
        if better({"d_eff": None, "cnots": None}, None) is not True:
            out["failed"].append("repair-better-none")
        if better({"d_eff": 3, "cnots": 72},
                  {"d_eff": 3, "cnots": 120}) is not True:
            out["failed"].append("repair-better-tiebreak")
        if better({"d_eff": 2, "cnots": 10},
                  {"d_eff": 3, "cnots": 120}) is not False:
            out["failed"].append("repair-better-deff")
        rng_a = _rnd.Random(1234)
        frozen_parent = [s for s in sched3]
        key_before = sched_key(frozen_parent)
        _ = mutate_single(stabs3, frozen_parent, rng_a)
        if sched_key(frozen_parent) != key_before:
            out["failed"].append("aliasing-single")
        rng_b = _rnd.Random(1234)
        key_before_b = sched_key(frozen_parent)
        _ = pair_mutate(stabs3, frozen_parent, rng_b)
        if sched_key(frozen_parent) != key_before_b:
            out["failed"].append("aliasing-pair")
        rng_c = _rnd.Random(1234)
        key_before_c = sched_key(frozen_parent)
        _ = mutate_wide(stabs3, frozen_parent, rng_c)
        if sched_key(frozen_parent) != key_before_c:
            out["failed"].append("aliasing-wide")
        saw_two = False
        for probe_seed in range(20):
            probe_rng = _rnd.Random(probe_seed)
            probe_child = pair_mutate(stabs3, frozen_parent, probe_rng)
            probe_ndiff = sum(1 for a, b in zip(sched_key(frozen_parent),
                                               sched_key(probe_child))
                              if a != b)
            if probe_ndiff > 2:
                out["failed"].append("pair-moves-too-many-sites")
                break
            if probe_ndiff == 2:
                saw_two = True
        if not saw_two:
            out["failed"].append("pair-moves-two-sites")
        out["checks"]["aliasing"] = True
        maxsup5 = max_pair_support(stabs5)
        maxsup7 = max_pair_support(stabs7)
        if maxsup5 < 6 or maxsup7 < 6:
            out["failed"].append("pair-support-6plus")
        out["checks"]["pair_support"] = {"d5": maxsup5, "d7": maxsup7}
        out["checks"]["weights"] = {"d3": weight_histogram(stabs3),
                                    "d5": weight_histogram(stabs5),
                                    "d7": weight_histogram(stabs7)}
        if 4 not in weight_histogram(stabs5):
            out["failed"].append("weights-bulk-4")
        probe_rng = _rnd.Random(99)
        bad_start = random_schedule(stabs3, probe_rng)
        bad_ev = {"ok": False, "why": "forced-invalid", "d_eff": None,
                  "cnots": None, "ancillas": None}
        rep_rec, rep_stopped = greedy_search(
            stabs3, 3, bad_start, bad_ev, sched3, r1, 4, probe_rng,
            None, False)
        if rep_rec.get("fallback_from") != "canonical-fallback":
            out["failed"].append("repair-greedy-fallback")
        if rep_stopped is not False:
            out["failed"].append("repair-greedy-stopped")
        if sched_key(bad_start) != sched_key(
                random_schedule(stabs3, _rnd.Random(99))):
            out["failed"].append("repair-greedy-aliasing")
        out["checks"]["repair"] = True
    except Exception as ex:
        out["failed"].append("raise: %r" % ex)
    return out


def _stim_layers(d):
    import stim
    gen = stim.Circuit.generated("surface_code:rotated_memory_x",
                                 distance=d, rounds=1,
                                 after_clifford_depolarization=0.0)
    layers = []
    cur = []
    in_cnot = False
    for l in str(gen).splitlines():
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
    return layers


def run_random(stabs, d, n_per_seed, salt, stop, skipped, wide):
    import random
    batches = []
    arm_best = None
    arm_sched = None
    stopped_any = False
    for seed in SEEDS:
        if stop is not None and stop():
            stopped_any = True
            skipped.append({"what": "random-d%d-seed-%d" % (d, seed),
                            "reason": "wall-guard", "iters_done": 0,
                            "n_evaluated": n_per_seed, "stopped": True})
            continue
        rng = random.Random(int(seed * 10007 + salt) % (2 ** 63 - 1))
        n_valid = 0
        n_evaluated = 0
        local_best = None
        local_sched = None
        for k in range(n_per_seed):
            if stop is not None and stop():
                break
            cand_sched = random_schedule(stabs, rng)
            ev = evaluate(d, ROUNDS, P_NOISE, cand_sched)
            n_evaluated += 1
            if ev["ok"] and ev["d_eff"] == d:
                n_valid += 1
            if ev["ok"] and better(ev, local_best):
                local_best = ev
                local_sched = sched_key(cand_sched)
            if ev["ok"] and better(ev, arm_best):
                arm_best = ev
                arm_sched = sched_key(cand_sched)
        batch_stopped = bool(stop is not None and stop() and
                             n_evaluated < n_per_seed)
        if batch_stopped:
            stopped_any = True
        if n_evaluated < n_per_seed:
            skipped.append({"what": "random-d%d-seed-%d-truncated"
                                    % (d, seed),
                            "reason": "wall-guard",
                            "iters_done": n_evaluated,
                            "n_evaluated": n_per_seed,
                            "stopped": True})
        batches.append({"seed": seed, "n": n_per_seed,
                        "n_evaluated": n_evaluated,
                        "n_valid": n_valid, "best": local_best})
    return {"batches": batches, "best": arm_best, "best_sched": arm_sched,
            "stopped": stopped_any}


def greedy_search(stabs, d, start_sched, start_ev, canon_sched, canon_ev,
                  n_iters, rng, stop, wide):
    fallback_from = None
    if start_ev is None or not start_ev.get("ok"):
        cur_sched = [s for s in canon_sched]
        cur_ev = dict(canon_ev) if canon_ev.get("ok") else None
        fallback_from = "canonical-fallback"
        if cur_ev is None:
            cur_sched = random_schedule(stabs, rng)
            cur_ev = evaluate(d, ROUNDS, P_NOISE, cur_sched)
            fallback_from = "random-fallback"
    else:
        cur_sched = [s for s in start_sched]
        cur_ev = dict(start_ev)
    mutate_fn = mutate_wide if wide else mutate_single
    iters_done = 0
    for _ in range(n_iters):
        if stop is not None and stop():
            break
        cand_sched = mutate_fn(stabs, cur_sched, rng)
        cand_ev = evaluate(d, ROUNDS, P_NOISE, cand_sched)
        iters_done += 1
        if cand_ev["ok"] and better(cand_ev, cur_ev):
            cur_sched = cand_sched
            cur_ev = cand_ev
    batch_stopped = bool(stop is not None and stop() and
                         iters_done < n_iters)
    rec = {"best": cur_ev, "best_sched": sched_key(cur_sched),
           "iters": n_iters, "iters_done": iters_done,
           "stopped": batch_stopped}
    if fallback_from is not None:
        rec["fallback_from"] = fallback_from
    return rec, batch_stopped


def run_greedy(stabs, d, canon_sched, canon_ev, n_iters, salt, stop,
               skipped, wide):
    import random
    runs = []
    arm_best = None
    arm_sched = None
    stopped_any = False
    for seed in SEEDS:
        if stop is not None and stop():
            stopped_any = True
            skipped.append({"what": "greedy-d%d-seed-%d" % (d, seed),
                            "reason": "wall-guard", "iters_done": 0,
                            "n_evaluated": n_iters, "stopped": True})
            continue
        rng = random.Random(int(seed * 10007 + salt) % (2 ** 63 - 1))
        rec, batch_stopped = greedy_search(
            stabs, d, canon_sched, canon_ev, canon_sched, canon_ev,
            n_iters, rng, stop, wide)
        if batch_stopped:
            stopped_any = True
        if rec["iters_done"] < n_iters:
            skipped.append({"what": "greedy-d%d-seed-%d-truncated"
                                    % (d, seed),
                            "reason": "wall-guard",
                            "iters_done": rec["iters_done"],
                            "n_evaluated": n_iters, "stopped": True})
        runs.append(dict(rec, seed=seed))
        if rec["best"] is not None and rec["best"].get("ok") and \
                better(rec["best"], arm_best):
            arm_best = rec["best"]
            arm_sched = rec["best_sched"]
    return {"runs": runs, "best": arm_best, "best_sched": arm_sched,
            "stopped": stopped_any}


def run_sa(stabs, d, n_iters, salt, np_salt, stop, skipped, wide):
    import random
    import numpy as _np
    runs = []
    arm_best = None
    arm_sched = None
    stopped_any = False
    for seed in SEEDS:
        if stop is not None and stop():
            stopped_any = True
            skipped.append({"what": "sa-d%d-seed-%d" % (d, seed),
                            "reason": "wall-guard", "iters_done": 0,
                            "n_evaluated": n_iters, "stopped": True})
            continue
        rng = random.Random(int(seed * 10007 + salt) % (2 ** 63 - 1))
        npg = _np.random.default_rng(
            (int(seed * 10007 + np_salt) % (2 ** 63 - 1)))
        cur_sched = random_schedule(stabs, rng)
        cur_ev = evaluate(d, ROUNDS, P_NOISE, cur_sched)
        top_sched, top_ev = cur_sched, cur_ev
        mutate_fn = mutate_wide if wide else mutate_single
        iters_done = 0
        for it in range(n_iters):
            if stop is not None and stop():
                break
            cand_sched = mutate_fn(stabs, cur_sched, rng)
            cand_ev = evaluate(d, ROUNDS, P_NOISE, cand_sched)
            iters_done += 1
            temp = SA_T0 * (SA_ALPHA ** it)
            accept = False
            if cand_ev["ok"]:
                if cur_ev["ok"] and better(cand_ev, cur_ev):
                    accept = True
                elif temp > 0 and cur_ev["ok"]:
                    cur_score = (cur_ev["d_eff"], -cur_ev["cnots"])
                    cand_score = (cand_ev["d_eff"], -cand_ev["cnots"])
                    if float(npg.random()) < math.exp(
                            min(0.0, (cand_score[0] - cur_score[0]) * 2.0 +
                                (cand_score[1] - cur_score[1]) / 200.0)
                            / temp):
                        accept = True
                elif not cur_ev["ok"]:
                    accept = True
            if accept:
                cur_sched, cur_ev = cand_sched, cand_ev
                if better(cur_ev, top_ev):
                    top_sched, top_ev = cur_sched, cur_ev
            if top_ev["ok"] and better(top_ev, arm_best):
                arm_best = dict(top_ev)
                arm_sched = sched_key(top_sched)
        batch_stopped = bool(stop is not None and stop() and
                             iters_done < n_iters)
        if batch_stopped:
            stopped_any = True
        if iters_done < n_iters:
            skipped.append({"what": "sa-d%d-seed-%d-truncated" % (d, seed),
                            "reason": "wall-guard",
                            "iters_done": iters_done,
                            "n_evaluated": n_iters, "stopped": True})
        runs.append({"seed": seed, "best": top_ev, "iters": n_iters,
                     "iters_done": iters_done, "stopped": batch_stopped})
    return {"runs": runs, "best": arm_best, "best_sched": arm_sched,
            "stopped": stopped_any}


def run_exact_d3(stabs, stop, skipped):
    exact_best = None
    exact_n = 0
    exact_sched = None
    total = 1 << len(stabs)
    stopped = False
    if stop is not None and stop():
        stopped = True
        skipped.append({"what": "exact-remaining", "reason": "wall-guard",
                        "iters_done": 0, "n_evaluated": total,
                        "stopped": True})
    else:
        for mask in range(total):
            if stop is not None and stop():
                stopped = True
                skipped.append({"what": "exact-remaining",
                                "reason": "wall-guard",
                                "iters_done": exact_n,
                                "n_evaluated": total, "stopped": True})
                break
            cand_sched = []
            for s in range(len(stabs)):
                n = len(stabs[s][1])
                cand_sched.append((tuple(range(n)),
                                   bool(mask & (1 << s))))
            ev = evaluate(3, ROUNDS, P_NOISE, cand_sched)
            exact_n += 1
            if ev["ok"] and better(ev, exact_best):
                exact_best = ev
                exact_sched = sched_key(cand_sched)
    return {"n_evaluated": exact_n, "total": total, "best": exact_best,
            "best_sched": exact_sched, "solved": exact_n == total,
            "stopped": stopped}


def run_enum_d5(stabs, stop, skipped):
    enum_status = "cap-hit"
    enum_n = 0
    stopped = False
    if stop is not None and stop():
        stopped = True
        enum_status = "skipped-guard"
        skipped.append({"what": "enum-d5-remaining",
                        "reason": "wall-guard", "iters_done": 0,
                        "n_evaluated": ENUM_CAP_EVALS, "stopped": True})
    else:
        per_opts = [all_options(len(pts)) for _, pts, _ in stabs]
        idx = [0] * len(stabs)
        while True:
            if stop is not None and stop():
                enum_status = "stopped-guard"
                stopped = True
                skipped.append({"what": "enum-d5-remaining",
                                "reason": "wall-guard",
                                "iters_done": enum_n,
                                "n_evaluated": ENUM_CAP_EVALS,
                                "stopped": True})
                break
            if enum_n >= ENUM_CAP_EVALS:
                break
            cand_sched = [per_opts[s][idx[s] % len(per_opts[s])]
                          for s in range(len(stabs))]
            evaluate(5, ROUNDS, P_NOISE, cand_sched)
            enum_n += 1
            idx[0] += 1
            for s in range(len(stabs)):
                if idx[s] >= len(per_opts[s]):
                    idx[s] = 0
                    if s + 1 < len(stabs):
                        idx[s + 1] += 1
                else:
                    break
            else:
                enum_status = "solved"
                break
    return {"status": enum_status, "n_evaluated": enum_n,
            "cap": ENUM_CAP_EVALS, "stopped": stopped}


def run_threshold(d, sched_rows, tag, stop, skipped):
    out = {}
    stopped_any = False
    for row_name, row_sched in sched_rows:
        out[row_name] = []
        for pi, pp in enumerate(P_GRID):
            if stop is not None and stop():
                stopped_any = True
                skipped.append({"what": "threshold-%s-%s-%.4f"
                                        % (tag, row_name, pp),
                                "reason": "wall-guard",
                                "iters_done": len(out[row_name]),
                                "n_evaluated": len(P_GRID),
                                "stopped": True})
                out[row_name].append({"p": pp, "ler": None, "se": None})
                continue
            rec = threshold_ler(d, ROUNDS, pp, row_sched, N_SHOTS,
                                1000 + pi)
            out[row_name].append({"p": pp, **rec})
    return out, stopped_any


def _recon_sched(key):
    return [(tuple(int(x) for x in o), bool(f)) for (o, f) in key]


def main():
    import argparse
    import os
    import random
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

    def stop():
        return over()

    skipped = []
    cells = {}
    gate3 = {"exact": {}, "enum_d5": {}}
    gate2 = {}
    selftest = self_tests()
    with open(os.path.join(witdir, "selftest.json"), "w") as f:
        json.dump(selftest, f, indent=1, default=str)

    def checkpoint(tag, payload):
        try:
            with open(os.path.join(witdir, "checkpoint-%s.json" % tag),
                      "w") as f:
                json.dump({"tag": tag, "wall_s": elapsed(),
                           "n_cells": len(cells),
                           "n_skipped": len(skipped),
                           "verdict": "unresolved-with-reason: partial "
                                      "checkpoint", **payload},
                          f, indent=1, default=str)
        except Exception:
            pass

    layouts = {}
    for d in D_SIZES:
        layouts[d] = layout(d)
    checkpoint("layout", {"sizes": {str(d): (len(layouts[d][0]),
                                             len(layouts[d][1]))
                                    for d in D_SIZES}})

    canon = {}
    canon_ev = {}
    transfer = {}
    transfer_ev = {}
    for d in D_SIZES:
        _, stabs, _ = layouts[d]
        canon[d] = canonical_schedule(stabs)
        canon_ev[d] = evaluate(d, ROUNDS, P_NOISE, canon[d])
        cells["%d/canonical/fixed" % d] = dict(canon_ev[d])
        transfer[d] = transfer_schedule(stabs)
        transfer_ev[d] = evaluate(d, ROUNDS, P_NOISE, transfer[d])
        cells["%d/transfer/fixed" % d] = dict(transfer_ev[d])
    checkpoint("fixed", {"canon": {str(d): canon_ev[d] for d in D_SIZES},
                         "transfer": {str(d): transfer_ev[d]
                                      for d in D_SIZES}})

    per_size_best = {}
    per_size_best_sched = {}
    arm_best = {}
    for d in D_SIZES:
        per_size_best[d] = dict(canon_ev[d])
        per_size_best_sched[d] = sched_key(canon[d])
        arm_best[d] = {}

    def note_arm(d, arm, best, sched):
        if best is not None and best.get("ok"):
            arm_best[d][arm] = {"d_eff": best.get("d_eff"),
                               "cnots": best.get("cnots"),
                               "ancillas": best.get("ancillas")}
            if better(best, per_size_best[d]):
                per_size_best[d] = dict(best)
                per_size_best_sched[d] = sched

    r3 = run_random(layouts[3][1], 3, N_RANDOM_SEED_D3, SALT_D3_RANDOM,
                    stop, skipped, False)
    for b in r3["batches"]:
        cells["3/random/%d" % b["seed"]] = {
            "n_valid": b["n_valid"], "n": b["n"],
            "n_evaluated": b["n_evaluated"],
            "best_cnots": (b["best"] or {}).get("cnots"),
            "best_d_eff": (b["best"] or {}).get("d_eff")}
    note_arm(3, "random", r3["best"], r3["best_sched"])
    checkpoint("d3-random", {"batches": len(r3["batches"])})

    g3 = run_greedy(layouts[3][1], 3, canon[3], canon_ev[3],
                    GREEDY_ITERS_D3, SALT_D3_GREEDY, stop, skipped, False)
    for r in g3["runs"]:
        cells["3/greedy/%d" % r["seed"]] = {
            "d_eff": r["best"]["d_eff"] if r["best"] else None,
            "cnots": r["best"]["cnots"] if r["best"] else None,
            "iters_done": r["iters_done"], "iters": r["iters"],
            "stopped": r["stopped"]}
    note_arm(3, "greedy", g3["best"], g3["best_sched"])
    checkpoint("d3-greedy", {"runs": len(g3["runs"])})

    s3 = run_sa(layouts[3][1], 3, SA_ITERS_D3, SALT_D3_SA, SALT_D3_SA_NP,
                stop, skipped, False)
    for r in s3["runs"]:
        cells["3/sa/%d" % r["seed"]] = {
            "d_eff": r["best"]["d_eff"] if r["best"] else None,
            "cnots": r["best"]["cnots"] if r["best"] else None,
            "iters_done": r["iters_done"], "iters": r["iters"],
            "stopped": r["stopped"]}
    note_arm(3, "sa", s3["best"], s3["best_sched"])
    checkpoint("d3-sa", {"runs": len(s3["runs"])})
    note_arm(3, "transfer", transfer_ev[3], sched_key(transfer[3]))

    exact = run_exact_d3(layouts[3][1], stop, skipped)
    gate3["exact"] = {"n_evaluated": exact["n_evaluated"],
                      "total": exact["total"], "best": exact["best"],
                      "solved": exact["solved"],
                      "stopped": exact["stopped"]}
    note_arm(3, "exact", exact["best"], exact["best_sched"])
    checkpoint("exact", {"gate3exact": gate3["exact"]})

    r5 = run_random(layouts[5][1], 5, N_RANDOM_SEED_D5, SALT_D5_RANDOM,
                    stop, skipped, True)
    for b in r5["batches"]:
        cells["5/random/%d" % b["seed"]] = {
            "n_valid": b["n_valid"], "n": b["n"],
            "n_evaluated": b["n_evaluated"],
            "best_cnots": (b["best"] or {}).get("cnots"),
            "best_d_eff": (b["best"] or {}).get("d_eff")}
    note_arm(5, "random", r5["best"], r5["best_sched"])
    checkpoint("d5-random", {"batches": len(r5["batches"])})

    g5 = run_greedy(layouts[5][1], 5, canon[5], canon_ev[5],
                    GREEDY_ITERS_D5, SALT_D5_GREEDY, stop, skipped, True)
    for r in g5["runs"]:
        cells["5/greedy/%d" % r["seed"]] = {
            "d_eff": r["best"]["d_eff"] if r["best"] else None,
            "cnots": r["best"]["cnots"] if r["best"] else None,
            "iters_done": r["iters_done"], "iters": r["iters"],
            "stopped": r["stopped"]}
    note_arm(5, "greedy", g5["best"], g5["best_sched"])
    checkpoint("d5-greedy", {"runs": len(g5["runs"])})

    s5 = run_sa(layouts[5][1], 5, SA_ITERS_D5, SALT_D5_SA, SALT_D5_SA_NP,
                stop, skipped, True)
    for r in s5["runs"]:
        cells["5/sa/%d" % r["seed"]] = {
            "d_eff": r["best"]["d_eff"] if r["best"] else None,
            "cnots": r["best"]["cnots"] if r["best"] else None,
            "iters_done": r["iters_done"], "iters": r["iters"],
            "stopped": r["stopped"]}
    note_arm(5, "sa", s5["best"], s5["best_sched"])
    checkpoint("d5-sa", {"runs": len(s5["runs"])})
    note_arm(5, "transfer", transfer_ev[5], sched_key(transfer[5]))

    enum5 = run_enum_d5(layouts[5][1], stop, skipped)
    gate3["enum_d5"] = {"status": enum5["status"],
                       "n_evaluated": enum5["n_evaluated"],
                       "cap": enum5["cap"], "stopped": enum5["stopped"]}
    checkpoint("enum", {"gate3enum": gate3["enum_d5"]})

    r7 = run_random(layouts[7][1], 7, N_RANDOM_SEED_D7, SALT_D7_RANDOM,
                    stop, skipped, True)
    for b in r7["batches"]:
        cells["7/random/%d" % b["seed"]] = {
            "n_valid": b["n_valid"], "n": b["n"],
            "n_evaluated": b["n_evaluated"],
            "best_cnots": (b["best"] or {}).get("cnots"),
            "best_d_eff": (b["best"] or {}).get("d_eff")}
    note_arm(7, "random", r7["best"], r7["best_sched"])
    checkpoint("d7-random", {"batches": len(r7["batches"])})

    g7 = run_greedy(layouts[7][1], 7, transfer[7], transfer_ev[7],
                    GREEDY_ITERS_D7, SALT_D7_GREEDY, stop, skipped, True)
    for r in g7["runs"]:
        cells["7/greedy/%d" % r["seed"]] = {
            "d_eff": r["best"]["d_eff"] if r["best"] else None,
            "cnots": r["best"]["cnots"] if r["best"] else None,
            "iters_done": r["iters_done"], "iters": r["iters"],
            "stopped": r["stopped"]}
    note_arm(7, "greedy", g7["best"], g7["best_sched"])
    checkpoint("d7-greedy", {"runs": len(g7["runs"])})

    s7 = run_sa(layouts[7][1], 7, SA_ITERS_D7, SALT_D7_SA, SALT_D7_SA_NP,
                stop, skipped, True)
    for r in s7["runs"]:
        cells["7/sa/%d" % r["seed"]] = {
            "d_eff": r["best"]["d_eff"] if r["best"] else None,
            "cnots": r["best"]["cnots"] if r["best"] else None,
            "iters_done": r["iters_done"], "iters": r["iters"],
            "stopped": r["stopped"]}
    note_arm(7, "sa", s7["best"], s7["best_sched"])
    checkpoint("d7-sa", {"runs": len(s7["runs"])})
    note_arm(7, "transfer", transfer_ev[7], sched_key(transfer[7]))

    for d in D_SIZES:
        best_sched_obj = _recon_sched(per_size_best_sched[d])
        rows = run_threshold(d, [("canonical", canon[d]),
                                 ("best", best_sched_obj)], "d%d" % d,
                             stop, skipped)
        gate2["d%d" % d] = rows[0]
        checkpoint("thr-d%d" % d, {"gate2d": gate2["d%d" % d]})

    anchor_greedy_hits = 0
    for seed in SEEDS:
        rec = cells.get("3/greedy/%d" % seed, {})
        if rec.get("d_eff") == 3 and rec.get("cnots") == \
                ANCHOR_BEST3_CNOTS:
            anchor_greedy_hits += 1
    anchor_ok = bool(
        cells["3/canonical/fixed"].get("ok") and
        cells["3/canonical/fixed"].get("d_eff") == 3 and
        cells["3/canonical/fixed"].get("cnots") == ANCHOR_CANON3_CNOTS and
        cells["3/canonical/fixed"].get("ancillas") == ANCHOR_CANON3_ANC and
        gate3["exact"].get("solved") and
        gate3["exact"].get("total") == EXACT_TOTAL_D3 and
        (gate3["exact"].get("best") or {}).get("d_eff") == 3 and
        (gate3["exact"].get("best") or {}).get("cnots") ==
        ANCHOR_BEST3_CNOTS and
        anchor_greedy_hits >= ANCHOR_GREEDY3_HITS)
    selftest_ok = bool(selftest.get("ran")) and not selftest.get("failed") \
        and anchor_ok

    canon_valid = {}
    for d in D_SIZES:
        rec = cells["%d/canonical/fixed" % d]
        canon_valid[d] = bool(rec.get("ok") and rec.get("d_eff") == d)
    exact_valid = bool(gate3["exact"].get("best") and
                       gate3["exact"]["best"].get("d_eff") == 3)
    rand_frac = {}
    for d, batches in ((3, r3["batches"]), (5, r5["batches"]),
                       (7, r7["batches"])):
        fracs = [b["n_valid"] / b["n"] for b in batches if b["n"] > 0]
        rand_frac[d] = (sum(fracs) / len(fracs)) if fracs else 1.0
    g1_ok = bool(all(canon_valid[d] for d in D_SIZES) and exact_valid and
                 rand_frac[3] < 1.0 and anchor_ok)

    grad = {}
    for d in D_SIZES:
        rows = gate2["d%d" % d].get("canonical", [])
        grad[d] = grad_ok(rows)
    row_grad = {}
    for d in D_SIZES:
        for row_name, rows in gate2["d%d" % d].items():
            row_grad["%d/%s" % (d, row_name)] = grad_ok(rows)
    g2_ok = bool(all(grad[d] for d in D_SIZES))
    g3pass = bool(gate3["exact"].get("solved") and
                  gate3["enum_d5"].get("status") == "cap-hit")

    def cells_complete():
        for seed in SEEDS:
            rb = cells.get("3/random/%d" % seed, {})
            if rb.get("n_evaluated") != N_RANDOM_SEED_D3:
                return False
            gr = cells.get("3/greedy/%d" % seed, {})
            if gr.get("iters_done") != GREEDY_ITERS_D3:
                return False
            sr = cells.get("3/sa/%d" % seed, {})
            if sr.get("iters_done") != SA_ITERS_D3:
                return False
            rb5 = cells.get("5/random/%d" % seed, {})
            if rb5.get("n_evaluated") != N_RANDOM_SEED_D5:
                return False
            gr5 = cells.get("5/greedy/%d" % seed, {})
            if gr5.get("iters_done") != GREEDY_ITERS_D5:
                return False
            sr5 = cells.get("5/sa/%d" % seed, {})
            if sr5.get("iters_done") != SA_ITERS_D5:
                return False
            rb7 = cells.get("7/random/%d" % seed, {})
            if rb7.get("n_evaluated") != N_RANDOM_SEED_D7:
                return False
            gr7 = cells.get("7/greedy/%d" % seed, {})
            if gr7.get("iters_done") != GREEDY_ITERS_D7:
                return False
            sr7 = cells.get("7/sa/%d" % seed, {})
            if sr7.get("iters_done") != SA_ITERS_D7:
                return False
        if not gate3["exact"].get("solved"):
            return False
        if gate3["exact"].get("n_evaluated") != gate3["exact"].get("total"):
            return False
        enum = gate3["enum_d5"]
        enum_full = bool(
            (enum.get("status") == "cap-hit" and
             enum.get("n_evaluated") == ENUM_CAP_EVALS) or
            enum.get("status") == "solved")
        if not enum_full:
            return False
        for d in D_SIZES:
            for rows in gate2["d%d" % d].values():
                if len(rows) != 3:
                    return False
        return True

    complete = bool(cells_complete() and all(
        cells["%d/canonical/fixed" % d].get("ok") for d in D_SIZES))
    wall = elapsed()
    clean = len(skipped) == 0
    g4_ok = bool(complete and wall < WALL_LIMIT_S and clean)

    joint = {}
    for d in D_SIZES:
        joint[d] = {}
        for arm, rec in arm_best[d].items():
            joint[d][arm] = bool(
                rec.get("d_eff") == d and
                rec.get("cnots") is not None and
                cells["%d/canonical/fixed" % d].get("cnots") is not None and
                rec.get("cnots") <
                cells["%d/canonical/fixed" % d].get("cnots"))
    wins3 = sum(1 for v in joint[3].values() if v)
    wins5 = sum(1 for v in joint[5].values() if v)
    wins7 = sum(1 for v in joint[7].values() if v)
    pursue_d3 = bool(wins3 >= 1 and g1_ok and g2_ok and g3pass and g4_ok
                     and selftest_ok)
    extended_d7 = bool(pursue_d3 and wins7 >= 1)
    reject = bool(complete and all(canon_valid[d] for d in D_SIZES) and
                  wins3 == 0)
    if pursue_d3 and extended_d7:
        reason = "PURSUE-condition holds at d=3 AND d=7 transfer " \
            "preserves the overhead advantage (valid d_eff==7 schedule " \
            "with fewer CNOTs than canonical at d=7 + gradient + " \
            "d=5-class cap-hit + gates 1,2,3,4 + self-tests ok); " \
            "payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side."
    elif pursue_d3:
        reason = "PURSUE-condition holds d=3-bounded (found valid " \
            "d_eff==3 schedule with fewer CNOTs than canonical on d=3 " \
            "+ gates 1,2,3,4 + self-tests + anchor ok; d7 joint wins " \
            "%d); payload verdict stays unresolved-with-reason, " \
            "classification is coordinator-side." % wins7
    elif reject:
        reason = "REJECT-condition holds (complete cells, canonical " \
            "valid at all sizes, no joint win at d=3); payload verdict " \
            "stays unresolved-with-reason, classification is " \
            "coordinator-side."
    else:
        reason = "UNRESOLVED + %s (d3 joint wins=%d d5=%d d7=%d; g1=%s " \
            "g2=%s(grad d3 %s d5 %s d7 %s) g3=%s g4=%s selftest=%s " \
            "anchor=%s complete=%s skipped=%d)." % (
                NEXT_EXPERIMENT, wins3, wins5, wins7, g1_ok, g2_ok,
                grad[3], grad[5], grad[7], g3pass, g4_ok, selftest_ok,
                anchor_ok, complete, len(skipped))
    verdict_bits = {
        "gate1": {"pass": bool(g1_ok), "canonical_valid": {
            str(d): bool(canon_valid[d]) for d in D_SIZES},
            "exact_valid": bool(exact_valid),
            "random_valid_frac": dict(rand_frac),
            "anchor_ok": bool(anchor_ok),
            "anchor_greedy_hits": anchor_greedy_hits},
        "gate2": {"pass": bool(g2_ok), "grad_canonical": {
            str(d): bool(grad[d]) for d in D_SIZES},
            "row_gradients": {k: bool(v) for k, v in row_grad.items()},
            "d3": gate2["d3"], "d5": gate2["d5"], "d7": gate2["d7"]},
        "gate3": {"pass": bool(g3pass), "exact": gate3["exact"],
                  "enum_d5": gate3["enum_d5"]},
        "gate4": {"pass": bool(g4_ok), "complete": bool(complete),
                  "wall_sec": wall, "clean": bool(clean)},
        "acceptance": {"pursue_d3_bounded": bool(pursue_d3),
                       "extended_d7": bool(extended_d7),
                       "reject_condition": bool(reject),
                       "joint_wins": {str(d): {a: bool(v) for a, v in
                                               joint[d].items()}
                                      for d in D_SIZES},
                       "n_wins": {"3": wins3, "5": wins5, "7": wins7},
                       "best": {str(d): per_size_best[d]
                                for d in D_SIZES},
                       "selftest_ok": bool(selftest_ok),
                       "anchor_ok": bool(anchor_ok)},
        "reason": reason,
    }
    results = {
        "screen": "02",
        "verdict": "unresolved-with-reason: payload reports numbers "
                   "and gate evidence; classification is coordinator-side.",
        "design": {
            "model": "screen-authored schedule search on stim-"
                     "transcribed rotated-surface-code tiling "
                     "(stim 1.16.0 + stdlib + numpy only)",
            "distances": list(D_SIZES),
            "rounds": ROUNDS,
            "noise": {"depolarizing": P_NOISE, "meas_flip": P_NOISE,
                      "prep": "RX/R + DEPOLARIZE1",
                      "note": "DEPOLARIZE1 after each 1q gate, "
                              "DEPOLARIZE2 after each CNOT, X_ERROR(p) "
                              "after each measurement"},
            "seeds": list(SEEDS),
            "arms": {"canonical": "transcribed order + flags everywhere",
                     "transfer": "transcribed order + zero flags (d=3 "
                                 "exact-optimum pattern lifted to d=5/d=7)",
                     "random": "%d/%d/%d rollouts/seed at d=3/5/7" % (
                         N_RANDOM_SEED_D3, N_RANDOM_SEED_D5,
                         N_RANDOM_SEED_D7),
                     "greedy": "single-stab moves at d=3 from canonical "
                               "(%d iters/seed), single+pair moves at "
                               "d=5 from canonical (%d iters/seed) and "
                               "at d=7 from transfer (%d iters/seed)" % (
                                   GREEDY_ITERS_D3, GREEDY_ITERS_D5,
                                   GREEDY_ITERS_D7),
                     "sa": "single-stab moves at d=3 (%d iters/seed), "
                           "single+pair at d=5/d=7 (%d/%d iters/seed)" % (
                               SA_ITERS_D3, SA_ITERS_D5, SA_ITERS_D7),
                     "exact": "flag-subset enumeration 2^8=256 on d=3",
                     "enum_d5": "per-stab capped enumeration, cap %d" %
                                ENUM_CAP_EVALS},
            "schedule_space": "per stab: data-qubit to layer-slot "
                              "assignment (transcribed layer skeleton "
                              "fixed) x flag {0,1}, full-bracket flags; "
                              "wider neighborhoods via pair moves at "
                              "d>=5 spanning 6+ data qubits",
            "metrics": "d_eff via shortest_graphlike_error, then total "
                       "CNOTs at preserved d_eff; LER via compile_sampler "
                       "+ compile_m2d_converter(separate_observables=True)",
            "pareto": "PURSUE needs a valid (d_eff==d) schedule with "
                      "strictly fewer CNOTs than canonical at that size; "
                      "overhead-only wins without preserved distance do "
                      "not count; d=7 extension needs a d=7 joint win",
            "exact": "flag-subset enumeration solves d=3 (256/256); "
                     "per-stab enumeration must cap-hit on d=5-class",
        },
        "timing": {"wall_s": wall, "guards": {"wall_guard_s": WALL_GUARD_S,
                                              "limit_s": WALL_LIMIT_S}},
        "cells": cells,
        "gates": verdict_bits,
        "skipped": skipped,
    }
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)


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


def build_memory(d, rounds, p, sched):
    import stim
    data, stabs, logiset = layout(d)
    ndata = len(data)
    q = ndata
    synd = {}
    flag = {}
    for s in range(len(stabs)):
        synd[s] = q
        q += 1
        _, fl = sched[s]
        if fl:
            flag[s] = q
            q += 1
    c = stim.Circuit()
    for i in range(q):
        c.append("QUBIT_COORDS", [i], [])
    for dq in range(ndata):
        c.append("RX", [dq])
    if p:
        c.append("DEPOLARIZE1", list(range(ndata)), [p])
    c.append("TICK", [])
    nm = [0]
    synrec = {}
    flagrec = {}

    def meas1(qb, basis):
        if basis == "Z":
            c.append("M", [qb])
        else:
            c.append("MX", [qb])
        k = nm[0]
        nm[0] += 1
        if p:
            c.append("X_ERROR", [qb], [p])
        return k

    max_layer = 0
    for _, _, slots in stabs:
        max_layer = max(max_layer, max(slots))
    for r in range(rounds):
        for s, (typ, pts, slots) in enumerate(stabs):
            a = synd[s]
            c.append("RX" if typ == "X" else "R", [a])
            if p:
                c.append("DEPOLARIZE1", [a], [p])
            if s in flag:
                c.append("R", [flag[s]])
                if p:
                    c.append("DEPOLARIZE1", [flag[s]], [p])
        c.append("TICK", [])
        for li in range(max_layer + 1):
            for s, (typ, pts, slots) in enumerate(stabs):
                if li not in slots:
                    continue
                a = synd[s]
                order, fl = sched[s]
                k = slots.index(li)
                dq = pts[order[k]]
                if fl and k == 0:
                    c.append("CNOT", [a, flag[s]])
                    if p:
                        c.append("DEPOLARIZE2", [a, flag[s]], [p])
                if typ == "Z":
                    c.append("CNOT", [dq, a])
                else:
                    c.append("CNOT", [a, dq])
                if p:
                    c.append("DEPOLARIZE2", [dq, a], [p])
                if fl and k + 1 == len(pts):
                    c.append("CNOT", [a, flag[s]])
                    if p:
                        c.append("DEPOLARIZE2", [a, flag[s]], [p])
            c.append("TICK", [])
        for s, (typ, pts, slots) in enumerate(stabs):
            a = synd[s]
            synrec[(s, r)] = meas1(a, "X" if typ == "X" else "Z")
            if s in flag:
                flagrec[(s, r)] = meas1(flag[s], "Z")
        c.append("TICK", [])
    datarec = {}
    for dq in range(ndata):
        datarec[dq] = meas1(dq, "X")
    c.append("TICK", [])
    total = nm[0]

    def rec(k):
        return stim.target_rec(k - total)

    for s, (typ, pts, slots) in enumerate(stabs):
        for r in range(rounds):
            if r == 0 and typ == "Z":
                continue
            if r == 0:
                c.append("DETECTOR", [rec(synrec[(s, 0)])], [])
            else:
                c.append("DETECTOR",
                         [rec(synrec[(s, r)]), rec(synrec[(s, r - 1)])], [])
        if typ == "X":
            c.append("DETECTOR",
                     [rec(datarec[dq]) for dq in pts] +
                     [rec(synrec[(s, rounds - 1)])], [])
    for s in range(len(stabs)):
        for r in range(2, rounds):
            if (s, r) in flagrec:
                c.append("DETECTOR",
                         [rec(flagrec[(s, r)]), rec(flagrec[(s, r - 1)])],
                         [])
    obs = [rec(datarec[dq]) for dq in logiset]
    c.append("OBSERVABLE_INCLUDE", obs, [0])
    return c


if __name__ == "__main__":
    main()
