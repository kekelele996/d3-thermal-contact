"""按权重汇总检查结果，并负责评分目录的清场与收尾。

Harbor 0.24 单步任务的 /logs/verifier 在解题阶段就挂进容器，权限 0777，
进入评分前不会清空；同时存在 reward.json 和 reward.txt 时 Harbor 优先读
reward.json。所以评分开始先清场，结束时再删一次 reward.json。

检查记录写在 root 私有目录（默认 /run/harbor-verify），候选程序以 runner
身份运行，读写不到这里；收尾时才复制一份到 /logs/verifier/checks.jsonl 供查看。
"""

import json
import os
import shutil
import signal
import sys
from pathlib import Path

VERIFIER_DIR = Path(os.environ.get("HARBOR_VERIFIER_DIR", "/logs/verifier"))
PRIVATE = Path(os.environ.get("HARBOR_PRIVATE_DIR", "/run/harbor-verify"))
REWARD = VERIFIER_DIR / "reward.txt"
REWARD_JSON = VERIFIER_DIR / "reward.json"
CHECKS = PRIVATE / "checks.jsonl"
WEIGHTS = Path(os.environ.get("HARBOR_WEIGHTS", Path(__file__).with_name("weights.json")))
CANDIDATE_USER = os.environ.get("HARBOR_CANDIDATE_USER", "runner")


def candidate_uid():
    import pwd

    try:
        return pwd.getpwnam(CANDIDATE_USER).pw_uid
    except KeyError:
        return None


def _start_ticks(pid):
    stat = Path(f"/proc/{pid}/stat").read_text()
    return int(stat.rsplit(")", 1)[1].split()[19])


def _protected_pids():
    """PID 1 和容器启动时随它拉起的保活进程（Harbor 的 sleep infinity）不能杀。"""
    protected = {1}
    try:
        init_start = _start_ticks(1)
    except (OSError, ValueError, IndexError):
        return protected
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            ppid = int(Path(entry, "stat").read_text().rsplit(")", 1)[1].split()[1])
            if ppid == 1 and _start_ticks(entry.name) - init_start <= 50:  # 0.5 s 内
                protected.add(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    return protected


def kill_candidate_processes():
    """结束候选用户留下的全部进程，防止后台进程在评分期间改写结果。"""
    uid = candidate_uid()
    if uid is None or uid == os.getuid():
        return 0
    protected = _protected_pids()
    killed = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in protected:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            os.kill(int(entry.name), signal.SIGKILL)
            killed += 1
        except (ProcessLookupError, PermissionError, FileNotFoundError):
            continue
    return killed


def prepare():
    killed = kill_candidate_processes()
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    for item in VERIFIER_DIR.iterdir():
        if item.name == "test-stdout.txt":  # Harbor 正在写的标准输出
            continue
        _remove(item)
    try:
        VERIFIER_DIR.chmod(0o755)
    except OSError:
        pass
    shutil.rmtree(PRIVATE, ignore_errors=True)
    PRIVATE.mkdir(mode=0o700, parents=True)
    REWARD.write_text("0\n", encoding="utf-8")
    print(f"prepare: killed={killed}", file=sys.stderr)


def _remove(path):
    """文件、软链接、目录都删掉；候选可能把 reward.json 建成目录让 unlink 失败。"""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def record(check_id, ok, detail=""):
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    row = {"id": str(check_id), "ok": bool(ok), "detail": str(detail)[:2000]}
    with CHECKS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def finalize():
    kill_candidate_processes()
    _remove(REWARD_JSON)
    _remove(REWARD)
    weights = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weights.json 的权重之和必须大于 0")
    got = 0.0
    seen = set()
    if CHECKS.exists():
        for line in CHECKS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            check_id = row.get("id")
            if check_id in weights and check_id not in seen and row.get("ok") is True:
                seen.add(check_id)
                got += float(weights[check_id])
        shutil.copyfile(CHECKS, VERIFIER_DIR / "checks.jsonl")
    REWARD.write_text(f"{got / total:.6f}\n", encoding="utf-8")
    _remove(REWARD_JSON)
    return got / total


if __name__ == "__main__":
    commands = {"prepare": prepare, "finalize": finalize}
    if len(sys.argv) == 2 and sys.argv[1] in commands:
        commands[sys.argv[1]]()
    else:
        print("usage: python3 score.py prepare|finalize", file=sys.stderr)
        raise SystemExit(2)
