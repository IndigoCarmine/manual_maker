"""manual.json のデータモデルと読み書き。"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = REPO_ROOT / "projects"
TEMPLATES_DIR = REPO_ROOT / "templates"

_lock = threading.Lock()


@dataclass
class Click:
    x: float  # 画像内の相対座標 (0-1)
    y: float
    button: str = "left"


@dataclass
class Element:
    name: str = ""
    control_type: str = ""


@dataclass
class Step:
    id: str
    image: str
    trigger: str = "click"  # click | hotkey
    time: str = ""
    window_title: str = ""
    process: str = ""
    click: Click | None = None
    element: Element | None = None
    typed_text: str = ""
    title: str = ""
    description: str = ""
    note: str = ""
    section: str = ""  # 章見出し（同じ値が続く手順を1つの章にまとめる）
    highlight: bool = True
    include: bool = True
    # ユーザーが手で編集したフィールド名。describe はここに含まれる項目を上書きしない
    edited: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Step:
        d = dict(d)
        if d.get("click"):
            d["click"] = Click(**d["click"])
        if d.get("element"):
            d["element"] = Element(**d["element"])
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Manual:
    title: str = ""
    app_name: str = ""
    author: str = ""
    created: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    intro: str = ""
    steps: list[Step] = field(default_factory=list)
    edited: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Manual:
        d = dict(d)
        d["steps"] = [Step.from_dict(s) for s in d.get("steps", [])]
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def next_id(self) -> str:
        n = max((int(s.id) for s in self.steps if s.id.isdigit()), default=0)
        return f"{n + 1:04d}"


def project_dir(name: str) -> Path:
    return PROJECTS_DIR / name


def manual_path(name: str) -> Path:
    return project_dir(name) / "manual.json"


def load(name: str) -> Manual:
    path = manual_path(name)
    if not path.exists():
        raise FileNotFoundError(f"プロジェクト '{name}' が見つかりません: {path}")
    with _lock:
        return Manual.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save(name: str, manual: Manual) -> None:
    path = manual_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(manual.to_dict(), ensure_ascii=False, indent=2)
    with _lock:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)


def backup_dir(name: str) -> Path:
    return project_dir(name) / "backups"


def backup(name: str, label: str) -> Path:
    """現在の manual.json を backups/ に退避する。"""
    src = manual_path(name)
    d = backup_dir(name)
    d.mkdir(exist_ok=True)
    dst = d / f"{datetime.now():%Y%m%d-%H%M%S}-{label}.json"
    with _lock:
        dst.write_bytes(src.read_bytes())
    return dst


def list_backups(name: str) -> list[Path]:
    d = backup_dir(name)
    return sorted(d.glob("*.json"), reverse=True) if d.exists() else []


def restore_latest(name: str) -> Path:
    """最新のバックアップに戻す（戻したバックアップは削除）。"""
    backups = list_backups(name)
    if not backups:
        raise FileNotFoundError("元に戻せるバックアップがありません")
    latest = backups[0]
    with _lock:
        os.replace(latest, manual_path(name))
    return latest


def list_projects() -> list[str]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted(p.name for p in PROJECTS_DIR.iterdir() if (p / "manual.json").exists())
