"""補足（note）や全体指示をもとに Claude Code でマニュアル全体を再構成する。

- 不要な手順（ウィンドウを前面に出しただけのクリック、重複クリック等）を除外
- 手順の並べ替え、章（section）分け
- 補足に書かれた指示を反映してタイトル・説明・補足を書き直す
実行前の manual.json は backups/ に退避され、restore_latest で元に戻せる。
画像ファイルは削除せず、除外は include=false で表す。
"""

from __future__ import annotations

from collections.abc import Callable

from . import model
from .describe import _run_claude, _step_block
from .model import Manual

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "intro": {"type": "string"},
        "steps": {
            "type": "array",
            "description": "再構成後の順序で、入力のすべての id を1回ずつ含める",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "include": {"type": "boolean"},
                    "section": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["id", "include", "section", "title", "description", "note"],
            },
        },
        "changes": {"type": "string", "description": "行った変更の要約（箇条書き）"},
    },
    "required": ["title", "intro", "steps", "changes"],
}

INSTRUCTIONS = """\
あなたはソフトウェア操作マニュアルの編集者です。
操作記録から作られたマニュアルの下書きを、読み手（エンドユーザー）にとって分かりやすい手順書に再構成してください。

## 作成者の指示の扱い
- 各ステップの「補足」は作成者が書いたメモです。編集指示（例: 「ここは不要」「次とまとめる」「ここから○○の章」
  「△△について注意を書いて」）が含まれていれば、それに従って再構成してください。
- 指示を反映した後の note は、PDF に「補足」として読み手に表示される文章です。編集指示そのものは残さず、
  読み手向けの補足（注意点・ヒント）があればそれだけを書き、なければ空文字にしてください。
- 全体指示がある場合は最優先で従ってください。

## 再構成のルール
- 不要な手順は include=false にする（削除はしない）。例: ウィンドウを前面に出すだけのクリック、
  同じ要素の連続クリックの重複、誤操作、意味のない手順。迷う場合は include=true のままにする。
- 内容のまとまりごとに section（章名、例: 「データの読み込み」「モデルの設定」）を付ける。
  同じ章の手順は連続させ、章名は完全に同じ文字列にする。章が1つで足りるなら全手順に同じ章名を付ける。
- 並べ替えは、操作の前後関係が壊れない範囲で行う。基本は記録順のまま。
- 除外した手順の操作が説明に必要なら、隣の手順の description に含める（例: 「ダブルクリックして値を入力します」）。
- title: 操作を簡潔に（20文字程度まで）。description: です・ます調で1〜3文、ボタン名・メニュー名は [ ] で囲む。
  ピクセル座標は書かない。
- 説明が空・不十分なステップは、画像を Read ツールで確認して書くこと（パスはカレントディレクトリ基準）。
  それ以外でも、判断に迷う場合は画像を確認してよい。
- 画面に写る個人情報やパスワードらしきものは文章に書き写さない。
- steps には入力のすべての id を、再構成後の順序で1回ずつ含めること。
- changes には、除外・統合・並べ替え・章分けなど行った変更を短く箇条書きで書くこと。
"""


def _step_info(m: Manual, project: str) -> str:
    parts = []
    for i, s in enumerate(m.steps, 1):
        block = _step_block(s, i, project).replace("- 作成者メモ:", "- 補足（作成者のメモ・指示）:")
        extra = [f"- 現在の状態: {'PDFに含める' if s.include else '除外中'}"]
        if s.section:
            extra.append(f"- 現在の章: {s.section}")
        extra.append(f"- 現在のタイトル: {s.title or '（なし）'}")
        extra.append(f"- 現在の説明: {s.description or '（なし）'}")
        parts.append(block + "\n" + "\n".join(extra))
    return "\n\n".join(parts)


def restructure(
    project: str,
    instruction: str = "",
    model_name: str | None = None,
    log: Callable[[str], None] = print,
) -> tuple[Manual, str]:
    """再構成して保存する。(新しい Manual, 変更の要約) を返す。"""
    m = model.load(project)
    if not m.steps:
        raise RuntimeError("ステップがありません")

    prompt = "\n".join([
        INSTRUCTIONS,
        "## 全体指示",
        instruction.strip() or "（なし。各ステップの補足と上記ルールに従って再構成）",
        "\n## マニュアル情報",
        f"- 対象アプリ: {m.app_name or '不明'}",
        f"- 現在のタイトル: {m.title}",
        f"- 現在のはじめに: {m.intro or '（なし）'}",
        f"- 手順数: {len(m.steps)}",
        "\n## ステップ一覧（現在の順序）",
        _step_info(m, project),
    ])
    log(f"Claude に再構成を依頼中...（{len(m.steps)} ステップ）")
    res = _run_claude(prompt, project, model_name, schema=SCHEMA)

    # 実行中に UI で編集された可能性があるので最新を読み直してから適用する
    m = model.load(project)
    by_id = {s.id: s for s in m.steps}
    new_order = []
    for r in res.get("steps", []):
        s = by_id.pop(r.get("id"), None)
        if s is None:
            continue  # 存在しない id / 重複は無視
        s.include = bool(r.get("include", s.include))
        s.section = r.get("section", s.section)
        s.title = r.get("title", s.title)
        s.description = r.get("description", s.description)
        s.note = r.get("note", s.note)
        new_order.append(s)
    # Claude が返さなかったステップは末尾に残す（消さない）
    leftovers = [s for s in m.steps if s.id in by_id]
    m.steps = new_order + leftovers

    if res.get("title"):
        m.title = res["title"]
    if res.get("intro"):
        m.intro = res["intro"]

    backup_path = model.backup(project, "before-restructure")
    model.save(project, m)

    changes = res.get("changes", "").strip()
    if leftovers:
        changes += f"\n- （Claude の出力に含まれなかった {len(leftovers)} 手順を末尾に残しました）"
    kept = sum(s.include for s in m.steps)
    log(f"完了: {kept}/{len(m.steps)} 手順を採用。変更前の状態は {backup_path.name} に保存しました")
    if changes:
        log(changes)
    return m, changes
