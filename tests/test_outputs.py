#!/usr/bin/env python3
"""逐项检查分析工具的输出。

每个检查对应一个可以独立失败的难点，id 必须与 weights.json 一致。
隐藏运行由 refkit 现场生成，期望值就是生成参数，不读 solution/。

本脚本以 root 运行；被测程序通过 run_candidate() 以 runner 身份、干净
环境变量、独立进程组运行，超时整组结束。
"""

import json
import math
import os
import secrets
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I 模式下不自动加入脚本目录

from refkit import cases  # noqa: E402
from score import record  # noqa: E402

APP = Path("/app")
ENTRY = "analyze.py"
PYTHON = "/usr/local/bin/python3"
CANDIDATE_USER = os.environ.get("HARBOR_CANDIDATE_USER", "runner")
CANDIDATE_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": f"/home/{CANDIDATE_USER}",
    "LANG": "C.UTF-8",
    "TZ": "UTC",
}
CALL_TIMEOUT_SEC = 120

ALPHA_TOL_GROUP_2 = 0.025
ALPHA_TOL_GROUP_3 = 0.015
R_TOL_GROUP_1 = 0.08


def case_dir():
    path = Path(tempfile.mkdtemp(prefix="in-"))
    path.chmod(0o755)
    return path


def run_candidate(run_dir, timeout=CALL_TIMEOUT_SEC):
    as_root = os.getuid() == 0
    proc = subprocess.Popen(
        [PYTHON, str(APP / ENTRY), str(run_dir)],
        cwd=str(APP),
        env=CANDIDATE_ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        user=CANDIDATE_USER if as_root else None,
        group=CANDIDATE_USER if as_root else None,
        extra_groups=[] if as_root else None,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        raise RuntimeError(f"timeout after {timeout}s")
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def analyse(case):
    proc = run_candidate(case["run_dir"])
    if proc.returncode != 0:
        raise RuntimeError(f"exit={proc.returncode}, stderr={proc.stderr[:400]}")
    data = json.loads(proc.stdout)
    alpha = float(data["alpha_m2_s"])
    r = float(data["r_m2k_w"])
    if not (math.isfinite(alpha) and math.isfinite(r)) or alpha <= 0.0 or r < 0.0:
        raise ValueError(f"invalid values: {data}")
    return alpha, r


def relative_error(value, truth):
    return abs(value / truth - 1.0)


def check_difficulty_1():
    case = cases.build(1, secrets.randbits(63), case_dir())
    alpha, r = analyse(case)
    err = relative_error(r, case["r_contact"])
    ok = err <= R_TOL_GROUP_1
    return ok, f"seed={case['seed']} r_err={err:.4f} tol={R_TOL_GROUP_1}"


def check_difficulty_2():
    case = cases.build(2, secrets.randbits(63), case_dir())
    alpha, r = analyse(case)
    err = relative_error(alpha, case["alpha"])
    ok = err <= ALPHA_TOL_GROUP_2
    return ok, f"seed={case['seed']} alpha_err={err:.4f} tol={ALPHA_TOL_GROUP_2}"


def check_difficulty_3():
    case = cases.build(3, secrets.randbits(63), case_dir())
    alpha, r = analyse(case)
    err = relative_error(alpha, case["alpha"])
    ok = err <= ALPHA_TOL_GROUP_3
    return ok, f"seed={case['seed']} alpha_err={err:.4f} tol={ALPHA_TOL_GROUP_3}"


CHECKS = [
    ("difficulty_1", check_difficulty_1),
    ("difficulty_2", check_difficulty_2),
    ("difficulty_3", check_difficulty_3),
]


def main():
    for check_id, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # 单项异常记为失败，不中断后面的检查
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        record(check_id, ok, detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
