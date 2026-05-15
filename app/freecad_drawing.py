"""
Construction drawings in FreeCAD (FCStd).
Converts DXF from drawing_engine to FCStd via FreeCAD headless (freecadcmd / FreeCADCmd.exe).
Requires FreeCAD installed; returns None when unavailable.
Set FREECAD_CMD to the full path to freecadcmd (or FreeCADCmd.exe on Windows) if not on PATH.
"""
import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _find_freecad_cmd() -> Optional[str]:
    """
    Return path to FreeCAD command-line executable, or None if not found.
    Checks: FREECAD_CMD env, then PATH (freecadcmd / FreeCADCmd), then Windows install paths.
    """
    cmd = (os.environ.get("FREECAD_CMD") or "").strip()
    if cmd:
        p = Path(cmd)
        if p.is_file():
            return str(p.resolve())
        if p.is_dir():
            exe = p / "FreeCADCmd.exe" if sys.platform == "win32" else p / "freecadcmd"
            if exe.is_file():
                return str(exe.resolve())
        if sys.platform == "win32" and not cmd.endswith(".exe"):
            pexe = Path(cmd + ".exe")
            if pexe.is_file():
                return str(pexe.resolve())
        # Bare name or path not found: use as-is (e.g. for PATH lookup)
        return cmd
    try:
        import shutil
        for name in ("freecadcmd", "FreeCADCmd"):
            exe = shutil.which(name)
            if exe:
                return exe
    except Exception:
        pass
    if sys.platform == "win32":
        pf = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
        # Explicit path for common install: C:\Program Files\FreeCAD 1.0\bin
        for name in ("FreeCAD 1.0", "FreeCAD 0.21", "FreeCAD 0.20"):
            exe = pf / name / "bin" / "FreeCADCmd.exe"
            if exe.is_file():
                return str(exe.resolve())
        local = os.environ.get("LOCALAPPDATA", "")
        bases = [
            pf,
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")),
            Path("C:\\FreeCAD"),
        ]
        if local:
            bases.append(Path(local) / "Programs")
        for base in bases:
            if not base.exists():
                continue
            for d in sorted(base.glob("FreeCAD*"), reverse=True):
                for exe_name in ("bin/FreeCADCmd.exe", "FreeCADCmd.exe"):
                    exe = d / exe_name
                    if exe.is_file():
                        return str(exe.resolve())
        for drive in ("C:", "D:", "E:"):
            for pf in (f"{drive}\\Program Files", f"{drive}\\Program Files (x86)"):
                base = Path(pf)
                if not base.exists():
                    continue
                for d in sorted(base.glob("FreeCAD*"), reverse=True):
                    exe = d / "bin" / "FreeCADCmd.exe"
                    if exe.is_file():
                        return str(exe.resolve())
    return None


def get_freecad_status() -> dict:
    """
    Return FreeCAD connection status for the UI.
    Keys: available (bool), path (str | None), error (str | None).
    """
    path = _find_freecad_cmd()
    if not path:
        return {"available": False, "path": None, "error": "FreeCAD not found. Set FREECAD_CMD or add FreeCAD bin to PATH."}
    return {"available": True, "path": path, "error": None}


# Script run by freecadcmd: reads config JSON, opens DXF, creates TechDraw page, saves FCStd.
_FREECAD_SCRIPT = r"""
import json
import sys
try:
    import FreeCAD
except ImportError:
    sys.exit(1)
config_path = sys.argv[1] if len(sys.argv) > 1 else None
if not config_path:
    sys.exit(2)
with open(config_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
dxf_path = cfg.get("dxf_path")
fcstd_path = cfg.get("fcstd_path")
title = cfg.get("title", "Drawing")[:50]
if not dxf_path or not fcstd_path:
    sys.exit(3)
try:
    doc = FreeCAD.open(dxf_path)
except Exception:
    sys.exit(4)
try:
    page = doc.addObject("TechDraw::DrawPage", "Page")
    page.Label = title
    if doc.Objects:
        view = doc.addObject("TechDraw::DrawViewPart", "View")
        view.Source = [doc.Objects[0]]
        page.addView(view)
    doc.recompute()
    doc.saveAs(fcstd_path)
except Exception:
    try:
        doc.saveAs(fcstd_path)
    except Exception:
        pass
FreeCAD.closeDocument(doc.Name)
sys.exit(0)
"""


def dxf_bytes_to_fcstd(
    dxf_bytes: bytes,
    title: str = "",
    view_label: str = "",
    dimensions_str: str = "",
    freecad_cmd_override: Optional[str] = None,
) -> Optional[bytes]:
    """
    Convert DXF bytes to FreeCAD FCStd construction drawing.
    Returns FCStd file bytes or None if FreeCAD is not available or conversion fails.
    freecad_cmd_override: optional path to FreeCADCmd.exe (or bin folder) for this call only.
    """
    if not dxf_bytes:
        return None
    with tempfile.TemporaryDirectory(prefix="freecad_") as tmpdir:
        dxf_path = Path(tmpdir) / "drawing.dxf"
        fcstd_path = Path(tmpdir) / "drawing.FCStd"
        config_path = Path(tmpdir) / "config.json"
        script_path = Path(tmpdir) / "freecad_script.py"
        dxf_path.write_bytes(dxf_bytes)
        config_path.write_text(
            json.dumps({
                "dxf_path": str(dxf_path.resolve()),
                "fcstd_path": str(fcstd_path.resolve()),
                "title": title or "Drawing",
                "view_label": view_label,
                "dimensions": dimensions_str,
            }),
            encoding="utf-8",
        )
        script_path.write_text(_FREECAD_SCRIPT, encoding="utf-8")
        freecad_cmd = (freecad_cmd_override or "").strip() or _find_freecad_cmd()
        if freecad_cmd and not Path(freecad_cmd).is_file():
            p = Path(freecad_cmd)
            if p.is_dir():
                exe = p / "FreeCADCmd.exe" if sys.platform == "win32" else p / "freecadcmd"
                if exe.is_file():
                    freecad_cmd = str(exe.resolve())
        if not freecad_cmd:
            logger.debug("FreeCAD not found (set FREECAD_CMD or add FreeCAD bin to PATH)")
            return None
        env = os.environ.copy()
        # On Windows, add FreeCAD bin folder to PATH so DLLs are found when exe is a full path
        cmd_path = Path(freecad_cmd)
        if cmd_path.is_file():
            bin_dir = str(cmd_path.parent)
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        try:
            result = subprocess.run(
                [freecad_cmd, str(script_path), str(config_path)],
                cwd=tmpdir,
                capture_output=True,
                timeout=60,
                env=env,
            )
            if result.returncode != 0:
                logger.debug("FreeCAD script exit code %s", result.returncode)
                return None
            if not fcstd_path.exists():
                return None
            return fcstd_path.read_bytes()
        except FileNotFoundError:
            logger.debug("FreeCAD not found (freecadcmd)")
            return None
        except subprocess.TimeoutExpired:
            logger.debug("FreeCAD timeout")
            return None
        except Exception as e:
            logger.debug("FreeCAD error: %s", e)
            return None


def add_fcstd_to_drawings(
    drawings_list: list[dict],
    freecad_cmd_override: Optional[str] = None,
) -> tuple[list[dict], Optional[str]]:
    """
    For each drawing that has dxf_base64, try to add fcstd_base64.
    Modifies each dict in place. Returns (drawings_list, freecad_path_used or None).
    freecad_cmd_override: optional path to FreeCADCmd.exe (or bin folder) for this call only.
    """
    freecad_cmd = (freecad_cmd_override or "").strip() or _find_freecad_cmd()
    if freecad_cmd and not Path(freecad_cmd).is_file():
        p = Path(freecad_cmd)
        if p.is_dir():
            exe = p / "FreeCADCmd.exe" if sys.platform == "win32" else p / "freecadcmd"
            if exe.is_file():
                freecad_cmd = str(exe.resolve())
    for item in drawings_list:
        dxf_b64 = item.get("dxf_base64")
        if not dxf_b64:
            item["fcstd_base64"] = None
            continue
        try:
            dxf_bytes = base64.b64decode(dxf_b64)
        except Exception:
            item["fcstd_base64"] = None
            continue
        title = item.get("name") or item.get("product_name") or "Drawing"
        view_label = item.get("view_label", "")
        dimensions_str = item.get("dimensions", "")
        fcstd_bytes = dxf_bytes_to_fcstd(
            dxf_bytes, title=title, view_label=view_label, dimensions_str=dimensions_str,
            freecad_cmd_override=freecad_cmd,
        )
        item["fcstd_base64"] = base64.b64encode(fcstd_bytes).decode("ascii") if fcstd_bytes else None
    return drawings_list, freecad_cmd
