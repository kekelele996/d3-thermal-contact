"""Random hidden runs, one family per difficulty."""

import json
import math
import random
from pathlib import Path

from .forward import simulate

T_AMB = 23.0
SAMPLE = {"density_kg_m3": 2800.0, "cp_j_kg_k": 880.0}
BLOCK = {"thickness_m": 0.005, "density_kg_m3": 2700.0, "cp_j_kg_k": 896.0}
RHO_CP = SAMPLE["density_kg_m3"] * SAMPLE["cp_j_kg_k"]
BLOCK_C = BLOCK["thickness_m"] * BLOCK["density_kg_m3"] * BLOCK["cp_j_kg_k"]


def draw(group, rng):
    if group == 1:
        params = {
            "thickness": rng.uniform(0.008, 0.012),
            "alpha": rng.uniform(6.0e-7, 1.1e-6),
            "r_contact": rng.uniform(3.0e-3, 6.0e-3),
            "h_back": 0.0,
            "tau": rng.uniform(0.05, 0.15),
            "p0": rng.uniform(2500.0, 4000.0),
            "duration": rng.uniform(350.0, 450.0),
        }
    elif group == 2:
        params = {
            "thickness": rng.uniform(0.008, 0.012),
            "alpha": rng.uniform(3.5e-7, 9.0e-7),
            "r_contact": rng.uniform(2.0e-5, 1.0e-4),
            "h_back": rng.uniform(15.0, 30.0),
            "tau": rng.uniform(0.05, 0.15),
            "p0": rng.uniform(1800.0, 3000.0),
            "duration": rng.uniform(800.0, 1000.0),
        }
    else:
        params = {
            "thickness": rng.uniform(0.008, 0.012),
            "alpha": rng.uniform(5.0e-7, 1.0e-6),
            "r_contact": rng.uniform(5.0e-6, 3.0e-5),
            "h_back": 0.0,
            "tau": rng.uniform(15.0, 25.0),
            "p0": rng.uniform(2500.0, 4000.0),
            "duration": rng.uniform(350.0, 450.0),
        }
    return params


def build(group, seed, out_dir):
    rng = random.Random(seed)
    params = draw(group, rng)
    duration = int(round(params["duration"]))
    times = [float(t) for t in range(duration + 1)]
    power_q = [params["p0"] * (1.0 - math.exp(-t / params["tau"])) for t in times]
    noise = random.Random(rng.getrandbits(32))
    power_log = [q * (1.0 + noise.gauss(0.0, 0.004)) for q in power_q]

    temp = simulate(
        params["alpha"],
        params["r_contact"],
        thickness=params["thickness"],
        rho_cp=RHO_CP,
        block_c=BLOCK_C,
        h_back=params["h_back"],
        t_amb=T_AMB,
        times=times,
        power_t=times,
        power_q=power_log,
        nodes=161,
        dt=0.25,
    )
    temp = [v + noise.gauss(0.0, 0.02) for v in temp]
    if group == 3:
        # 现场记录偶尔出现单点尖刺：少量采样被抬/压 0.6 K。
        count = max(1, len(temp) // 150)
        for idx in rng.sample(range(1, len(temp) - 1), count):
            temp[idx] += 1.5 if rng.random() < 0.5 else -1.5

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "run_id": f"{rng.getrandbits(48):012x}",
        "sample": {"thickness_m": round(params["thickness"], 6), **SAMPLE},
        "block": dict(BLOCK),
        "ambient_c": T_AMB,
        "back_heat_transfer_w_m2_k": round(params["h_back"], 4),
        "duration_s": duration,
        "logger_note": "采样为原始记录，偶尔有单点跳变",
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "power.csv").open("w", encoding="utf-8") as f:
        f.write("t_s,q_w_m2\n")
        for t, q in zip(times, power_log):
            f.write(f"{t:.0f},{q:.3f}\n")
    with (out / "temp.csv").open("w", encoding="utf-8") as f:
        f.write("t_s,t_back_c\n")
        for t, v in zip(times, temp):
            f.write(f"{t:.0f},{v:.4f}\n")
    for name in ("meta.json", "power.csv", "temp.csv"):
        (out / name).chmod(0o644)

    return {
        "group": group,
        "seed": seed,
        "alpha": params["alpha"],
        "r_contact": params["r_contact"],
        "thickness": params["thickness"],
        "h_back": params["h_back"],
        "tau": params["tau"],
        "duration": duration,
        "run_dir": str(out),
    }
