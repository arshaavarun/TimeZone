"""
Register TimeZone to start automatically and hidden when you log into Windows.

Creates a Task Scheduler job named "TimeZone" that runs ``pythonw serve.py``
(no console window) at logon, restarts it if it crashes, and keeps it running
the whole session. After this you never run the .bat again — just open the IP.

Run once:   python install_autostart.py     (or double-click install_autostart.bat)
Remove:     python install_autostart.py --remove   (or uninstall_autostart.bat)

No administrator rights are needed — it's a per-user task that runs as you.
"""
import os
import subprocess
import sys
import tempfile

TASK_NAME = "TimeZone"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVE_PY = os.path.join(PROJECT_DIR, "serve.py")
USER = "%s\\%s" % (os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))

# Task Scheduler XML. Runs as the logged-in user (interactive token, no password
# stored), hidden, auto-restarting up to 3 times a minute apart on failure, with
# no execution time limit so the server can stay up indefinitely.
TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>TimeZone timesheet and invoicing portal - starts hidden at logon.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{USER}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{USER}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{PYTHONW}</Command>
      <Arguments>"{SERVE}"</Arguments>
      <WorkingDirectory>{PROJDIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def pythonw_path():
    """The windowless interpreter (pythonw.exe) sitting next to this python.exe.
    On Store Python this is the version-independent per-user alias, so the task
    keeps working across Python upgrades."""
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def remove():
    rc = subprocess.call(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    print("\nRemoved." if rc == 0 else "\nNothing to remove (or removal failed).")
    return rc


def install():
    xml = TASK_XML.format(
        USER=USER, PYTHONW=pythonw_path(), SERVE=SERVE_PY, PROJDIR=PROJECT_DIR
    )
    # schtasks wants the XML file as UTF-16; the .format above keeps it valid XML.
    fd, path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    with open(path, "w", encoding="utf-16") as f:
        f.write(xml)
    try:
        rc = subprocess.call(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", path, "/F"]
        )
    finally:
        os.remove(path)

    if rc == 0:
        print("\n" + "=" * 60)
        print("TimeZone will now start automatically and hidden when you log in.")
        print("  Launcher : %s" % pythonw_path())
        print("  Serving  : %s  ->  http://127.0.0.1:5000" % SERVE_PY)
        print("\nStart it now without logging out:")
        print('  schtasks /Run /TN "%s"' % TASK_NAME)
        print("To remove later:  python install_autostart.py --remove")
        print("=" * 60)
    else:
        print("\nCould not register the task (schtasks returned %d)." % rc)
    return rc


if __name__ == "__main__":
    sys.exit(remove() if "--remove" in sys.argv else install())
