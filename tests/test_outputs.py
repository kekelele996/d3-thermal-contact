#!/usr/bin/env python3
"""逐项检查分析工具的输出。

九个计分测试分三组，每组三个种子，分别对应三个可以独立失败的难点：
界面热阻、背面换热、功率爬升与记录尖刺。另有一个不计分的入口契约测试。
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

APP = Path("/app")
ENTRY = "analyze.py"
ENTRY_PATH = os.environ.get("HTB_ENTRY", "/app/analyze.py")
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
        [PYTHON, ENTRY_PATH, str(run_dir)],
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
    return data, alpha, r


def relative_error(value, truth):
    return abs(value / truth - 1.0)


def _expect(group, seed, tolerance, field):
    case = cases.build(group, seed, case_dir())
    data, alpha, r = analyse(case)
    truth = case["r_contact"] if field == "r" else case["alpha"]
    value = r if field == "r" else alpha
    err = relative_error(value, truth)
    ok = err <= tolerance
    return ok, f"seed={seed} err={err:.4f} tol={tolerance}"


def test_cli_contract():
    """题面：“标准输出一个 JSON 对象，只有两个字段：”；“只读运行目录，不往目录里写文件；不要联网。”"""
    case = cases.build(1, secrets.randbits(32), case_dir())
    proc = run_candidate(case["run_dir"])
    raw = proc.stdout
    assert proc.returncode == 0, proc.stderr[:300]
    assert raw.strip().startswith("{") and raw.strip().endswith("}"), raw[:200]
    assert raw.endswith("\n"), raw[-20:]
    assert len(raw.encode("utf-8")) > 0
    data = json.loads(raw)
    assert list(data) == ["alpha_m2_s", "r_m2k_w"], list(data)
    assert set(data) == {"alpha_m2_s", "r_m2k_w"}, data
    assert isinstance(data["alpha_m2_s"], float) and isinstance(data["r_m2k_w"], float), data
    assert data["alpha_m2_s"] > 0.0 and data["r_m2k_w"] >= 0.0, data


def test_repeatable():
    """题面：“同一份输入重复执行，结果一致。”"""
    case = cases.build(1, secrets.randbits(32), case_dir())
    first = run_candidate(case["run_dir"]).stdout
    second = run_candidate(case["run_dir"]).stdout
    assert first == second


def test_difficulty_1_case1():
    """题面：“界面热阻相对误差不超过 8%”。"""
    ok, detail = _expect(1, secrets.randbits(32), R_TOL_GROUP_1, "r")
    assert ok, detail


def test_difficulty_1_case2():
    """题面：“界面热阻相对误差不超过 8%”，换一组厚度与热阻。"""
    ok, detail = _expect(1, secrets.randbits(32), R_TOL_GROUP_1, "r")
    assert ok, detail


def test_difficulty_1_case3():
    """题面：“界面热阻相对误差不超过 8%”，第三组界面热阻主导样例。"""
    ok, detail = _expect(1, secrets.randbits(32), R_TOL_GROUP_1, "r")
    assert ok, detail


def test_difficulty_2_case1():
    """题面：“热扩散率相对误差不超过 1.5%”，背面散热强、运行时间长。"""
    ok, detail = _expect(2, secrets.randbits(32), ALPHA_TOL_GROUP_2, "alpha")
    assert ok, detail


def test_difficulty_2_case2():
    """题面：“热扩散率相对误差不超过 1.5%”，换一组背面换热系数。"""
    ok, detail = _expect(2, secrets.randbits(32), ALPHA_TOL_GROUP_2, "alpha")
    assert ok, detail


def test_difficulty_2_case3():
    """题面：“热扩散率相对误差不超过 1.5%”，第三组背面散热样例。"""
    ok, detail = _expect(2, secrets.randbits(32), ALPHA_TOL_GROUP_2, "alpha")
    assert ok, detail


def test_difficulty_3_case1():
    """题面：“热扩散率相对误差不超过 1.5%”，记录里偶尔有单点跳变。"""
    ok, detail = _expect(3, secrets.randbits(32), ALPHA_TOL_GROUP_3, "alpha")
    assert ok, detail


def test_difficulty_3_case2():
    """题面：“热扩散率相对误差不超过 1.5%”，功率爬升 15 到 25 秒。"""
    ok, detail = _expect(3, secrets.randbits(32), ALPHA_TOL_GROUP_3, "alpha")
    assert ok, detail


def test_difficulty_3_case3():
    """题面：“热扩散率相对误差不超过 1.5%”，换一组跳变位置。"""
    ok, detail = _expect(3, secrets.randbits(32), ALPHA_TOL_GROUP_3, "alpha")
    assert ok, detail
