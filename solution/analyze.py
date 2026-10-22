"""Model-based analysis of one measured run."""

import json
import math
import sys

SKIP = "__SKIP__"

ALPHA_BOUNDS = (1e-9, 5e-5)
R_BOUNDS = (1e-7, 5e-2)


def load_run(run_dir):
    import csv
    from pathlib import Path

    root = Path(run_dir)
    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))

    def read(name):
        t, v = [], []
        with (root / name).open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                t.append(float(row["t_s"]))
                v.append(float(list(row.values())[1]))
        return t, v

    power_t, power_q = read("power.csv")
    temp_t, temp_c = read("temp.csv")
    sample = meta["sample"]
    block = meta["block"]
    return {
        "meta": meta,
        "power_t": power_t,
        "power_q": power_q,
        "time": temp_t,
        "temp": temp_c,
        "thickness": float(sample["thickness_m"]),
        "rho_cp": float(sample["density_kg_m3"]) * float(sample["cp_j_kg_k"]),
        "block_c": float(block["thickness_m"])
        * float(block["density_kg_m3"])
        * float(block["cp_j_kg_k"]),
        "h_back": float(meta.get("back_heat_transfer_w_m2_k", 0.0)),
        "t_amb": float(meta["ambient_c"]),
    }


def _interp(t, ts, vs):
    if t < ts[0] + 1e-12:
        return vs[0]
    if t > ts[-1] - 1e-12:
        return vs[-1]
    lo, hi = 0, len(ts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ts[mid] < t + 1e-12:
            lo = mid
        else:
            hi = mid
    span = ts[hi] - ts[lo]
    if span < 1e-12:
        return vs[hi]
    w = (t - ts[lo]) / span
    return vs[lo] * (1.0 - w) + vs[hi] * w


def _solve_tridiagonal(lower, diag, upper, rhs):
    n = len(diag)
    c = [0.0] * n
    d = [0.0] * n
    c[0] = upper[0] / diag[0] if n > 1 else 0.0
    d[0] = rhs[0] / diag[0]
    for i in range(1, n):
        den = diag[i] - lower[i - 1] * c[i - 1]
        c[i] = upper[i] / den if i < n - 1 else 0.0
        d[i] = (rhs[i] - lower[i - 1] * d[i - 1]) / den
    x = [0.0] * n
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


def simulate(alpha, r_contact, run, power_t, power_q, nodes=61, dt=0.5):
    thickness = run["thickness"]
    rho_cp = run["rho_cp"]
    block_c = run["block_c"]
    h_back = run["h_back"]
    t_amb = run["t_amb"]
    times = run["time"]

    dx = thickness / (nodes - 1)
    n = nodes + 1

    cap = [0.0] * n
    cap[0] = block_c
    for i in range(1, n):
        cap[i] = rho_cp * dx * 0.5
    for i in range(2, n - 1):
        cap[i] = rho_cp * dx

    kinv = 1.0 / r_contact
    g = alpha * rho_cp / dx

    a_diag = [0.0] * n
    a_lower = [0.0] * (n - 1)
    a_upper = [0.0] * (n - 1)
    a_diag[0] += kinv
    a_upper[0] -= kinv
    a_lower[0] -= kinv
    a_diag[1] += kinv
    for i in range(1, nodes):
        a_diag[i] += g
        a_diag[i + 1] += g
        a_upper[i] -= g
        a_lower[i] -= g
    a_diag[-1] += h_back

    inv_dt = 1.0 / dt
    lhs_diag = [cap[i] * inv_dt + 0.5 * a_diag[i] for i in range(n)]
    lhs_lower = [0.5 * v for v in a_lower]
    lhs_upper = [0.5 * v for v in a_upper]
    rhs_diag = [cap[i] * inv_dt - 0.5 * a_diag[i] for i in range(n)]
    rhs_lower = [-0.5 * v for v in a_lower]
    rhs_upper = [-0.5 * v for v in a_upper]

    temp = [t_amb] * n
    out = [t_amb] * len(times)

    b_prev = [0.0] * n
    b_prev[-1] = h_back * t_amb
    b_prev[0] = _interp(0.0, power_t, power_q)

    index = 1
    steps = int(times[-1] / dt + 1e-9)
    for k in range(1, steps + 1):
        t = k * dt
        q = _interp(t, power_t, power_q)
        rhs = [0.0] * n
        for i in range(n):
            value = rhs_diag[i] * temp[i]
            if i > 0:
                value += rhs_lower[i - 1] * temp[i - 1]
            if i < n - 1:
                value += rhs_upper[i] * temp[i + 1]
            rhs[i] = value
        rhs[0] += 0.5 * (b_prev[0] + q)
        rhs[-1] += 0.5 * (b_prev[-1] + h_back * t_amb)
        temp = _solve_tridiagonal(lhs_lower, lhs_diag, lhs_upper, rhs)
        b_prev = [0.0] * n
        b_prev[-1] = h_back * t_amb
        b_prev[0] = q
        while index < len(times) and times[index] < t + 1e-9 + 1e-12:
            out[index] = temp[-1]
            index += 1
    while index < len(times):
        out[index] = temp[-1]
        index += 1
    return out


def _keep_mask(temp):
    """去掉单点尖刺：二阶差分明显大于中位水平的点连同左右邻点。"""
    n = len(temp)
    if n < 5:
        return list(range(n))
    d2 = [abs(temp[i + 1] - 2.0 * temp[i] + temp[i - 1]) for i in range(1, n - 1)]
    ordered = sorted(d2)
    med = ordered[len(ordered) // 2]
    threshold = max(8.0 * med, 0.15)
    bad = set()
    for j, value in enumerate(d2):
        if value > threshold:
            i = j + 1
            bad.update((i - 1, i, i + 1))
    return [i for i in range(n) if i not in bad]


def _residual(p, run, power_t, power_q, fixed, nodes, dt):
    if fixed is not None and fixed[0] == "r":
        alpha, r_contact = math.exp(p[0]), fixed[1]
    elif fixed is not None and fixed[0] == "alpha":
        alpha, r_contact = fixed[1], math.exp(p[0])
    else:
        alpha, r_contact = math.exp(p[0]), math.exp(p[1])
    model = simulate(alpha, r_contact, run, power_t, power_q, nodes=nodes, dt=dt)
    keep = run["keep"]
    return [model[i] - run["temp"][i] for i in keep]


def refine(run, power_t, power_q, alpha0, r0, fix_r=None, fix_alpha=None, dt=1.0, nodes=31):
    lo_a, hi_a = math.log(ALPHA_BOUNDS[0]), math.log(ALPHA_BOUNDS[1])
    lo_r, hi_r = math.log(R_BOUNDS[0]), math.log(R_BOUNDS[1])
    if fix_r is not None:
        fixed = ("r", fix_r)
        p = [math.log(alpha0)]
        lo, hi = [lo_a], [hi_a]
    elif fix_alpha is not None:
        fixed = ("alpha", fix_alpha)
        p = [math.log(r0)]
        lo, hi = [lo_r], [hi_r]
    else:
        fixed = None
        p = [math.log(alpha0), math.log(r0)]
        lo, hi = [lo_a, lo_r], [hi_a, hi_r]

    residual = _residual(p, run, power_t, power_q, fixed, nodes, dt)
    cost = sum(v * v for v in residual)
    lam = 1e-3
    for _ in range(60):
        jac = []
        for j in range(len(p)):
            probe = list(p)
            probe[j] += 1e-5
            rj = _residual(probe, run, power_t, power_q, fixed, nodes, dt)
            jac.append([(rj[i] - residual[i]) / 1e-5 for i in range(len(residual))])
        if len(p) == 1:
            a11 = sum(v * v for v in jac[0])
            b1 = sum(jac[0][i] * residual[i] for i in range(len(residual)))
            dp = [-b1 / (a11 * (1.0 + lam) + 1e-30)]
        else:
            a11 = sum(v * v for v in jac[0])
            a22 = sum(v * v for v in jac[1])
            a12 = sum(jac[0][i] * jac[1][i] for i in range(len(residual)))
            b1 = sum(jac[0][i] * residual[i] for i in range(len(residual)))
            b2 = sum(jac[1][i] * residual[i] for i in range(len(residual)))
            d1 = a11 * (1.0 + lam) + 1e-30
            d2 = a22 * (1.0 + lam) + 1e-30
            det = d1 * d2 - a12 * a12
            if abs(det) < 1e-30:
                break
            dp = [(-d2 * b1 + a12 * b2) / det, (-d1 * b2 + a12 * b1) / det]
        new_p = [min(hi[i], max(lo[i], p[i] + dp[i])) for i in range(len(p))]
        new_residual = _residual(new_p, run, power_t, power_q, fixed, nodes, dt)
        new_cost = sum(v * v for v in new_residual)
        if new_cost < cost:
            p, residual, cost = new_p, new_residual, new_cost
            lam = max(lam / 3.0, 1e-9)
        else:
            lam *= 5.0
            if lam > 1e8:
                break
        if max(abs(v) for v in dp) < 1e-9:
            break

    if fixed is not None and fixed[0] == "r":
        return math.exp(p[0]), fixed[1], cost
    if fixed is not None and fixed[0] == "alpha":
        return fixed[1], math.exp(p[0]), cost
    return math.exp(p[0]), math.exp(p[1]), cost


def _mean(values):
    return sum(values) / len(values)


def analyse(run):
    run["keep"] = _keep_mask(run["temp"])
    power_t = run["power_t"]
    power_q = run["power_q"]
    if SKIP == "difficulty_2":
        run["h_back"] = 0.0
    if SKIP == "difficulty_3":
        constant = _mean(power_q[-max(1, len(power_q) // 5):])
        power_t = [0.0, 1e-6]
        power_q = [constant, constant]

    if SKIP == "difficulty_1":
        alpha, _, _ = refine(run, power_t, power_q, 5e-7, 1e-3, fix_r=1e-7)
        return {"alpha_m2_s": alpha, "r_m2k_w": 1e-7}

    starts = [1e-7, 1e-5, 1e-4, 5e-4, 2e-3, 8e-3]
    solutions = [refine(run, power_t, power_q, 5e-7, r0) for r0 in starts]
    solutions.sort(key=lambda item: item[2])
    best = solutions[0]
    base = min(solutions, key=lambda item: item[1])

    n = len(run["keep"])
    dof = max(n - 2, 1)
    sigma2 = best[2] / dof

    pure_alpha, _, pure_cost = refine(run, power_t, power_q, 5e-7, 1e-7, fix_r=1e-7)
    bic = n * math.log(max(best[2], 1e-30) / max(pure_cost, 1e-30)) + 2.0 * math.log(n)
    if bic > -1e-12:
        alpha, _, _ = refine(run, power_t, power_q, pure_alpha, 1e-7, fix_r=1e-7, dt=0.5, nodes=41)
        return {"alpha_m2_s": alpha, "r_m2k_w": 1e-7}

    chosen = base if base[2] < best[2] + 4.0 * sigma2 + 1e-12 else best
    alpha, r_contact, _ = refine(run, power_t, power_q, chosen[0], chosen[1], dt=0.5, nodes=41)
    return {"alpha_m2_s": alpha, "r_m2k_w": r_contact}


def main(argv):
    if len(argv) != 2:
        print("usage: python3 analyze.py <run_dir>", file=sys.stderr)
        return 2
    run = load_run(argv[1])
    result = analyse(run)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
