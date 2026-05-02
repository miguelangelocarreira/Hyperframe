#!/usr/bin/env python3
"""
Regista um resumo de sessão em edit/project.md.

Uso (args):
    python helpers/session_log.py "intro.mp4 (37s, 1080p60)" "3 fillers removidos" neutral_punch "final.mp4 (31s)" \
        --subtitles --pending "ajustar overlay do logo"

Uso (JSON):
    python helpers/session_log.py --from-json edit/session.json
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path


def format_entry(
    date_str: str,
    video: str,
    cuts: str,
    grade: str,
    subtitles: bool,
    result: str,
    pending: str | None,
) -> str:
    lines = [
        f"## Sessão {date_str}",
        f"- Vídeo: {video}",
        f"- Cortes: {cuts}",
        f"- Grade: {grade}",
        f"- Legendas: {'sim' if subtitles else 'não'}",
        f"- Resultado: {result}",
    ]
    if pending:
        lines.append(f"- Pendente: {pending}")
    return "\n".join(lines)


def append_to_project_md(entry: str, project_md: Path) -> None:
    project_md.parent.mkdir(parents=True, exist_ok=True)
    if project_md.exists() and project_md.stat().st_size > 0:
        with open(project_md, "a", encoding="utf-8") as f:
            f.write(f"\n\n{entry}\n")
    else:
        with open(project_md, "w", encoding="utf-8") as f:
            f.write(f"{entry}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Registar resumo de sessão em edit/project.md")
    parser.add_argument("video", nargs="?", help='Vídeo e info (ex: "intro.mp4 (37s, 1080p60)")')
    parser.add_argument("cuts", nargs="?", help="Descrição dos cortes")
    parser.add_argument("grade", nargs="?", help="Preset de grade utilizado")
    parser.add_argument("result", nargs="?", help='Resultado (ex: "final.mp4 (31s)")')
    parser.add_argument("--subtitles", action="store_true", default=True, help="Legendas aplicadas (default: sim)")
    parser.add_argument("--no-subtitles", dest="subtitles", action="store_false")
    parser.add_argument("--pending", help="Notas pendentes para a próxima sessão")
    parser.add_argument("--date", default=date.today().isoformat(), help="Data da sessão (default: hoje)")
    parser.add_argument("--from-json", metavar="PATH", help="Carregar campos de ficheiro JSON")
    parser.add_argument("--edit-dir", default="edit", help="Diretório de output (default: edit/)")
    args = parser.parse_args()

    if args.from_json:
        json_path = Path(args.from_json)
        if not json_path.exists():
            print(f"Erro: ficheiro não encontrado: {json_path}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Erro: JSON inválido em {json_path}: {e}", file=sys.stderr)
            sys.exit(1)

        video = data.get("video", "N/A")
        cuts = data.get("cuts", "N/A")
        grade = data.get("grade", "N/A")
        subtitles = data.get("subtitles", True)
        result = data.get("result", "N/A")
        pending = data.get("pending")
        date_str = data.get("date", args.date)
    else:
        missing = [n for n, v in [("video", args.video), ("cuts", args.cuts), ("grade", args.grade), ("result", args.result)] if not v]
        if missing:
            parser.print_usage()
            print(f"Erro: argumentos obrigatórios em falta: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        video = args.video
        cuts = args.cuts
        grade = args.grade
        result = args.result
        subtitles = args.subtitles
        pending = args.pending
        date_str = args.date

    entry = format_entry(date_str, video, cuts, grade, subtitles, result, pending)
    project_md = Path(args.edit_dir) / "project.md"
    append_to_project_md(entry, project_md)
    print(f"Sessão registada em {project_md}")


if __name__ == "__main__":
    main()
