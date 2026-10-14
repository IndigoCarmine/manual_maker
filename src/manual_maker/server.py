"""編集用ローカル Web UI（FastAPI）。"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import build as build_mod
from . import describe as describe_mod
from . import model
from .model import Manual

STATIC_DIR = Path(__file__).parent / "static"
NAME_RE = re.compile(r"^[\w\-. ]+$")

app = FastAPI(title="manual_maker")
_busy = threading.Lock()  # describe / build の同時実行を防ぐ


def _check(name: str) -> str:
    if not NAME_RE.match(name) or name.startswith("."):
        raise HTTPException(400, "不正なプロジェクト名です")
    return name


def _load(name: str) -> Manual:
    try:
        return model.load(_check(name))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/projects")
def projects():
    return model.list_projects()


@app.post("/api/projects")
def create_project(name: str = Body(..., embed=True)):
    _check(name)
    if model.manual_path(name).exists():
        raise HTTPException(409, "同名のプロジェクトが既にあります")
    model.project_dir(name).joinpath("images").mkdir(parents=True, exist_ok=True)
    model.save(name, Manual(title=name))
    return {"name": name}


@app.get("/api/p/{name}/manual")
def get_manual(name: str):
    return _load(name).to_dict()


@app.put("/api/p/{name}/manual")
def put_manual(name: str, data: dict = Body(...)):
    _load(name)
    manual = Manual.from_dict(data)
    model.save(name, manual)
    return manual.to_dict()


@app.delete("/api/p/{name}/steps/{step_id}")
def delete_step(name: str, step_id: str):
    m = _load(name)
    step = m.step(step_id)
    if not step:
        raise HTTPException(404, "ステップがありません")
    m.steps.remove(step)
    model.save(name, m)
    img = model.project_dir(name) / step.image
    img.unlink(missing_ok=True)
    return m.to_dict()


@app.post("/api/p/{name}/describe")
def describe(name: str, step_ids: list[str] | None = Body(None), force: bool = Body(False),
             model_name: str | None = Body(None)):
    _load(name)
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "別の処理を実行中です")
    try:
        m = describe_mod.describe(name, step_ids=step_ids, force=force, model_name=model_name or None)
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    finally:
        _busy.release()
    return m.to_dict()


@app.post("/api/p/{name}/restructure")
def restructure(name: str, instruction: str = Body("", embed=True)):
    from .restructure import restructure as run

    _load(name)
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "別の処理を実行中です")
    try:
        m, changes = run(name, instruction=instruction)
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    finally:
        _busy.release()
    return {"manual": m.to_dict(), "changes": changes}


@app.post("/api/p/{name}/undo")
def undo(name: str):
    _load(name)
    try:
        restored = model.restore_latest(name)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"manual": _load(name).to_dict(), "restored": restored.name}


@app.get("/api/p/{name}/backups")
def backups(name: str):
    _load(name)
    return [p.name for p in model.list_backups(name)]


@app.post("/api/p/{name}/build")
def build(name: str):
    _load(name)
    if not _busy.acquire(blocking=False):
        raise HTTPException(409, "別の処理を実行中です")
    try:
        out = build_mod.build(name)
    except Exception as e:
        raise HTTPException(500, str(e)) from e
    finally:
        _busy.release()
    return {"pdf": f"/files/{name}/{out.name}", "typ": str(model.project_dir(name) / "manual.typ")}


@app.post("/api/p/{name}/record")
def record(name: str, fullscreen: bool = Body(False, embed=True)):
    """記録を新しいコンソールで開始する（終了は Ctrl+Shift+Q）。"""
    _load(name)
    cmd = [sys.executable, "-m", "manual_maker.cli", "record", name]
    if fullscreen:
        cmd.append("--fullscreen")
    subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=model.REPO_ROOT)
    return {"started": True}


model.PROJECTS_DIR.mkdir(exist_ok=True)
app.mount("/files", StaticFiles(directory=model.PROJECTS_DIR), name="files")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _server_running(port: int) -> bool:
    """同じポートで manual_maker の編集UIが既に動いているか。"""
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/projects", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def serve(project: str | None = None, port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn
    import webbrowser

    url = f"http://127.0.0.1:{port}/"
    if project:
        url += f"#{project}"
    if _server_running(port):
        print(f"編集UIは既に起動しています: {url}")
        if open_browser:
            webbrowser.open(url)
        return
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"編集UI: {url}  （Ctrl+C で終了）")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
