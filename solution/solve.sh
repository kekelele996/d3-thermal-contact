#!/usr/bin/env bash
set -euo pipefail

# 参考解：把快速估算替换成"集总铝块 + 一维样品 + 界面热阻 + 背面换热"的
# 瞬态模型，再用多起点最小二乘同时反演热扩散率和界面热阻。
#
# 留一法：
#   HTB_SKIP=difficulty_1  界面按理想接触处理，只反演热扩散率
#   HTB_SKIP=difficulty_2  背面按绝热处理
#   HTB_SKIP=difficulty_3  功率按理想阶跃处理
# 正式 Oracle 不设这个变量。
cd /app
SKIP="${HTB_SKIP:-}"

fix_difficulty_1() { :; }
fix_difficulty_2() { :; }
fix_difficulty_3() { :; }

for d in difficulty_1 difficulty_2 difficulty_3; do
  if [ "$SKIP" = "$d" ]; then
    echo "留一法：跳过 $d" >&2
    continue
  fi
  "fix_$d"
done

cat > /app/thermalkit/solve.py <<'PY'
"""Model-based analysis of one measured run."""

import json
import sys

import numpy as np
from scipy.linalg import solve_banded
from scipy.optimize import least_squares

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
        return np.asarray(t, dtype=float), np.asarray(v, dtype=float)

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


def simulate(alpha, r_contact, run, power_t, power_q, nodes=61, dt=0.5):
    thickness = run["thickness"]
    rho_cp = run["rho_cp"]
    block_c = run["block_c"]
    h_back = run["h_back"]
    t_amb = run["t_amb"]
    times = run["time"]

    dx = thickness / (nodes - 1)
    n = nodes + 1
    cap = np.zeros(n)
    cap[0] = block_c
    cap[1:] = rho_cp * dx
    cap[1] *= 0.5
    cap[-1] *= 0.5

    a = np.zeros((n, n))
    a[0, 0] += 1.0 / r_contact
    a[0, 1] -= 1.0 / r_contact
    a[1, 0] -= 1.0 / r_contact
    a[1, 1] += 1.0 / r_contact
    g = alpha * rho_cp / dx
    for i in range(1, nodes):
        a[i, i] += g
        a[i + 1, i + 1] += g
        a[i, i + 1] -= g
        a[i + 1, i] -= g
    a[-1, -1] += h_back

    lhs = np.diag(cap / dt) + 0.5 * a
    rhs = np.diag(cap / dt) - 0.5 * a
    ab = np.zeros((3, n))
    ab[0, 1:] = np.diag(lhs, 1)
    ab[1, :] = np.diag(lhs)
    ab[2, :-1] = np.diag(lhs, -1)

    temp = np.full(n, t_amb)
    out = np.empty(len(times))
    out[0] = t_amb

    def power(t):
        return float(np.interp(t, power_t, power_q))

    b_prev = np.zeros(n)
    b_prev[-1] = h_back * t_amb
    b_prev[0] = power(0.0)
    index = 1
    steps = int(np.floor(times[-1] / dt + 1e-9))
    for k in range(1, steps + 1):
        t = k * dt
        b = np.zeros(n)
        b[-1] = h_back * t_amb
        b[0] = power(t)
        temp = solve_banded((1, 1), ab, rhs @ temp + 0.5 * (b_prev + b))
        b_prev = b
        while index < len(times) and times[index] <= t + 1e-9:
            out[index] = temp[-1]
            index += 1
    while index < len(times):
        out[index] = temp[-1]
        index += 1
    return out


def refine(run, power_t, power_q, alpha0, r0, fix_r=None, fix_alpha=None, dt=1.0, nodes=31):
    lo = [np.log(ALPHA_BOUNDS[0]), np.log(R_BOUNDS[0])]
    hi = [np.log(ALPHA_BOUNDS[1]), np.log(R_BOUNDS[1])]

    if fix_r is not None:
        def cost(p):
            return simulate(np.exp(p[0]), fix_r, run, power_t, power_q, nodes=nodes, dt=dt) - run["temp"]

        result = least_squares(cost, [np.log(alpha0)], bounds=([lo[0]], [hi[0]]),
                               xtol=1e-10, ftol=1e-10, max_nfev=60)
        return float(np.exp(result.x[0])), fix_r, float(result.cost * 2.0)
    if fix_alpha is not None:
        def cost(p):
            return simulate(fix_alpha, np.exp(p[0]), run, power_t, power_q, nodes=nodes, dt=dt) - run["temp"]

        result = least_squares(cost, [np.log(r0)], bounds=([lo[1]], [hi[1]]),
                               xtol=1e-10, ftol=1e-10, max_nfev=60)
        return fix_alpha, float(np.exp(result.x[0])), float(result.cost * 2.0)

    def residual(p):
        return simulate(np.exp(p[0]), np.exp(p[1]), run, power_t, power_q, nodes=nodes, dt=dt) - run["temp"]

    result = least_squares(residual, np.log([alpha0, r0]), bounds=(lo, hi),
                           xtol=1e-10, ftol=1e-10, max_nfev=60)
    return float(np.exp(result.x[0])), float(np.exp(result.x[1])), float(result.cost * 2.0)


def analyse(run):
    power_t = run["power_t"]
    power_q = run["power_q"]
    if SKIP == "difficulty_2":
        run["h_back"] = 0.0
    if SKIP == "difficulty_3":
        constant = float(np.mean(power_q[-max(1, len(power_q) // 5):]))
        power_t = np.asarray([0.0, 1e-6])
        power_q = np.asarray([constant, constant])

    if SKIP == "difficulty_1":
        alpha, _, _ = refine(run, power_t, power_q, 5e-7, 1e-3, fix_r=1e-7)
        return {"alpha_m2_s": alpha, "r_m2k_w": 1e-7}

    starts = [1e-7, 1e-5, 1e-4, 5e-4, 2e-3, 8e-3]
    solutions = []
    for r0 in starts:
        solutions.append(refine(run, power_t, power_q, 5e-7, r0))
    solutions.sort(key=lambda item: item[2])
    best = solutions[0]
    base = min(solutions, key=lambda item: item[1])

    dof = max(len(run["time"]) - 2, 1)
    sigma2 = best[2] / dof
    if base[2] <= best[2] + 4.0 * sigma2:
        chosen = base
    else:
        chosen = best
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
PY

sed -i "s/__SKIP__/${SKIP}/" /app/thermalkit/solve.py

cat > /app/analyze.py <<'PY'
#!/usr/bin/env python3
"""Station entry point: analyse one measured run directory."""

import sys

from thermalkit.solve import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
PY

chmod 0755 /app/analyze.py
python3 -c "import thermalkit.solve" 
