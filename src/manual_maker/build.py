"""Typst で PDF を生成する / 編集用の Typst ソースを書き出す。"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from . import model
from .model import Manual

EXPORT_HEADER = """\
// {title}
// manual-maker が manual.json から生成した編集用ファイルです。
// このファイルを直接編集して、次のコマンドで PDF にできます:
//   typst compile manual.typ      （保存のたびに自動更新: typst watch manual.typ）
// デザインは style.typ を編集してください。
// 注意: manual-maker build / 編集UIの「PDF作成」を実行すると manual.json から再生成されます
//       （変更されていた場合、上書き前の内容は backups/ に保存されます）。
"""


def find_typst() -> str:
    exe = shutil.which("typst")
    if not exe:
        raise RuntimeError("typst が見つかりません（winget install Typst.Typst）")
    return exe


# ---------- Typst ソース生成 ----------
_MARKUP_SPECIAL = re.compile(r"([\\#*_`$<>@\[\]~/])")


def _markup(text: str) -> str:
    """プレーンテキストを Typst マークアップに変換（特殊文字をエスケープ、改行は改行のまま）。"""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = _MARKUP_SPECIAL.sub(r"\\\1", line)
        # 行頭の = - + は見出し・箇条書き・番号付きリストになるのでエスケープ
        line = re.sub(r"^(\s*)([=\-+])", r"\1\\\2", line)
        lines.append(line)
    return " \\\n".join(lines)


def _str(text: str) -> str:
    """Typst の文字列リテラル。"""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _content(text: str) -> str:
    return "[" + _markup(text) + "]"


def render_typst(m: Manual) -> str:
    steps = [s for s in m.steps if s.include]
    has_sections = any(s.section for s in steps)
    out = [EXPORT_HEADER.format(title=m.title.replace("\n", " ")), '#import "style.typ": *', ""]
    out.append(f"#show: manual.with(title: {_str(m.title)}, author: {_str(m.author)})")
    out.append("")
    out.append("#cover(")
    out.append(f"  title: {_str(m.title)},")
    out.append(f"  app: {_str(m.app_name)},")
    out.append(f"  created: {_str(m.created)},")
    out.append(f"  author: {_str(m.author)},")
    out.append(")")
    out.append("")
    out.append('#outline(title: "目次", depth: 2)')
    out.append("")
    if m.intro:
        out += ["= はじめに", "", _markup(m.intro), ""]
    if not has_sections:
        out += ["#section[操作手順]", ""]

    prev = None
    for n, s in enumerate(steps, 1):
        if has_sections and s.section != prev:
            out += [f"#section{_content(s.section or 'その他')}", ""]
        prev = s.section
        out.append(f"// ---- 手順 {n}（id={s.id}）----")
        args = [str(n), _content(s.title or "（タイトル未設定）"), f'image("{s.image}")']
        if s.click and s.highlight:
            args.append(f"click: (x: {s.click.x}, y: {s.click.y})")
        if s.note:
            args.append(f"note: {_content(s.note)}")
        out.append(f"#step({', '.join(args)})[")
        if s.description:
            out.append("  " + _markup(s.description).replace("\n", "\n  "))
        out.append("]")
        out.append("")
    return "\n".join(out)


def export_typst(name: str) -> Path:
    """projects/<name>/manual.typ と style.typ を書き出す。変更されていた既存ファイルは backups/ に退避。"""
    m = model.load(name)
    pdir = model.project_dir(name)
    files = {
        pdir / "manual.typ": render_typst(m),
        pdir / "style.typ": (model.TEMPLATES_DIR / "style.typ").read_text(encoding="utf-8"),
    }
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    for path, text in files.items():
        if path.exists():
            old = path.read_text(encoding="utf-8")
            if old == text:
                continue
            bdir = model.backup_dir(name)
            bdir.mkdir(exist_ok=True)
            (bdir / f"{stamp}-{path.name}").write_text(old, encoding="utf-8")
        path.write_text(text, encoding="utf-8")
    return pdir / "manual.typ"


# ---------- PDF ----------
def _compile(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"typst compile 失敗:\n{proc.stderr}")


def build(name: str, output: Path | None = None) -> Path:
    """manual.json から PDF を作り、編集用の Typst ソースも書き出す。"""
    typ = export_typst(name)
    out = output or model.project_dir(name) / "manual.pdf"
    _compile([find_typst(), "compile", str(typ), str(out)])
    return out


def compile_typst(name: str, output: Path | None = None) -> Path:
    """手で編集した projects/<name>/manual.typ をそのまま PDF にする（再生成しない）。"""
    typ = model.project_dir(name) / "manual.typ"
    if not typ.exists():
        raise FileNotFoundError(f"{typ} がありません。先に build してください")
    out = output or typ.with_suffix(".pdf")
    _compile([find_typst(), "compile", str(typ), str(out)])
    return out
