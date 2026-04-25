#!/usr/bin/env python3
"""
Gera uma imagem PNG com filmstrip + waveform para verificar pontos de corte.
Usa apenas ffmpeg + Pillow (sem librosa).

Uso:
    python helpers/timeline_view.py video.mp4 44.0 47.0
    python helpers/timeline_view.py video.mp4 44.0 47.0 --n-frames 12
    python helpers/timeline_view.py video.mp4 44.0 47.0 -o verify_cut.png
    python helpers/timeline_view.py video.mp4 44.0 47.0 --transcript edit/transcripts/video.json
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


FRAME_W = 280
FRAME_H = 158   # 16:9
WAVE_H  = 80
RULER_H = 24
LABEL_H = 28
PADDING = 12
BG_COLOR = (18, 18, 18)
FRAME_BG = (30, 30, 30)
WAVE_COLOR = (30, 132, 199)
SILENCE_COLOR = (244, 81, 30, 60)
TEXT_COLOR = (200, 200, 200)
ACCENT_COLOR = (30, 132, 199)
CUT_COLOR = (244, 81, 30)


def extract_frames(video: Path, start: float, end: float, n: int, tmpdir: Path) -> list[Path]:
    """Extrai N frames uniformemente distribuídos no intervalo."""
    frames = []
    for i in range(n):
        t = start + (end - start) * i / max(n - 1, 1)
        out = tmpdir / f"frame_{i:03d}.jpg"
        cmd = [
            "ffmpeg", "-y", "-ss", str(t), "-i", str(video),
            "-frames:v", "1",
            "-vf", f"scale={FRAME_W}:{FRAME_H}:force_original_aspect_ratio=decrease,pad={FRAME_W}:{FRAME_H}:(ow-iw)/2:(oh-ih)/2",
            str(out),
        ]
        subprocess.run(cmd, capture_output=True)
        if out.exists():
            frames.append((t, out))
    return frames


def extract_waveform(video: Path, start: float, end: float, tmpdir: Path, samples: int = 500) -> np.ndarray:
    """Extrai envelope RMS do áudio no intervalo."""
    wav = tmpdir / "audio.wav"
    duration = end - start
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start), "-t", str(duration),
        "-i", str(video),
        "-ac", "1", "-ar", "8000", "-vn",
        str(wav),
    ]
    subprocess.run(cmd, capture_output=True)

    if not wav.exists():
        return np.zeros(samples)

    # Ler WAV raw (16-bit PCM)
    raw_cmd = [
        "ffmpeg", "-y", "-i", str(wav),
        "-f", "s16le", "-ac", "1", "-ar", "8000",
        "pipe:1",
    ]
    result = subprocess.run(raw_cmd, capture_output=True)
    if not result.stdout:
        return np.zeros(samples)

    audio = np.frombuffer(result.stdout, dtype=np.int16).astype(float) / 32768.0
    if len(audio) == 0:
        return np.zeros(samples)

    # Calcular envelope RMS em janelas
    chunk = max(1, len(audio) // samples)
    rms = []
    for i in range(samples):
        seg = audio[i * chunk: (i + 1) * chunk]
        if len(seg) > 0:
            rms.append(float(np.sqrt(np.mean(seg ** 2))))
        else:
            rms.append(0.0)

    arr = np.array(rms)
    peak = arr.max()
    if peak > 0:
        arr = arr / peak
    return arr


def find_silence_gaps(waveform: np.ndarray, threshold: float = 0.05) -> list[tuple[float, float]]:
    """Encontra regiões de silêncio (proporção 0–1)."""
    gaps = []
    in_silence = False
    start_idx = 0
    n = len(waveform)

    for i, v in enumerate(waveform):
        if v < threshold and not in_silence:
            in_silence = True
            start_idx = i
        elif v >= threshold and in_silence:
            in_silence = False
            if (i - start_idx) / n > 0.01:  # mínimo 1% da janela
                gaps.append((start_idx / n, i / n))

    return gaps


def get_words_in_range(transcript_path: Path | None, start: float, end: float) -> list[dict]:
    if not transcript_path or not transcript_path.exists():
        return []
    with open(transcript_path, encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", [])
    return [w for w in words if w.get("type") != "audio_event"
            and w.get("start", 0) >= start and w.get("end", 0) <= end]


def render_image(
    frames: list[tuple[float, Path]],
    waveform: np.ndarray,
    silence_gaps: list[tuple[float, float]],
    words: list[dict],
    start: float,
    end: float,
    out_path: Path,
) -> None:
    n = len(frames)
    if n == 0:
        print("Sem frames para renderizar.", file=sys.stderr)
        return

    total_w = n * FRAME_W + (n + 1) * PADDING
    total_h = FRAME_H + WAVE_H + RULER_H + LABEL_H + PADDING * 4

    img = Image.new("RGB", (total_w, total_h), BG_COLOR)
    draw = ImageDraw.Draw(img, "RGBA")

    try:
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_tiny  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except Exception:
        font_small = ImageFont.load_default()
        font_tiny = font_small

    # ── Frames ──
    for i, (t, frame_path) in enumerate(frames):
        x = PADDING + i * (FRAME_W + PADDING)
        y = PADDING

        try:
            frame_img = Image.open(frame_path).resize((FRAME_W, FRAME_H))
            img.paste(frame_img, (x, y))
        except Exception:
            draw.rectangle([x, y, x + FRAME_W, y + FRAME_H], fill=FRAME_BG)

        # Timestamp
        ts = f"{t:.2f}s"
        draw.text((x + 4, y + FRAME_H - 16), ts, fill=TEXT_COLOR, font=font_tiny)

        # Linha divisória
        if i > 0:
            draw.line([(x - PADDING // 2, PADDING), (x - PADDING // 2, PADDING + FRAME_H)],
                      fill=CUT_COLOR, width=2)

    # ── Waveform ──
    wave_y = FRAME_H + PADDING * 2
    wave_x_start = PADDING
    wave_w = total_w - PADDING * 2
    wave_mid = wave_y + WAVE_H // 2

    # Fundo da waveform
    draw.rectangle([wave_x_start, wave_y, wave_x_start + wave_w, wave_y + WAVE_H],
                   fill=(25, 25, 25))

    # Silêncios
    for gap_start, gap_end in silence_gaps:
        gx1 = wave_x_start + int(gap_start * wave_w)
        gx2 = wave_x_start + int(gap_end * wave_w)
        draw.rectangle([gx1, wave_y, gx2, wave_y + WAVE_H], fill=(244, 81, 30, 40))

    # Waveform bars
    bar_w = max(1, wave_w // len(waveform))
    for i, v in enumerate(waveform):
        x = wave_x_start + int(i * wave_w / len(waveform))
        h = int(v * (WAVE_H // 2 - 4))
        draw.rectangle([x, wave_mid - h, x + bar_w, wave_mid + h], fill=WAVE_COLOR)

    # Linha central
    draw.line([(wave_x_start, wave_mid), (wave_x_start + wave_w, wave_mid)],
              fill=(50, 50, 50), width=1)

    # ── Régua de tempo ──
    ruler_y = wave_y + WAVE_H + PADDING
    duration = end - start

    for i in range(n):
        t = start + duration * i / max(n - 1, 1)
        x = PADDING + i * (FRAME_W + PADDING) + FRAME_W // 2
        draw.line([(x, ruler_y), (x, ruler_y + 8)], fill=(100, 100, 100), width=1)
        draw.text((x - 15, ruler_y + 10), f"{t:.2f}s", fill=(120, 120, 120), font=font_tiny)

    # ── Palavras da transcrição ──
    if words:
        label_y = ruler_y + RULER_H
        for word in words:
            w_start = word.get("start", 0)
            w_end = word.get("end", w_start + 0.1)
            w_mid = (w_start + w_end) / 2
            prop = (w_mid - start) / duration
            x = wave_x_start + int(prop * wave_w)
            draw.text((x, label_y), word.get("text", ""), fill=ACCENT_COLOR, font=font_tiny)

    # ── Info no topo ──
    draw.text((PADDING, 2), f"Timeline: {start:.2f}s → {end:.2f}s  ({duration:.2f}s)",
              fill=(150, 150, 150), font=font_small)

    img.save(out_path)
    print(f"Timeline guardada: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Visualização de timeline para verificar cortes")
    parser.add_argument("video", help="Ficheiro de vídeo")
    parser.add_argument("start", type=float, help="Início do intervalo (segundos)")
    parser.add_argument("end", type=float, help="Fim do intervalo (segundos)")
    parser.add_argument("--n-frames", type=int, default=8, help="Número de frames (default: 8)")
    parser.add_argument("-o", "--output", help="PNG de output (default: edit/timeline_<start>_<end>.png)")
    parser.add_argument("--transcript", help="JSON de transcrição para mostrar palavras")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"Vídeo não encontrado: {video}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output) if args.output else \
        Path("edit") / f"timeline_{args.start:.0f}_{args.end:.0f}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    transcript_path = Path(args.transcript) if args.transcript else None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        print(f"A extrair {args.n_frames} frames de {args.start:.2f}s a {args.end:.2f}s...")
        frames = extract_frames(video, args.start, args.end, args.n_frames, tmp)

        print("A extrair waveform...")
        waveform = extract_waveform(video, args.start, args.end, tmp)

        silence_gaps = find_silence_gaps(waveform)
        words = get_words_in_range(transcript_path, args.start, args.end)

        render_image(frames, waveform, silence_gaps, words, args.start, args.end, out_path)


if __name__ == "__main__":
    main()
