#!/usr/bin/env python3
"""
Transcrição em lote com 4 workers paralelos via ElevenLabs Scribe.
Respeita o cache: ficheiros já transcritos são ignorados.

Uso:
    python helpers/transcribe_batch.py ../pasta/com/videos/
    python helpers/transcribe_batch.py ../pasta/ --language pt --num-speakers 2
"""

import argparse
import json
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from transcribe import call_scribe, extract_audio

load_dotenv()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def transcribe_one(
    video_path: Path,
    api_key: str,
    transcripts_dir: Path,
    language: str | None,
    num_speakers: int | None,
) -> tuple[Path, str]:
    """Transcreve um vídeo. Retorna (video_path, status_string)."""
    out_json = transcripts_dir / f"{video_path.stem}.json"

    if out_json.exists():
        with open(out_json) as f:
            data = json.load(f)
        n = len(data.get("words", []))
        return video_path, f"cached ({n} palavras)"

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = Path(tmp.name)

    try:
        extract_audio(video_path, tmp_wav)
        result = call_scribe(tmp_wav, api_key, language=language, num_speakers=num_speakers)
    except Exception as e:
        return video_path, f"erro: {e}"
    finally:
        tmp_wav.unlink(missing_ok=True)

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    n = len(result.get("words", []))
    return video_path, f"done ({n} palavras)"


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcrição em lote com 4 workers paralelos")
    parser.add_argument("directory", help="Diretório com ficheiros de vídeo")
    parser.add_argument("--language", help="Código de idioma (ex: pt, en)")
    parser.add_argument("--num-speakers", type=int, help="Número de speakers")
    parser.add_argument("--edit-dir", default="edit", help="Diretório de output (default: edit/)")
    args = parser.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("Erro: ELEVENLABS_API_KEY não definida. Adiciona ao ficheiro .env", file=sys.stderr)
        sys.exit(1)

    source_dir = Path(args.directory)
    if not source_dir.exists():
        print(f"Erro: diretório não encontrado: {source_dir}", file=sys.stderr)
        sys.exit(1)

    videos = [f for f in source_dir.iterdir() if f.suffix.lower() in VIDEO_EXTENSIONS]
    if not videos:
        print(f"Aviso: nenhum vídeo encontrado em {source_dir}")
        sys.exit(0)

    transcripts_dir = Path(args.edit_dir) / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    total = len(videos)
    print(f"Encontrados {total} vídeo(s). A transcrever com 4 workers...\n")

    errors = []
    completed = 0

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                transcribe_one,
                v, api_key, transcripts_dir, args.language, args.num_speakers,
            ): v
            for v in videos
        }
        for future in as_completed(futures):
            completed += 1
            video_path, status = future.result()
            _log(f"[{completed}/{total}] {video_path.name} → {status}")
            if status.startswith("erro:"):
                errors.append(f"{video_path.name}: {status}")

    print()
    if errors:
        print(f"Concluído com {len(errors)} erro(s):")
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Concluído: {total} ficheiro(s) processados.")


if __name__ == "__main__":
    main()
