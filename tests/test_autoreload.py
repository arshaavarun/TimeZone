"""Auto-reload: launch serve.py on its own port against a fresh DB copy and
confirm a source change makes the worker restart on its own (PID changes) while
the portal stays up — the hupper setup behind the always-on service. Windows-only;
runs on its own port (5099) and a throwaway probe template so the live service on
5000 is never disturbed."""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.harness import standalone, snapshot_db, PROJECT, REAL_DB  # noqa: E402

PORT = 5099


def _pid_listening(port):
    """PID of the process LISTENING on ``port`` (Windows netstat), or None."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, text=True).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(":%d" % port):
            return parts[4]
    return None


def _http_ok(port):
    try:
        return urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=2).status == 200
    except Exception:
        return False


def run(h):
    h.section("auto-reload")
    if os.name != "nt":
        h.check("auto-reload (skipped: Windows-only check)", True)
        return

    rdb = tempfile.NamedTemporaryFile(prefix="tz_reload_", suffix=".db", delete=False)
    rdb.close()
    if os.path.exists(REAL_DB):
        snapshot_db(REAL_DB, rdb.name)
    # a throwaway template the *test* server watches; the live service does not,
    # since its watch list was fixed at its own startup (so 5000 is undisturbed)
    probe = os.path.join(PROJECT, "templates", "_reload_probe.html")
    proc = None
    try:
        with open(probe, "w") as f:
            f.write("<!-- reload probe A -->")
        env = dict(os.environ, TIMEZONE_DB=rdb.name, TIMEZONE_PORT=str(PORT),
                   TIMEZONE_RELOAD="1", TIMEZONE_RELOAD_WORKER="1")  # worker flag skips backup
        proc = subprocess.Popen(
            [sys.executable, os.path.join(PROJECT, "serve.py")],
            cwd=PROJECT, env=env,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        up = False
        for _ in range(50):
            if _http_ok(PORT):
                up = True
                break
            time.sleep(0.3)
        h.check("reload server starts on port %d" % PORT, up)

        pid1 = _pid_listening(PORT)
        time.sleep(0.5)
        with open(probe, "w") as f:            # edit a watched file -> should reload
            f.write("<!-- reload probe B -->")
        reloaded = False
        for _ in range(50):
            time.sleep(0.3)
            pid2 = _pid_listening(PORT)
            if pid2 and pid1 and pid2 != pid1:
                reloaded = True
                break
        h.check("server auto-reloads after a source change", reloaded)
        h.check("server still serving after reload", _http_ok(PORT))
    finally:
        if proc is not None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(5):
            lp = _pid_listening(PORT)
            if not lp:
                break
            subprocess.run(["taskkill", "/F", "/PID", lp],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.3)
        for path in (probe, rdb.name):
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    standalone(run)
