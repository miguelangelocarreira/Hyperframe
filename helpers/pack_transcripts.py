#!/usr/bin/env python3
"""
Agrupa a transcrição word-level em frases legíveis com timestamps.
Output: edit/takes_packed.md — base para decisões de corte.

Uso:
    python helpers/pack_transcripts.py --edit-dir edit/
    python helpers/pack_transcripts.py --edit-dir edit/ --silence-threshold 0.7
"""

import argparse
import json
from pathlib import Path


def flush_phrase(words: list, speaker: str | None) -> dict:
    text = " ".join(w["text"] for w in words if w.get("type") != "audio_event")
    events = [w["text"] for w in words if w.get("type") == "audio_event"]
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "speaker": speaker or "S0",
        "text": text.strip(),
        "events": events,
    }


def group_into_phrases(words: list, silence_threshold: float = 0.5) -> list:
    """Agrupa palavras em frases quebrando em silêncios e mudanças de speaker."""
    phrases = []
    current: list = []
    last_end = 0.0
    last_speaker = None

    for word in words:
        start = word.get("start", last_end)
        end = word.get("end", start + 0.1)
        speaker = word.get("speaker", "S0")

        # Quebrar em silêncio longo
        if current and (start - last_end) >= silence_threshold:
            phrases.append(flush_phrase(current, last_speaker))
            current = []

        # Quebrar em mudança de speaker
        if current and last_speaker and speaker != last_speaker:
            phrases.append(flush_phrase(current, last_speaker))
            current = []

        current.append(word)
        last_end = end
        last_speaker = speaker

    if current:
        phrases.append(flush_phrase(current, last_speaker))

    return phrases


def format_time(seconds: float) -> str:
    return f"{seconds:07.2f}"


def main():
    parser = argparse.ArgumentParser(description="Empacotar transcrições word-level em frases")
    parser.add_argument("--edit-dir", default="edit", help="Diretório com edit/transcripts/")
    parser.add_argument("--silence-threshold", type=float, default=0.5,
                        help="Silêncio mínimo (segundos) para quebrar frase (default: 0.5)")
    args = parser.parse_args()

    edit_dir = Path(args.edit_dir)
    transcripts_dir = edit_dir / "transcripts"

    if not transcripts_dir.exists():
        print(f"Diretório não encontrado: {transcripts_dir}")
        print("Corre primeiro: python helpers/transcribe.py <video>")
        return

    json_files = list(transcripts_dir.glob("*.json"))
    if not json_files:
        print(f"Nenhuma transcrição encontrada em {transcripts_dir}")
        return

    out_lines = []

    for json_file in sorted(json_files):
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)

        words = data.get("words", [])
        if not words:
            continue

        phrases = group_into_phrases(words, silence_threshold=args.silence_threshold)

        out_lines.append(f"## {json_file.stem}\n")

        for phrase in phrases:
            t_start = format_time(phrase["start"])
            t_end = format_time(phrase["end"])
            speaker = phrase["speaker"]
            text = phrase["text"]
            events = phrase["events"]

            line = f"[{t_start}-{t_end}] {speaker} {text}"
            if events:
                line += f"  ({', '.join(events)})"
            out_lines.append(line)

        out_lines.append("")

    out_path = edit_dir / "takes_packed.md"
    content = "\n".join(out_lines)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    total_phrases = content.count("\n[")
    print(f"Transcrição embalada: {out_path}")
    print(f"  {total_phrases} frases de {len(json_files)} ficheiro(s)")
    print(f"\nPrimeiras linhas:\n{'─'*60}")
    for line in out_lines[:10]:
        print(line)


if __name__ == "__main__":
    main()
