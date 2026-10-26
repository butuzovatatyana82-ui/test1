"""Самообновление программы: ищет свежий установщик в GitHub Releases и тихо ставит его поверх."""
import os
import subprocess
import tempfile

from .config import UPDATE_REPO, VERSION
from .engine import download
from .net import http_json


def vtuple(v):
    out = []
    for p in str(v).lstrip("vV").split("."):
        digits = "".join(c for c in p if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def check():
    """None — обновлений нет / не настроено; иначе dict(version, url, notes)."""
    if not UPDATE_REPO:
        return None
    d = http_json(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest", 15)
    ver = d.get("tag_name", "")
    if vtuple(ver) <= vtuple(VERSION):
        return None
    for a in d.get("assets", []):
        if a["name"].lower().endswith("setup.exe"):
            return dict(version=ver.lstrip("vV"), url=a["browser_download_url"], notes=(d.get("body") or "")[:600])
    return None


def install(url, progress=None):
    """Скачивает установщик и запускает его в тихом режиме; Inno Setup сам закроет и перезапустит плеер."""
    dest = os.path.join(tempfile.gettempdir(), "OkunekMusic-Setup.exe")
    download(url, dest, progress, 120)
    subprocess.Popen([dest, "/SILENT", "/SP-", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], close_fds=True)
