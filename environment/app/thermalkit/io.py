"""Reading a measured run directory."""

import csv
import json
import math
from pathlib import Path


def _read_csv(path):
    times = []
    values = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["t_s"]))
            values.append(float(list(row.values())[1]))
    return times, values


def read_run(run_dir):
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    power_t, power_q = _read_csv(run_dir / "power.csv")
    temp_t, temp_c = _read_csv(run_dir / "temp.csv")

    for name, t, v in (("power", power_t, power_q), ("temp", temp_t, temp_c)):
        if len(t) < 10 or len(v) != len(t):
            raise ValueError(f"{name} record is too short or ragged")
        if any(b <= a for a, b in zip(t, t[1:])):
            raise ValueError(f"{name} time column is not increasing")
        if not all(math.isfinite(x) for x in v):
            raise ValueError(f"{name} contains non-finite values")

    return {
        "meta": meta,
        "power_t": power_t,
        "power_q": power_q,
        "time_s": temp_t,
        "temp_c": temp_c,
    }
