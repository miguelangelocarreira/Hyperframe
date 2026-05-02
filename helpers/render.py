#!/usr/bin/env python3
"""
Pipeline de render baseado em EDL (Edit Decision List).
5 estágios: extração por segmento → concat → overlays → legendas → loudness.

Uso:
    python helpers/render.py edit/edl.json -o edit/final.mp4
    python helpers/render.py edit/edl.json -o edit/preview.mp4 --preview
    python helpers/render.py edit/edl.json -o edit/final.mp4 --build-subtitles

Formato EDL (edit/edl.json):
    {
      "source": "video.mp4",
      "grade": "neutral_punch",       // opcional: subtle|neutral_punch|warm_cinematic|hdr_to_sdr|none
      "subtitles": true,              // opcional
      "overlays": [                   // opcional: compostar overlays antes das legendas
        {"source": "edit/overlay.mp4", "start": 5.0, "end": 10.0}
      ],
      "segments": [
        {"start": 0.0, "end": 45.2, "beat": "hook", "quote": "Hoje vou mostrar...", "reason": "strong opener"},
        {"start": 46.8, "end": 89.5, "beat": "demo", "quote": "E o resultado...", "reason": "cut filler at 46.1s"}
      ]
    }

    Campos editoriais por segmento (opcionais, ignorados pelo render):
      beat   — tipo de momento: "hook", "demo", "cta", "b-roll", etc.
      quote  — texto da transcrição coberto pelo segmento
      reason — motivo do corte / o que foi removido antes deste segmento
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

GRADE_PRESETS = {
    "subtle": "eq=contrast=1.03:brightness=0.01:saturation=1.05",
    "neutral_punch": "eq=contrast=1.08:brightness=0.02:saturation=1.1",
    "warm_cinematic": (
        "eq=contrast=1.12:brightness=-0.02:saturation=1.15,"
        "colorbalance=rs=0.05:gs=0.02:bs=-0.05"
    ),
    "hdr_to_sdr": (
        "zscale=t=linear:npl=100,"
        "format=gbrpf32le,"
        "zscale=p=bt709,"
        "tonemap=tonemap=hable:desat=0,"
        "zscale=t=bt709:m=bt709:r=tv,"
        "format=yuv420p"
    ),
    "none": None,
}

HDR_FILTER = GRADE_PRESETS["hdr_to_sdr"]

QUALITY = {
    "preview": {"scale": "1280:720", "preset": "ultrafast", "crf": "28"},
    "default": {"scale": "1920:1080", "preset": "fast",      "crf": "20"},
    "hq":      {"scale": "1920:1080", "preset": "slow",      "crf": "18"},
}


def run(cmd: list, label: str = "") -> None:
    if label:
        print(f"  {label}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Erro:\n{result.stderr[-2000:]}", file=sys.stderr)
        sys.exit(1)


def extract_segment(
    source: Path,
    start: float,
    end: float,
    out: Path,
    grade_filter: str | None,
    quality: dict,
    pad_ms: int = 30,
    hdr_filter: str | None = None,
) -> None:
    """Extrai um segmento com fade de áudio, conversão HDR→SDR e color grade opcionais."""
    duration = end - start
    fade_dur = pad_ms / 1000

    vf_parts = []
    if hdr_filter:
        vf_parts.append(hdr_filter)
    if grade_filter:
        vf_parts.append(grade_filter)
    if quality["scale"] != "1920:1080":
        vf_parts.append(f"scale={quality['scale']}")

    af = f"afade=t=in:st=0:d={fade_dur},afade=t=out:st={duration - fade_dur}:d={fade_dur}"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-to", str(end),
        "-i", str(source),
        "-af", af,
        "-c:v", "libx264",
        "-preset", quality["preset"],
        "-crf", quality["crf"],
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
    ]
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]

    cmd.append(str(out))
    run(cmd, f"Extrair {start:.1f}s–{end:.1f}s → {out.name}")


def apply_overlays(video_path: Path, overlays: list[dict], out: Path) -> None:
    """Composita overlays sobre o vídeo base. Deve ser chamada ANTES das legendas (Regra 1)."""
    extra_inputs = []
    fc_parts = []
    prev_label = "0:v"

    for i, ov in enumerate(overlays):
        source = Path(ov["source"])
        if not source.exists():
            print(f"Erro: overlay não encontrado: {source}", file=sys.stderr)
            sys.exit(1)
        start = float(ov["start"])
        end = float(ov["end"])
        if start >= end:
            print(f"Aviso: overlay ignorado (start >= end): {source.name}")
            continue

        duration = end - start
        input_idx = i + 1
        out_label = f"tmp{i}" if i < len(overlays) - 1 else "outv"

        extra_inputs += ["-i", str(source)]
        fc_parts.append(
            f"[{input_idx}:v]trim=duration={duration:.3f},"
            f"setpts=PTS-STARTPTS+({start:.3f}/TB)[ov{i}];"
            f"[{prev_label}][ov{i}]overlay=shortest=1[{out_label}]"
        )
        prev_label = out_label

    if not fc_parts:
        import shutil
        shutil.copy2(video_path, out)
        return

    cmd = (
        ["ffmpeg", "-y", "-i", str(video_path)]
        + extra_inputs
        + ["-filter_complex", ";".join(fc_parts)]
        + ["-map", "[outv]", "-map", "0:a"]
        + ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "copy"]
        + [str(out)]
    )
    run(cmd, f"Overlays ({len(fc_parts)}) → {out.name}")


def concat_segments(segment_files: list[Path], out: Path) -> None:
    """Concatenação lossless via concat demuxer."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_path = Path(f.name)
        for seg in segment_files:
            f.write(f"file '{seg.resolve()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(out),
    ]
    run(cmd, f"Concatenar {len(segment_files)} segmentos → {out.name}")
    list_path.unlink(missing_ok=True)


def build_srt(
    transcript_path: Path,
    segments: list[dict],
    out_srt: Path,
    words_per_chunk: int = 2,
) -> None:
    """Gera ficheiro SRT a partir da transcrição, alinhado à timeline de output."""
    if not transcript_path.exists():
        print(f"Aviso: transcrição não encontrada em {transcript_path}. Legendas ignoradas.")
        return

    with open(transcript_path, encoding="utf-8") as f:
        data = json.load(f)

    words = [w for w in data.get("words", []) if w.get("type") != "audio_event"]
    if not words:
        return

    # Mapear tempo original → tempo de output
    def map_time(t: float) -> float | None:
        offset = 0.0
        for seg in segments:
            seg_dur = seg["end"] - seg["start"]
            if seg["start"] <= t <= seg["end"]:
                return offset + (t - seg["start"])
            offset += seg_dur
        return None

    # Agrupar em chunks de N palavras
    chunks = []
    for i in range(0, len(words), words_per_chunk):
        chunk = words[i:i + words_per_chunk]
        start_out = map_time(chunk[0]["start"])
        end_out = map_time(chunk[-1]["end"])
        if start_out is None or end_out is None:
            continue
        text = " ".join(w["text"] for w in chunk).upper()
        chunks.append((start_out, end_out, text))

    def fmt_time(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(out_srt, "w", encoding="utf-8") as f:
        for idx, (start, end, text) in enumerate(chunks, 1):
            f.write(f"{idx}\n{fmt_time(start)} --> {fmt_time(end)}\n{text}\n\n")

    print(f"  SRT gerado: {out_srt.name} ({len(chunks)} legendas)")


def burn_subtitles(video_path: Path, srt_path: Path, out: Path) -> None:
    """Queima legendas no vídeo (DEVE ser o último passo)."""
    style = (
        "FontName=Helvetica,FontSize=18,Bold=1,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "Outline=2,MarginV=90"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"subtitles={srt_path}:force_style='{style}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "copy",
        str(out),
    ]
    run(cmd, f"Queimar legendas → {out.name}")


def normalize_loudness(video_path: Path, out: Path) -> None:
    """Normalização de loudness em 2 passes: alvo -14 LUFS."""
    print("  Pass 1: análise de loudness...")
    probe_cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
        "-f", "null", "-",
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)

    # Extrair JSON das últimas linhas do stderr
    stderr = result.stderr
    json_start = stderr.rfind("{")
    json_end = stderr.rfind("}") + 1
    stats = {}
    if json_start != -1:
        try:
            stats = json.loads(stderr[json_start:json_end])
        except json.JSONDecodeError:
            pass

    if stats:
        af = (
            f"loudnorm=I=-14:TP=-1:LRA=11:"
            f"measured_I={stats.get('input_i', -23)}:"
            f"measured_TP={stats.get('input_tp', -2)}:"
            f"measured_LRA={stats.get('input_lra', 7)}:"
            f"measured_thresh={stats.get('input_thresh', -33)}:"
            f"offset={stats.get('target_offset', 0)}:"
            f"linear=true:print_format=summary"
        )
    else:
        af = "loudnorm=I=-14:TP=-1:LRA=11"

    print("  Pass 2: normalização...")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-af", af,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    run(cmd, f"Loudness normalizado → {out.name}")


def main():
    parser = argparse.ArgumentParser(description="Render de vídeo via EDL")
    parser.add_argument("edl", help="Ficheiro EDL JSON")
    parser.add_argument("-o", "--output", required=True, help="Ficheiro de output")
    parser.add_argument("--preview", action="store_true", help="Render rápido 720p")
    parser.add_argument("--hq", action="store_true", help="Render alta qualidade")
    parser.add_argument("--build-subtitles", action="store_true", help="Gerar e queimar legendas")
    parser.add_argument("--hdr", action="store_true", help="Pré-processar HDR→SDR antes do grade")
    parser.add_argument("--edit-dir", default="edit", help="Diretório de trabalho")
    args = parser.parse_args()

    edl_path = Path(args.edl)
    if not edl_path.exists():
        print(f"EDL não encontrado: {edl_path}", file=sys.stderr)
        sys.exit(1)

    with open(edl_path, encoding="utf-8") as f:
        edl = json.load(f)

    source = Path(edl["source"])
    if not source.exists():
        print(f"Source não encontrado: {source}", file=sys.stderr)
        sys.exit(1)

    segments = edl.get("segments", [])
    if not segments:
        print("EDL sem segmentos.", file=sys.stderr)
        sys.exit(1)

    quality_key = "preview" if args.preview else ("hq" if args.hq else "default")
    quality = QUALITY[quality_key]

    grade_name = edl.get("grade", "none")
    grade_filter = GRADE_PRESETS.get(grade_name)

    hdr_filter = None
    if args.hdr:
        if grade_filter == HDR_FILTER:
            print("Aviso: --hdr ignorado (grade 'hdr_to_sdr' já inclui a conversão).")
        else:
            hdr_filter = HDR_FILTER

    edit_dir = Path(args.edit_dir)
    edit_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output)

    print(f"\nRender: {source.name} → {out_path.name}")
    print(f"  Segmentos: {len(segments)} | Grade: {grade_name} | Qualidade: {quality_key}\n")

    # ── Estágio 1: extrair segmentos ──
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        seg_files = []

        for i, seg in enumerate(segments):
            seg_out = tmp / f"seg_{i:03d}.mp4"
            extract_segment(source, seg["start"], seg["end"], seg_out, grade_filter, quality, hdr_filter=hdr_filter)
            seg_files.append(seg_out)

        # ── Estágio 2: concatenar ──
        concat_out = tmp / "concat.mp4"
        concat_segments(seg_files, concat_out)

        working = concat_out

        # ── Estágio 3: overlays ──
        overlays = edl.get("overlays", [])
        if overlays:
            overlay_out = tmp / "with_overlays.mp4"
            apply_overlays(working, overlays, overlay_out)
            working = overlay_out

        # ── Estágio 4: legendas (SEMPRE POR ÚLTIMO — Regra 1) ──
        if args.build_subtitles or edl.get("subtitles"):
            # Procurar transcrição
            transcript_path = edit_dir / "transcripts" / f"{source.stem}.json"
            srt_path = tmp / "subtitles.srt"
            build_srt(transcript_path, segments, srt_path)

            if srt_path.exists():
                sub_out = tmp / "with_subs.mp4"
                burn_subtitles(working, srt_path, sub_out)
                working = sub_out

        # ── Estágio 5: loudness ──
        loud_out = tmp / "loud.mp4"
        normalize_loudness(working, loud_out)
        working = loud_out

        # ── Copiar para output final ──
        import shutil
        shutil.copy2(working, out_path)

    total_dur = sum(s["end"] - s["start"] for s in segments)
    print(f"\nFinalizado: {out_path}")
    print(f"  Duração: {total_dur:.1f}s | Segmentos: {len(segments)}")


if __name__ == "__main__":
    main()
