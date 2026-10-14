"""manual-maker コマンド。

  manual-maker record <name>     操作を記録（クリックで自動撮影）
  manual-maker describe <name>   Claude Code で説明文を生成
  manual-maker edit [<name>]     編集用 Web UI を開く
  manual-maker restructure <name> 補足・指示をもとに Claude で再構成
  manual-maker undo <name>       直前の再構成を元に戻す
  manual-maker build <name>      Typst ソース（manual.typ）を書き出して PDF を作成
  manual-maker compile <name>    手で編集した manual.typ をそのまま PDF にする
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(prog="manual-maker", description="操作マニュアル作成ヘルパー")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="操作を記録する")
    r.add_argument("name", help="プロジェクト名（projects/<name>）。既存なら追記")
    r.add_argument("--fullscreen", action="store_true", help="ウィンドウではなくモニター全体を撮影")
    r.add_argument("--no-keys", action="store_true", help="キーボード入力を記録しない")

    d = sub.add_parser("describe", help="Claude Code で説明文を生成")
    d.add_argument("name")
    d.add_argument("--steps", help="対象ステップID（カンマ区切り）。省略時は全ステップ")
    d.add_argument("--force", action="store_true", help="手で編集済みの文も上書き")
    d.add_argument("--model", help="Claude のモデル（例: sonnet, opus, haiku）")

    rs = sub.add_parser("restructure", help="補足・指示をもとに Claude で再構成")
    rs.add_argument("name")
    rs.add_argument("-i", "--instruction", default="", help="全体への指示（例: 'GPU設定の手順は省く'）")
    rs.add_argument("--model", help="Claude のモデル（例: sonnet, opus）")

    u = sub.add_parser("undo", help="直前の再構成を元に戻す（backups/ の最新に戻す）")
    u.add_argument("name")

    e = sub.add_parser("edit", help="編集用 Web UI を開く")
    e.add_argument("name", nargs="?")
    e.add_argument("--port", type=int, default=8765)
    e.add_argument("--no-browser", action="store_true")

    b = sub.add_parser("build", help="manual.typ を書き出して PDF を作成")
    b.add_argument("name")
    b.add_argument("-o", "--output", help="出力先 PDF パス")

    c = sub.add_parser("compile", help="手で編集した manual.typ をそのまま PDF にする")
    c.add_argument("name")
    c.add_argument("-o", "--output", help="出力先 PDF パス")

    args = p.parse_args(argv)
    try:
        if args.cmd == "record":
            from .recorder import record

            record(args.name, fullscreen=args.fullscreen, record_keys=not args.no_keys)
        elif args.cmd == "describe":
            from .describe import describe

            ids = [s.strip() for s in args.steps.split(",")] if args.steps else None
            describe(args.name, step_ids=ids, force=args.force, model_name=args.model)
        elif args.cmd == "restructure":
            from .restructure import restructure

            restructure(args.name, instruction=args.instruction, model_name=args.model)
        elif args.cmd == "undo":
            from . import model

            restored = model.restore_latest(args.name)
            print(f"{restored.name} の状態に戻しました")
        elif args.cmd == "edit":
            from .server import serve

            serve(args.name, port=args.port, open_browser=not args.no_browser)
        elif args.cmd == "build":
            from pathlib import Path

            from . import model
            from .build import build

            out = build(args.name, Path(args.output) if args.output else None)
            print(f"Typst: {model.project_dir(args.name) / 'manual.typ'}")
            print(f"PDF: {out}")
        elif args.cmd == "compile":
            from pathlib import Path

            from .build import compile_typst

            out = compile_typst(args.name, Path(args.output) if args.output else None)
            print(f"PDF: {out}")
    except (FileNotFoundError, RuntimeError) as ex:
        print(f"エラー: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
