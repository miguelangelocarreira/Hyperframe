#!/usr/bin/env python3
"""
Efeito de oclusão: texto 'THE GATHERING' desaparece atrás da escultura.

Composição de camadas:
  Layer 0 — vídeo original (fundo)
  Layer 1 — texto 'THE GATHERING' centrado
  Layer 2 — máscara da escultura (oculta o texto por baixo)

Fluxo de trabalho:
  1. Define a máscara no primeiro frame (modo --define-mask)
  2. Gera preview 480p para validação
  3. Após confirmação, gera ficheiro final 1080p

Uso:
    # Passo 1 — definir máscara interativamente (clica os contornos da escultura)
    python helpers/gathering_effect.py edit/normalized/IMG_8712_norm.mp4 --define-mask

    # Passo 2 — preview 480p
    python helpers/gathering_effect.py edit/normalized/IMG_8712_norm.mp4 --preview

    # Passo 3 — render final
    python helpers/gathering_effect.py edit/normalized/IMG_8712_norm.mp4 --final
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MASK_CONFIG = Path("edit/mask_points.json")
PREVIEW_OUT = Path("edit/preview_lowres.mp4")
FINAL_OUT = Path("edit/documentary_mask_effect.mp4")

TEXT = "THE GATHERING"
FEATHER_RATIO = 0.20  # 20% de feathering nas bordas


# ─── Utilitários de fonte ────────────────────────────────────────────────────

FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def load_font(frame_width: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(60, frame_width // 14)
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def render_text_layer(width: int, height: int, font) -> np.ndarray:
    """Renderiza 'THE GATHERING' centrado — retorna RGBA numpy array."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bbox = draw.textbbox((0, 0), TEXT, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = (height - th) // 2

    # Sombra subtil para legibilidade
    draw.text((x + 3, y + 3), TEXT, font=font, fill=(0, 0, 0, 120))
    # Texto branco principal
    draw.text((x, y), TEXT, font=font, fill=(255, 255, 255, 230))

    return np.array(img)


# ─── Definição da máscara ────────────────────────────────────────────────────

_poly_points: list[tuple[int, int]] = []


def _mouse_callback(event, x, y, flags, param) -> None:
    global _poly_points
    frame_display = param["frame"].copy()
    if event == cv2.EVENT_LBUTTONDOWN:
        _poly_points.append((x, y))
    # Desenha pontos e linhas em tempo real
    for i, pt in enumerate(_poly_points):
        cv2.circle(frame_display, pt, 5, (0, 255, 0), -1)
        if i > 0:
            cv2.line(frame_display, _poly_points[i - 1], pt, (0, 255, 0), 2)
    if len(_poly_points) > 2:
        cv2.line(frame_display, _poly_points[-1], _poly_points[0], (0, 255, 0), 1)
    param["display"][:] = frame_display


def define_mask(video_path: Path) -> None:
    """Abre o primeiro frame e permite definir a máscara por polygon click."""
    global _poly_points
    cap = cv2.VideoCapture(str(video_path))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("Erro: não foi possível ler o primeiro frame.", file=sys.stderr)
        sys.exit(1)

    display = frame.copy()
    win = "Define mascara — clica os contornos da escultura | Enter=confirmar | R=reset | Q=sair"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, min(frame.shape[1], 1280), min(frame.shape[0], 720))
    cv2.setMouseCallback(win, _mouse_callback, {"frame": frame, "display": display})

    print("\nInstruções:")
    print("  • Clica os contornos da escultura para definir o polígono da máscara")
    print("  • Enter — confirma e guarda")
    print("  • R — reset (apaga todos os pontos)")
    print("  • Q — sair sem guardar")

    while True:
        cv2.imshow(win, display)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10):  # Enter
            break
        elif key == ord("r"):
            _poly_points = []
            display[:] = frame.copy()
        elif key == ord("q"):
            cv2.destroyAllWindows()
            print("Cancelado.")
            return

    cv2.destroyAllWindows()

    if len(_poly_points) < 3:
        print("Erro: precisas de pelo menos 3 pontos para definir a máscara.", file=sys.stderr)
        sys.exit(1)

    MASK_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    MASK_CONFIG.write_text(json.dumps({
        "points": _poly_points,
        "frame_shape": list(frame.shape[:2]),  # [height, width]
    }, indent=2))
    print(f"\nMáscara guardada ({len(_poly_points)} pontos) → {MASK_CONFIG}")


# ─── Tracking com optical flow ───────────────────────────────────────────────

def track_mask(prev_gray: np.ndarray, curr_gray: np.ndarray,
               prev_pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Lucas-Kanade sparse optical flow. Retorna (new_pts, status)."""
    lk_params = dict(
        winSize=(21, 21),
        maxLevel=3,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    new_pts, status, _ = cv2.calcOpticalFlowPyrLK(
        prev_gray, curr_gray, prev_pts, None, **lk_params
    )
    return new_pts, status.flatten()


def pts_to_homography(src: np.ndarray, dst: np.ndarray,
                      status: np.ndarray) -> np.ndarray | None:
    good_src = src[status == 1]
    good_dst = dst[status == 1]
    if len(good_src) < 4:
        return None
    H, _ = cv2.findHomography(good_src, good_dst, cv2.RANSAC, 5.0)
    return H


def warp_polygon(points: list[tuple[int, int]], H: np.ndarray) -> np.ndarray:
    """Aplica homografia ao polígono da máscara."""
    pts = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    warped = cv2.perspectiveTransform(pts, H)
    return warped.reshape(-1, 2).astype(np.int32)


def build_feathered_mask(poly: np.ndarray, h: int, w: int,
                         feather_ratio: float = 0.20) -> np.ndarray:
    """Cria máscara binária com feathering gaussiano nas bordas."""
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [poly], 255)

    # Feathering: blur com kernel proporcional ao tamanho da máscara
    area = cv2.contourArea(poly.reshape(-1, 1, 2).astype(np.float32))
    radius = max(5, int(np.sqrt(area) * feather_ratio))
    # Kernel deve ser ímpar
    ksize = radius * 2 + 1
    mask_float = cv2.GaussianBlur(mask.astype(np.float32), (ksize, ksize), radius)
    return mask_float / 255.0  # 0.0 – 1.0


# ─── Composição frame a frame ─────────────────────────────────────────────────

def composite_frame(video_frame: np.ndarray, text_rgba: np.ndarray,
                    sculpture_mask: np.ndarray) -> np.ndarray:
    """
    Compõe frame com efeito de oclusão.
    sculpture_mask: float32 [0,1] — 1.0 = dentro da escultura (texto invisível)
    """
    h, w = video_frame.shape[:2]
    result = video_frame.astype(np.float32)

    # Alpha do texto: canal A do texto × (1 - máscara da escultura)
    text_a = text_rgba[:h, :w, 3:4].astype(np.float32) / 255.0
    occlusion = sculpture_mask[:, :, np.newaxis]   # [h,w,1]
    effective_alpha = text_a * (1.0 - occlusion)

    text_rgb = text_rgba[:h, :w, :3].astype(np.float32)

    # Blend: result = video * (1 - α_eff) + text * α_eff
    result = result * (1.0 - effective_alpha) + text_rgb * effective_alpha
    return np.clip(result, 0, 255).astype(np.uint8)


# ─── Pipeline principal ───────────────────────────────────────────────────────

def process(video_path: Path, preview: bool = False) -> Path:
    config = json.loads(MASK_CONFIG.read_text())
    mask_points = [tuple(p) for p in config["points"]]

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"Erro: não foi possível abrir {video_path}", file=sys.stderr)
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Dimensões de output (libx264 exige dimensões pares)
    if preview:
        scale = 480 / orig_h
        out_w = (int(orig_w * scale) // 2) * 2  # garante número par
        out_h = 480
        out_path = PREVIEW_OUT
        crf, preset = "28", "ultrafast"
    else:
        out_w = (orig_w // 2) * 2
        out_h = (orig_h // 2) * 2
        out_path = FINAL_OUT
        crf, preset = "18", "slow"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n{'Preview 480p' if preview else 'Render final 1080p'}: {out_path}")
    print(f"  {orig_w}x{orig_h} @ {fps:.2f}fps — {total_frames} frames")

    # Pré-renderizar layer de texto (tamanho do output)
    font = load_font(out_w)
    text_rgba = render_text_layer(out_w, out_h, font)

    # FFmpeg pipe para escrita do vídeo
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_video = Path(tmpdir) / "raw.mp4"

        ffmpeg_in = subprocess.Popen([
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{out_w}x{out_h}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "pipe:0",
            "-an",  # sem áudio (adicionamos depois)
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", crf, "-preset", preset,
            str(raw_video),
        ], stdin=subprocess.PIPE)

        # Lê primeiro frame para inicializar tracking
        ret, prev_frame = cap.read()
        if not ret:
            print("Erro: vídeo vazio.", file=sys.stderr)
            sys.exit(1)

        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)

        # Features iniciais dentro do polígono da máscara
        init_poly = np.array(mask_points, dtype=np.int32)
        roi_mask = np.zeros_like(prev_gray)
        cv2.fillPoly(roi_mask, [init_poly], 255)
        prev_feature_pts = cv2.goodFeaturesToTrack(
            prev_gray, maxCorners=150, qualityLevel=0.01,
            minDistance=5, mask=roi_mask,
        )

        current_poly = init_poly.copy()
        frame_idx = 0

        while True:
            # Aplica escala para preview
            frame = prev_frame if frame_idx == 0 else frame  # noqa — atribuído abaixo
            if frame_idx > 0:
                ret, frame = cap.read()
                if not ret:
                    break

            if preview:
                frame_out = cv2.resize(frame, (out_w, out_h))
                poly_scaled = (current_poly * scale).astype(np.int32)
            else:
                frame_out = frame
                poly_scaled = current_poly

            # Máscara com feathering
            sculpture_mask = build_feathered_mask(poly_scaled, out_h, out_w, FEATHER_RATIO)

            # Composição
            result = composite_frame(frame_out, text_rgba, sculpture_mask)

            # Envia frame para FFmpeg
            ffmpeg_in.stdin.write(result.tobytes())

            # Tracking para próximo frame (só se houver features)
            if frame_idx < total_frames - 1 and prev_feature_pts is not None and len(prev_feature_pts) > 0:
                curr_gray = cv2.cvtColor(frame if not preview else frame, cv2.COLOR_BGR2GRAY)
                new_pts, status = track_mask(prev_gray, curr_gray, prev_feature_pts)

                H = pts_to_homography(prev_feature_pts, new_pts, status)
                if H is not None:
                    current_poly = warp_polygon(mask_points, H)

                # Atualiza features (re-detecta periodicamente para robustez)
                if frame_idx % 30 == 0:
                    roi_mask_cur = np.zeros_like(curr_gray)
                    cv2.fillPoly(roi_mask_cur, [current_poly.astype(np.int32)], 255)
                    new_features = cv2.goodFeaturesToTrack(
                        curr_gray, maxCorners=150, qualityLevel=0.01,
                        minDistance=5, mask=roi_mask_cur,
                    )
                    if new_features is not None:
                        prev_feature_pts = new_features

                prev_gray = curr_gray
                mask_points = [tuple(p) for p in current_poly.tolist()]

            frame_idx += 1
            if frame_idx % 30 == 0:
                pct = frame_idx / total_frames * 100
                print(f"  {frame_idx}/{total_frames} frames ({pct:.0f}%)", end="\r", flush=True)

        cap.release()
        ffmpeg_in.stdin.close()
        ffmpeg_in.wait()
        print(f"\n  Frames processados. A adicionar áudio...")

        # Mux com áudio original (loudnorm já aplicado na normalização)
        mux_cmd = [
            "ffmpeg", "-y",
            "-i", str(raw_video),
            "-i", str(video_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v", "-map", "1:a",
            "-shortest",
            str(out_path),
        ]
        result = subprocess.run(mux_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Aviso mux áudio:\n{result.stderr}", file=sys.stderr)
            # Fallback: copia o raw sem áudio
            raw_video.rename(out_path)

    print(f"\nPronto → {out_path}")
    return out_path


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Efeito de oclusão THE GATHERING")
    parser.add_argument("video", help="Vídeo normalizado (edit/normalized/IMG_8712_norm.mp4)")
    parser.add_argument("--define-mask", action="store_true",
                        help="Modo interativo para definir máscara da escultura")
    parser.add_argument("--preview", action="store_true",
                        help="Render preview 480p (mais rápido)")
    parser.add_argument("--final", action="store_true",
                        help="Render final 1080p alta qualidade")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Erro: ficheiro não encontrado: {video_path}", file=sys.stderr)
        sys.exit(1)

    if args.define_mask:
        define_mask(video_path)
        print("\nPróximo passo:")
        print(f"  python helpers/gathering_effect.py {args.video} --preview")
        return

    if not MASK_CONFIG.exists():
        print(f"Erro: máscara não definida. Corre primeiro com --define-mask", file=sys.stderr)
        sys.exit(1)

    if args.preview:
        out = process(video_path, preview=True)
        print(f"\nValida o preview em: {out}")
        print("Se OK, corre com --final para o render completo.")
    elif args.final:
        process(video_path, preview=False)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
