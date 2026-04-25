#!/usr/bin/env python3
"""
Transcrição de vídeo via ElevenLabs Scribe.
Extrai áudio mono 16kHz, envia para a API e guarda JSON com timestamps word-level.

Uso:
    python helpers/transcribe.py video.mp4
    python helpers/transcribe.py video.mp4 --language pt
    python helpers/transcribe.py video.mp4 --num-speakers 2
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()


def extract_audio(video_path: Path, out_wav: Path) -> None:
    """Extrai áudio mono 16kHz do vídeo."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-ac", "1",          # mono
        "-ar", "16000",      # 16kHz
        "-vn",               # sem vídeo
        str(out_wav),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Erro ffmpeg:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def call_scribe(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    num_speakers: int | None = None,
) -> dict:
    """Chama a API ElevenLabs Scribe e retorna o JSON completo."""
    data: dict = {
        "model_id": "scribe_v1",
        "diarize": "true",
        "tag_audio_events": "true",
        "timestamps_granularity": "word",
    }
    if language:
        data["language_code"] = language
    if num_speakers:
        data["num_speakers"] = str(num_speakers)

    print(f"A enviar para ElevenLabs Scribe: {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)")

    with open(audio_path, "rb") as f:
        resp = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": api_key},
            files={"file": (audio_path.name, f, "audio/wav")},
            data=data,
            timeout=1800,
        )

    if resp.status_code != 200:
        print(f"Erro Scribe {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        sys.exit(1)

    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Transcrever vídeo com ElevenLabs Scribe")
    parser.add_argument("video", help="Caminho para o ficheiro de vídeo")
    parser.add_argument("--language", help="Código de idioma (ex: pt, en)")
    parser.add_argument("--num-speakers", type=int, help="Número de speakers")
    parser.add_argument("--edit-dir", default="edit", help="Diretório de output (default: edit/)")
    args = parser.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("Erro: ELEVENLABS_API_KEY não definida. Adiciona ao ficheiro .env", file=sys.stderr)
        sys.exit(1)

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Erro: ficheiro não encontrado: {video_path}", file=sys.stderr)
        sys.exit(1)

    # Diretório de output
    edit_dir = Path(args.edit_dir)
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    out_json = transcripts_dir / f"{video_path.stem}.json"

    # Cache: não re-transcrever se já existe
    if out_json.exists():
        print(f"Transcrição já existe: {out_json}. A usar cache.")
        with open(out_json) as f:
            result = json.load(f)
        print(f"  {len(result.get('words', []))} palavras carregadas.")
        return

    # Extrair áudio temporário
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = Path(tmp.name)

    try:
        print(f"A extrair áudio de {video_path.name}...")
        extract_audio(video_path, tmp_wav)

        result = call_scribe(
            tmp_wav,
            api_key,
            language=args.language,
            num_speakers=args.num_speakers,
        )
    finally:
        tmp_wav.unlink(missing_ok=True)

    # Guardar
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    words = result.get("words", [])
    duration = max((w.get("end", 0) for w in words), default=0)
    print(f"Transcrição guardada: {out_json}")
    print(f"  {len(words)} palavras | duração: {duration:.1f}s")


if __name__ == "__main__":
    main()
