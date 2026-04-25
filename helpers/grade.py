#!/usr/bin/env python3
"""
Color grading de vídeo via FFmpeg.
Analisa frames automaticamente e aplica correção, ou usa presets.

Uso:
    python helpers/grade.py --analyze video.mp4          # só analisa, não aplica
    python helpers/grade.py video.mp4 -o output.mp4      # auto-grade
    python helpers/grade.py video.mp4 -o output.mp4 --preset warm_cinematic
    python helpers/grade.py video.mp4 -o output.mp4 --filter 'eq=contrast=1.1'
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

PRESETS = {
    "subtle": "eq=contrast=1.03:brightness=0.01:saturation=1.05",
    "neutral_punch": (
        "eq=contrast=1.08:brightness=0.02:saturation=1.1,"
        "curves=master='0/0 0.2/0.18 0.8/0.82 1/1'"  # S-curve subtil
    ),
    "warm_cinematic": (
        "eq=contrast=1.12:brightness=-0.02:saturation=1.15,"
        "colorbalance=rs=0.05:gs=0.02:bs=-0.05:rm=0.03:gm=0.0:bm=-0.03,"  # warm shadows
        "curves=master='0/0 0.1/0.07 0.9/0.93 1/1'"  # crush blacks
    ),
    "none": None,
}


def sample_frame_stats(video_path: Path, num_samples: int = 5) -> tuple[float, float, float]:
    """Analisa amostras de frames: luma_mean, luma_range, saturation_mean."""
    duration_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_entries", "format=duration", str(video_path),
    ]
    info = json.loads(subprocess.check_output(duration_cmd))
    duration = float(info["format"]["duration"])

    y_values = []
    sat_values = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(num_samples):
            t = duration * (i + 1) / (num_samples + 1)
            frame_path = Path(tmpdir) / f"frame_{i}.png"
            cmd = [
                "ffmpeg", "-y", "-ss", str(t), "-i", str(video_path),
                "-frames:v", "1", "-vf", "scale=320:-1", str(frame_path),
            ]
            subprocess.run(cmd, capture_output=True)
            if not frame_path.exists():
                continue

            img = np.array(Image.open(frame_path).convert("RGB")).astype(float) / 255.0
            r, g, b = img[:, :, 0], img[:, :, 1], img[:, :, 2]

            # Luma (BT.709)
            y = 0.2126 * r + 0.7152 * g + 0.0722 * b
            y_values.append(y.mean())

            # Saturação aproximada
            max_c = np.maximum(np.maximum(r, g), b)
            min_c = np.minimum(np.minimum(r, g), b)
            sat = np.where(max_c > 0, (max_c - min_c) / max_c, 0)
            sat_values.append(sat.mean())

    if not y_values:
        return 0.5, 0.5, 0.2

    y_mean = float(np.mean(y_values))
    y_range = float(np.max(y_values) - np.min(y_values)) if len(y_values) > 1 else 0.5
    sat_mean = float(np.mean(sat_values))

    return y_mean, y_range, sat_mean


def auto_grade_filter(video_path: Path) -> str:
    """Gera filtro ffmpeg baseado na análise do vídeo."""
    print("A analisar frames...")
    y_mean, y_range, sat_mean = sample_frame_stats(video_path)

    print(f"  Luma média:     {y_mean:.3f}  (ideal: ~0.45)")
    print(f"  Luma range:     {y_range:.3f}  (ideal: >0.65)")
    print(f"  Saturação média:{sat_mean:.3f}  (ideal: >0.18)")

    adjustments = {}

    # Subexposição
    if y_mean < 0.40:
        delta = min((0.40 - y_mean) * 0.3, 0.08)
        adjustments["gamma"] = round(1.0 + delta, 3)

    # Baixo contraste
    if y_range < 0.60:
        delta = min((0.60 - y_range) * 0.12, 0.08)
        adjustments["contrast"] = round(1.0 + delta, 3)

    # Baixa saturação
    if sat_mean < 0.18:
        delta = min((0.18 - sat_mean) * 0.4, 0.10)
        adjustments["saturation"] = round(1.0 + delta, 3)

    if not adjustments:
        print("  Vídeo parece bem exposto. A aplicar correção mínima.")
        return PRESETS["subtle"]

    parts = []
    if "gamma" in adjustments:
        parts.append(f"gamma={adjustments['gamma']}")
    if "contrast" in adjustments:
        parts.append(f"contrast={adjustments['contrast']}")
    if "saturation" in adjustments:
        parts.append(f"saturation={adjustments['saturation']}")

    return f"eq={':'.join(parts)}"


def apply_grade(video_path: Path, out_path: Path, filter_str: str) -> None:
    """Aplica o filtro de color grade com ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "copy",
        str(out_path),
    ]
    print(f"A aplicar grade: {filter_str}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Erro ffmpeg:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"Output: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Color grading de vídeo")
    parser.add_argument("video", nargs="?", help="Vídeo de input")
    parser.add_argument("-o", "--output", help="Ficheiro de output")
    parser.add_argument("--preset", choices=list(PRESETS.keys()), help="Preset de grade")
    parser.add_argument("--filter", help="Filtro ffmpeg custom (ex: 'eq=contrast=1.1')")
    parser.add_argument("--analyze", action="store_true", help="Só analisar, não aplicar")
    args = parser.parse_args()

    if not args.video:
        parser.print_help()
        sys.exit(1)

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Ficheiro não encontrado: {video_path}", file=sys.stderr)
        sys.exit(1)

    if args.analyze:
        y_mean, y_range, sat_mean = sample_frame_stats(video_path)
        print(f"\nAnálise de {video_path.name}:")
        print(f"  Luma média:      {y_mean:.3f}")
        print(f"  Luma range:      {y_range:.3f}")
        print(f"  Saturação média: {sat_mean:.3f}")
        recommended = auto_grade_filter(video_path)
        print(f"\nFiltro recomendado: {recommended}")
        return

    if not args.output:
        print("Erro: -o / --output é obrigatório para aplicar grade", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)

    if args.filter:
        filter_str = args.filter
    elif args.preset:
        filter_str = PRESETS[args.preset]
        if filter_str is None:
            # preset "none" — copia sem alteração
            subprocess.run(["ffmpeg", "-y", "-i", str(video_path), "-c", "copy", str(out_path)])
            print(f"Copiado sem grade: {out_path}")
            return
    else:
        filter_str = auto_grade_filter(video_path)

    apply_grade(video_path, out_path, filter_str)


if __name__ == "__main__":
    main()
