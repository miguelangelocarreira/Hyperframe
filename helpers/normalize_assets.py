#!/usr/bin/env python3
"""
Normaliza vídeos para 30fps e 1080p usando FFmpeg.
Também aplica loudnorm broadcast (-14 LUFS).

Uso:
    python helpers/normalize_assets.py input/IMG_8712.MOV input/IMG_8930.MOV
    python helpers/normalize_assets.py input/IMG_8712.MOV --fps 25 --outdir edit/normalized
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def probe(video_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Erro ffprobe em {video_path.name}:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def print_info(video_path: Path, info: dict) -> None:
    fmt = info.get("format", {})
    duration = float(fmt.get("duration", 0))
    video_stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    r_frame_rate = video_stream.get("r_frame_rate", "?")
    width = video_stream.get("width", "?")
    height = video_stream.get("height", "?")
    codec = video_stream.get("codec_name", "?")

    # Calcular fps real
    if "/" in str(r_frame_rate):
        num, den = r_frame_rate.split("/")
        fps = round(int(num) / int(den), 3)
    else:
        fps = r_frame_rate

    print(f"  {video_path.name}: {width}x{height} @ {fps}fps | {duration:.1f}s | codec: {codec}")


def normalize(input_path: Path, output_path: Path, fps: int = 30) -> None:
    # scale mantém aspect ratio, pad centra em 1920x1080 com barras pretas
    vf = (
        f"fps={fps},"
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        "-c:a", "aac", "-b:a", "192k",
        "-af", "loudnorm=I=-14:TP=-1:LRA=11",
        str(output_path),
    ]
    print(f"  A normalizar → {output_path.name} ...", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Erro ffmpeg:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"  Pronto: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normaliza vídeos para 30fps 1080p")
    parser.add_argument("videos", nargs="+", help="Ficheiros de vídeo")
    parser.add_argument("--fps", type=int, default=30, help="FPS alvo (padrão: 30)")
    parser.add_argument("--outdir", default="edit/normalized", help="Pasta de output")
    args = parser.parse_args()

    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\nMetadados originais:")
    paths = [Path(v) for v in args.videos]
    for p in paths:
        if not p.exists():
            print(f"  Ficheiro não encontrado: {p}", file=sys.stderr)
            sys.exit(1)
        info = probe(p)
        print_info(p, info)

    print(f"\nNormalização → {args.fps}fps 1080p:")
    for p in paths:
        out = out_dir / f"{p.stem}_norm.mp4"
        normalize(p, out, args.fps)

    print("\nConcluído. Ficheiros em:", out_dir)


if __name__ == "__main__":
    main()
