"""Shows a message in this computer's notification area, with nothing to install.

The dashboard runs without a window of its own, so a notification is the one place it can show something only the
person at this computer sees. Each system has a built-in way to raise one: a toast through Windows PowerShell, AppleScript
on macOS, and notify-send on Linux. The text travels as data, in an environment variable or an argument, and is never
spliced into a script, so nothing in it can run. A failure returns False rather than raising, and the caller offers
another way to get the same information.
"""
import base64
import os
import shutil
import subprocess
import sys

TIMEOUT_SECONDS = 15
# Windows only shows toasts from an app it knows. Windows PowerShell's own id is on every copy of Windows 10 and 11.
WINDOWS_APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
WINDOWS_SCRIPT = """
$ErrorActionPreference = 'Stop'
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$title = [Security.SecurityElement]::Escape($env:PYRITE_NOTIFY_TITLE)
$body = [Security.SecurityElement]::Escape($env:PYRITE_NOTIFY_BODY)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$text = "<visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual>"
$actions = "<actions><action content='Dismiss' arguments='dismiss' activationType='system'/></actions>"
$xml.LoadXml("<toast scenario='reminder'>$text$actions</toast>")
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:PYRITE_NOTIFY_APP).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""
MAC_SCRIPT = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"


def _command(title: str, body: str) -> tuple[list[str], dict[str, str]] | None:
    env = dict(os.environ)
    if sys.platform == "win32":
        # Windows PowerShell 5.1, not pwsh: only 5.1 can load the Windows notification classes this way.
        exe = shutil.which("powershell.exe")
        if not exe:
            return None
        env.update(PYRITE_NOTIFY_TITLE=title, PYRITE_NOTIFY_BODY=body, PYRITE_NOTIFY_APP=WINDOWS_APP_ID)
        encoded = base64.b64encode(WINDOWS_SCRIPT.encode("utf-16-le")).decode()
        return [exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], env
    if sys.platform == "darwin":
        exe = shutil.which("osascript")
        return ([exe, "-e", MAC_SCRIPT, title, body], env) if exe else None
    exe = shutil.which("notify-send")
    # "--" ends the options, so a message that starts with a dash is still a message.
    return ([exe, "--app-name=Pyrite", "--urgency=critical", "--", title, body], env) if exe else None


def send(title: str, body: str) -> bool:
    """Show a notification. True if the system took it, which doesn't promise anyone saw it."""
    found = _command(title, body)
    if not found:
        return False
    command, env = found
    try:
        result = subprocess.run(command, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
