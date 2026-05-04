#!/usr/bin/env python3
"""
Análise visual de vídeo via Claude Vision (API Anthropic).
Extrai frames em pontos-chave, envia para Claude e devolve uma análise editorial.

Uso:
    python helpers/analyze_visual.py video.mp4
    python helpers/analyze_visual.py video.mp4 --frames 8
    python helpers/analyze_visual.py video.mp4 --transcript edit/transcripts/video.json
    python helpers/analyze_visual.py video.mp4 --output edit/visual_analysis.md
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """És um editor de vídeo sénior com olho clínico para pacing, composição visual e storytelling.
Analisa os frames fornecidos e devolve uma análise editorial objetiva e acionável.

Segue SEMPRE este formato de resposta:

## Análise Visual

**Tipo de conteúdo:** [talking head / tutorial / b-roll / entrevista / outro]
**Qualidade técnica:** [exposição, foco, estabilidade, enquadramento]
**Pacing aparente:** [lento / médio / rápido — baseado na variação entre frames]

## Momentos Notáveis

Para cada frame relevante:
- **[MM:SS]** — [observação: expressão, gesto, corte limpo, problema visual]

## Recomendações de Corte

Lista de 3–6 sugestões concretas baseadas no que vês:
- [Timestamp] [Ação recomendada e porquê]

## Resumo

1–2 frases sobre o estado geral do clip e próximo passo editorial sugerido."""


def get_video_duration(video_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Erro ffprobe:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def extract_frames(video_path: Path, timestamps: list[float], out_dir: Path) -> list[Path]:
    """Extrai um frame PNG para cada timestamp."""
    frames = []
    for i, ts in enumerate(timestamps):
        out_path = out_dir / f"frame_{i:03d}_{ts:.2f}s.png"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(ts),
            "-i", str(video_path),
            "-frames:v", "1",
            "-vf", "scale=1280:-2",  # largura máx 1280, mantém aspect ratio
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and out_path.exists():
            frames.append(out_path)
        else:
            print(f"  Aviso: não foi possível extrair frame em {ts:.2f}s", file=sys.stderr)
    return frames


def frame_to_base64(frame_path: Path) -> str:
    with open(frame_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def build_user_message(
    frames: list[Path],
    timestamps: list[float],
    duration: float,
    transcript_summary: str | None,
) -> list[dict]:
    """Constrói o conteúdo da mensagem com os frames e contexto."""
    content = []

    # Contexto textual
    intro_parts = [f"Vídeo com {duration:.1f}s de duração. Frames extraídos em {len(frames)} pontos:"]
    for ts in timestamps[:len(frames)]:
        mins, secs = divmod(ts, 60)
        intro_parts.append(f"  {int(mins):02d}:{secs:05.2f}")
    content.append({"type": "text", "text": "\n".join(intro_parts)})

    if transcript_summary:
        content.append({
            "type": "text",
            "text": f"\n**Transcrição (excerto):**\n{transcript_summary}",
        })

    # Frames com label de timestamp
    for frame_path, ts in zip(frames, timestamps):
        mins, secs = divmod(ts, 60)
        label = f"{int(mins):02d}:{secs:05.2f}"
        content.append({"type": "text", "text": f"\nFrame @ {label}:"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": frame_to_base64(frame_path),
            },
        })

    content.append({
        "type": "text",
        "text": "\nFaz a análise editorial completa deste clip.",
    })
    return content


def load_transcript_summary(transcript_path: Path, max_chars: int = 800) -> str:
    """Carrega transcrição e devolve um resumo compacto."""
    with open(transcript_path) as f:
        data = json.load(f)

    words = data.get("words", [])
    if not words:
        return ""

    lines = []
    current_line: list[str] = []
    line_start = words[0].get("start", 0.0)

    for word in words:
        text = word.get("text", "").strip()
        if not text:
            continue
        current_line.append(text)
        if len(current_line) >= 10:
            end_ts = word.get("end", word.get("start", 0.0))
            mins, secs = divmod(line_start, 60)
            lines.append(f"[{int(mins):02d}:{secs:05.2f}] {' '.join(current_line)}")
            current_line = []
            if word.get("end"):
                line_start = word["end"]

    if current_line:
        lines.append(f"[--:--] {' '.join(current_line)}")

    summary = "\n".join(lines)
    if len(summary) > max_chars:
        summary = summary[:max_chars] + "\n[...]"
    return summary


def analyze(
    video_path: Path,
    num_frames: int = 6,
    transcript_path: Path | None = None,
    output_path: Path | None = None,
) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Erro: ANTHROPIC_API_KEY não definida no .env", file=sys.stderr)
        sys.exit(1)

    print(f"  Duração do vídeo...", end=" ", flush=True)
    duration = get_video_duration(video_path)
    print(f"{duration:.1f}s")

    # Distribui frames uniformemente, evitando os extremos (0.5s de margem)
    margin = min(0.5, duration * 0.05)
    usable = duration - 2 * margin
    if num_frames == 1:
        timestamps = [duration / 2]
    else:
        step = usable / (num_frames - 1)
        timestamps = [margin + i * step for i in range(num_frames)]

    print(f"  A extrair {num_frames} frames...", end=" ", flush=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        frames = extract_frames(video_path, timestamps, Path(tmp_dir))
        print(f"{len(frames)} extraídos")

        if not frames:
            print("Erro: nenhum frame extraído.", file=sys.stderr)
            sys.exit(1)

        transcript_summary = None
        if transcript_path and transcript_path.exists():
            transcript_summary = load_transcript_summary(transcript_path)
            print(f"  Transcrição carregada ({len(transcript_summary)} chars)")

        print("  A enviar para Claude Vision...", flush=True)
        client = anthropic.Anthropic(api_key=api_key)

        user_content = build_user_message(frames, timestamps, duration, transcript_summary)

        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

    analysis = response.content[0].text

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        stem = video_path.stem
        header = f"# Análise Visual — {stem}\n\nVídeo: `{video_path}`\n\n"
        output_path.write_text(header + analysis)
        print(f"  Guardado em: {output_path}")

    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Análise visual de vídeo via Claude Vision")
    parser.add_argument("video", help="Caminho para o ficheiro de vídeo")
    parser.add_argument("--frames", type=int, default=6, metavar="N",
                        help="Número de frames a analisar (padrão: 6)")
    parser.add_argument("--transcript", metavar="PATH",
                        help="JSON de transcrição para contexto adicional")
    parser.add_argument("--output", "-o", metavar="PATH",
                        help="Guardar análise em ficheiro Markdown")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Erro: ficheiro não encontrado: {video_path}", file=sys.stderr)
        sys.exit(1)

    transcript_path = Path(args.transcript) if args.transcript else None
    output_path = Path(args.output) if args.output else None

    print(f"\nAnálise visual: {video_path.name}")
    print("─" * 50)
    analysis = analyze(video_path, args.frames, transcript_path, output_path)

    print("\n" + "─" * 50)
    print(analysis)


if __name__ == "__main__":
    main()
