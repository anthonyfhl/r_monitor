"""On-demand, offline Codex runner in the logged-in Windows session.

The daily S4U bank writer keeps its original availability. Only isolated code
repair moves to this bridge; bank collection and notifications stay in main.py.
"""
import argparse
import ctypes
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree

from src.config import PROJECT_ROOT
from src.state import file_lock, read_json, write_json

TASK_NAME = r"\RMonitorCodexRepair"
BRIDGE_ROOT = PROJECT_ROOT / "logs" / "repair_bridge"
MAX_AGE = 360


def in_noninteractive_session():
    if sys.platform != "win32":
        return False
    session = ctypes.c_uint()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.windll.kernel32.GetCurrentProcessId(), ctypes.byref(session)):
        raise RuntimeError("Cannot verify Windows session identity")
    return session.value == 0


def validate_task(xml):
    ns = {"t":"http://schemas.microsoft.com/windows/2004/02/mit/task"}
    task = ElementTree.fromstring(xml)
    commands = task.findall("t:Actions/t:Exec", ns)
    if len(commands) != 1:
        raise RuntimeError("Repair bridge must have exactly one fixed action")
    action = commands[0]
    command = action.findtext("t:Command", namespaces=ns)
    arguments = action.findtext("t:Arguments", namespaces=ns)
    cwd = action.findtext("t:WorkingDirectory", namespaces=ns)
    if Path(command or "").resolve() != Path(sys.executable).with_name("pythonw.exe").resolve():
        raise RuntimeError("Repair bridge Python identity changed")
    if arguments != "-B -m src.repair_bridge --work" or Path(cwd or "").resolve() != PROJECT_ROOT.resolve():
        raise RuntimeError("Repair bridge action or directory changed")
    if task.findtext("t:Principals/t:Principal/t:LogonType", namespaces=ns) != "InteractiveToken":
        raise RuntimeError("Repair bridge requires the verified interactive session")
    level = task.findtext("t:Principals/t:Principal/t:RunLevel", namespaces=ns)
    # Windows omits its default low-privilege value when exporting this task.
    if level not in (None, "LeastPrivilege"):
        raise RuntimeError("Repair bridge must remain unelevated")


def request_repair(source, error):
    query = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML"], capture_output=True, text=True, timeout=15)
    if query.returncode:
        raise RuntimeError("Offline repair bridge is not installed")
    validate_task(query.stdout)
    BRIDGE_ROOT.mkdir(parents=True, exist_ok=True)
    identifier = uuid.uuid4().hex
    request = BRIDGE_ROOT / (identifier + ".request.json")
    response = BRIDGE_ROOT / (identifier + ".response.json")
    write_json(request, {"id":identifier, "source":source, "error":str(error)[:2000], "created_at":time.time()})
    started = subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True, text=True, timeout=15)
    if started.returncode:
        return "離線修復已保存待辦；Windows 尚未啟動登入工作階段的修復任務，銀行資料保留"
    deadline = time.monotonic() + MAX_AGE
    while time.monotonic() < deadline:
        if response.exists():
            result = read_json(response)
            if result.get("id") != identifier or not isinstance(result.get("outcome"), str):
                raise RuntimeError("Repair bridge response identity is invalid")
            return result["outcome"]
        time.sleep(1)
    return "離線修復已保存待辦；等待登入工作階段的結果超時，未確認恢复，銀行資料保留"


def run_pending():
    from src.repair import _codex_repair_local
    BRIDGE_ROOT.mkdir(parents=True, exist_ok=True)
    with file_lock(BRIDGE_ROOT / "worker.lock"):
        for path in sorted(BRIDGE_ROOT.glob("*.request.json")):
            identifier = path.name.removesuffix(".request.json")
            if not re.fullmatch(r"[a-f0-9]{32}", identifier):
                continue
            response = BRIDGE_ROOT / (identifier + ".response.json")
            if response.exists():
                continue
            request = read_json(path)
            if request.get("id") != identifier or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", str(request.get("source", ""))):
                outcome = "離線修復待辦格式無效；未執行，原資料保留"
            elif not 0 <= time.time() - request.get("created_at", 0) <= MAX_AGE:
                outcome = "離線修復待辦已過時；未執行，原每日監測保留失敗及冷卻紀錄"
            elif (BRIDGE_ROOT / (identifier + ".started.json")).exists():
                outcome = "離線修復曾啟動但結果缺失；停止重跑，保留原始診斷證據"
            else:
                write_json(BRIDGE_ROOT / (identifier + ".started.json"), {"started_at":time.time(), "id":identifier})
                try:
                    outcome = _codex_repair_local(request["source"], request["error"])
                except Exception as exc:
                    outcome = "離線修復啟動失敗（" + type(exc).__name__ + "）；原資料保留"
            write_json(response, {"id":identifier, "outcome":outcome, "completed_at":time.time()})
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", action="store_true", required=True)
    parser.parse_args()
    raise SystemExit(run_pending())
