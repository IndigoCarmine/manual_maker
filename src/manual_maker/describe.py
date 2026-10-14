"""Claude Code (claude -p) で各ステップの説明文を生成する。"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable

from PIL import Image

from . import model
from .model import Manual, Step

BATCH_SIZE = 8

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "マニュアル全体のタイトル案"},
        "intro": {"type": "string", "description": "マニュアル冒頭の概要（2〜4文）"},
        "summary": {"type": "string", "description": "ここまでの操作の要約（次バッチへの引き継ぎ用）"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["id", "title", "description"],
            },
        },
    },
    "required": ["title", "intro", "summary", "steps"],
}

INSTRUCTIONS = """\
あなたはソフトウェアの操作マニュアルを書くテクニカルライターです。
ユーザーが Windows アプリを操作した記録（スクリーンショットと操作ログ）から、エンドユーザー向けの手順書を作ります。

ルール:
- 各ステップの画像ファイルを必ず Read ツールで開いて内容を確認すること（パスはカレントディレクトリ基準）。
- クリック位置は画像上のピクセル座標で示す。その位置にあるボタン・メニュー・入力欄を画像から特定すること。
  UI要素名が与えられている場合はそれを優先して正確な名称を使う。
- title: そのステップで行う操作を簡潔に（例: 「[ファイル] メニューを開く」「保存先フォルダーを選ぶ」、20文字程度まで）。
- description: です・ます調で1〜3文。何をどこで操作するか、結果どうなるかを書く。
  ボタン名・メニュー名は [ ] で囲む。入力した文字がある場合はその入力操作も説明に含める。
  場所は「画面右上の」「[ファイル] メニュー内の」のように言葉で示し、ピクセル座標は書かないこと。
  画像から読み取れない推測や、操作と関係のない一般的な注意書きは書かないこと。
- 画面に個人情報やパスワードらしきものが写っていても説明文には書き写さないこと。
- 出力は指定の JSON スキーマに従う。steps には入力で与えたすべての id を同じ順で含める。
"""


def find_claude() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude (Claude Code CLI) が見つかりません")
    return exe


def _step_block(step: Step, num: int, project: str) -> str:
    lines = [f"### id={step.id}（手順 {num}）", f"- 画像: {step.image}"]
    try:
        with Image.open(model.project_dir(project) / step.image) as im:
            w, h = im.size
        lines.append(f"- 画像サイズ: {w}x{h}px")
    except OSError:
        w = h = 0
    if step.click and w:
        btn = "右クリック" if step.click.button == "right" else "クリック"
        lines.append(f"- 操作: {btn} 位置 ({round(step.click.x * w)}, {round(step.click.y * h)})px")
    elif step.trigger == "hotkey":
        lines.append("- 操作: なし（画面状態を示すための手動撮影）")
    if step.element and step.element.name:
        lines.append(f"- クリックしたUI要素: 「{step.element.name}」({step.element.control_type})")
    if step.window_title:
        lines.append(f"- ウィンドウ: {step.window_title} ({step.process})")
    if step.typed_text:
        lines.append(f"- この操作の後にキーボード入力: {step.typed_text!r}")
    if step.note:
        lines.append(f"- 作成者メモ: {step.note}")
    if "title" in step.edited and step.title:
        lines.append(f"- 確定済みタイトル（変更しない）: {step.title}")
    return "\n".join(lines)


def _build_prompt(m: Manual, project: str, batch: list[Step], numbers: dict[str, int],
                  summary: str, total: int) -> str:
    parts = [INSTRUCTIONS, "## マニュアル情報"]
    parts.append(f"- 対象アプリ: {m.app_name or '不明'}")
    if m.title and m.title != project:
        parts.append(f"- タイトル: {m.title}")
    parts.append(f"- 全手順数: {total}")
    if summary:
        parts.append(f"\n## ここまでの手順の要約\n{summary}")
    parts.append("\n## 今回説明を書くステップ")
    parts += [_step_block(s, numbers[s.id], project) for s in batch]
    return "\n".join(parts)


def _run_claude(prompt: str, project: str, model_name: str | None, schema: dict = SCHEMA) -> dict:
    cmd = [
        find_claude(), "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--allowedTools", "Read",
        "--permission-mode", "dontAsk",
    ]
    if model_name:
        cmd += ["--model", model_name]
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=model.project_dir(project), timeout=900,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude 実行失敗 (code {proc.returncode}):\n{proc.stderr or proc.stdout}")
    out = json.loads(proc.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude エラー: {out.get('result')}")
    result = out.get("structured_output")
    if result is None:
        result = json.loads(out["result"])
    return result


def describe(
    project: str,
    step_ids: list[str] | None = None,
    force: bool = False,
    model_name: str | None = None,
    log: Callable[[str], None] = print,
) -> Manual:
    """説明を生成して manual.json に書き込む。

    step_ids 指定時はそのステップのみ。force=False ならユーザー編集済みのフィールドは保持する。
    """
    m = model.load(project)
    targets = [s for s in m.steps if s.include]
    numbers = {s.id: i + 1 for i, s in enumerate(targets)}
    if step_ids:
        targets = [s for s in targets if s.id in step_ids]
    if not targets:
        log("対象ステップがありません")
        return m

    summary = ""
    total = len(numbers)
    results: dict[str, dict] = {}
    whole: dict = {}
    for start in range(0, len(targets), BATCH_SIZE):
        batch = targets[start:start + BATCH_SIZE]
        log(f"Claude に問い合わせ中... 手順 {numbers[batch[0].id]}〜{numbers[batch[-1].id]} / {total}")
        res = _run_claude(_build_prompt(m, project, batch, numbers, summary, total), project, model_name)
        for s in res.get("steps", []):
            results[s["id"]] = s
        summary = res.get("summary", summary)
        whole = res  # 全体の title / intro は全手順を見た最後のバッチのものを採用

    # 最新の manual.json に対してマージ（実行中に UI で編集された内容を潰さない）
    m = model.load(project)
    for step in m.steps:
        r = results.get(step.id)
        if not r:
            continue
        for key in ("title", "description"):
            if force or key not in step.edited:
                setattr(step, key, r.get(key, getattr(step, key)))
                if force and key in step.edited:
                    step.edited.remove(key)
    if not step_ids:
        if whole.get("title") and (force or ("title" not in m.edited)):
            m.title = whole["title"]
        if whole.get("intro") and (force or ("intro" not in m.edited)):
            m.intro = whole["intro"]
    model.save(project, m)
    log(f"完了: {len(results)} ステップに説明を書き込みました")
    return m
