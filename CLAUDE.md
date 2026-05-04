# Video Studio — ChatCoreLab

Pipeline completo de edição de vídeo com IA: transcrição → cortes → motion graphics → render final.

## Stack

| Ferramenta | Papel |
|---|---|
| **ElevenLabs Scribe** | Transcrição word-level com timestamps |
| **FFmpeg** | Cortes, color grade, concat, loudness |
| **HyperFrames** | Motion graphics HTML→MP4 |
| **Claude Vision** | Análise editorial de frames (analyze_visual.py) |
| **Python helpers** | Orquestração do pipeline |

---

## Pipeline completo (passo a passo)

### 1. Inventário
Antes de qualquer coisa, inspeciona o ficheiro de vídeo:
```bash
ffprobe -v quiet -print_format json -show_streams -show_format video.mp4
```
Anota: duração, resolução, fps, codec de áudio.

### 2. Transcrição
```bash
cd video-studio
python helpers/transcribe.py ../caminho/para/video.mp4
# Com múltiplos speakers:
python helpers/transcribe.py ../video.mp4 --num-speakers 2
# Batch (vários ficheiros):
python helpers/transcribe_batch.py ../pasta/com/videos/
```
Guarda o JSON em `edit/transcripts/<nome>.json`.

### 3. Empacotar transcrição
Agrupa palavras em frases — muito mais legível para tomar decisões:
```bash
python helpers/pack_transcripts.py --edit-dir edit/
```
Produz `edit/takes_packed.md` com formato:
```
[000.00-045.23] S0 Hoje vou mostrar como funciona...
[046.00-089.75] S0 E o resultado final é este aqui...
```

### 4. Análise e decisão de cortes (com o utilizador)
Lê o `takes_packed.md`, identifica:
- Palavras de preenchimento ("hmm", "tipo", "pronto")
- Pausas longas (≥ 400ms entre frases)
- Retakes e gaguejadas

Propõe uma estratégia em 4–8 frases. **Aguarda aprovação antes de executar.**

Exemplo de EDL que geras após aprovação (`edit/edl.json`):
```json
{
  "source": "video.mp4",
  "grade": "neutral_punch",
  "subtitles": true,
  "segments": [
    {"start": 0.0, "end": 45.2},
    {"start": 46.8, "end": 89.5},
    {"start": 91.0, "end": 125.0}
  ]
}
```

### 4b. Análise visual com IA (opcional)
Quando queres uma segunda opinião editorial sobre o clip antes de cortar:
```bash
# Análise com 6 frames (padrão)
python helpers/analyze_visual.py video.mp4

# Mais frames + contexto da transcrição + guardar resultado
python helpers/analyze_visual.py video.mp4 \
  --frames 10 \
  --transcript edit/transcripts/video.json \
  --output edit/visual_analysis.md
```
Requer `ANTHROPIC_API_KEY` no `.env`. O helper extrai frames distribuídos uniformemente,
envia-os para Claude Vision e devolve análise com tipo de conteúdo, momentos notáveis
e recomendações de corte concretas.

### 5. Color grade (opcional, antes do render)
```bash
# Análise automática (recomendado primeiro)
python helpers/grade.py --analyze video.mp4

# Aplicar grade
python helpers/grade.py video.mp4 -o video_graded.mp4 --preset neutral_punch
# Presets: subtle | neutral_punch | warm_cinematic | none
```

### 6. Render
```bash
python helpers/render.py edit/edl.json -o edit/final.mp4

# Preview rápido (720p)
python helpers/render.py edit/edl.json -o edit/preview.mp4 --preview

# Com legendas automáticas
python helpers/render.py edit/edl.json -o edit/final.mp4 --build-subtitles
```

### 7. Verificação visual
Sempre verificar os pontos de corte:
```bash
python helpers/timeline_view.py video.mp4 44.0 47.0 -o edit/verify_cut1.png
```
Inspeciona o PNG: não deve haver saltos visuais nem cliques de áudio.

### 8. Motion graphics com HyperFrames
Após o render base, adicionar overlays:
```bash
# Preview da composição
npx hyperframes preview compositions/overlays/lower_third.html

# Render do overlay
npx hyperframes render compositions/overlays/lower_third.html -o edit/overlay_lower_third.mp4

# Compor overlay por cima do vídeo (com FFmpeg)
ffmpeg -i edit/final.mp4 -i edit/overlay_lower_third.mp4 \
  -filter_complex "[0:v][1:v]overlay=0:0" \
  -c:a copy edit/final_with_overlay.mp4
```

### 9. Memória de sessão
Após cada sessão, append ao `edit/project.md`:
```markdown
## Sessão 2026-04-24
- Vídeo: intro_produto.mp4 (37s, 1080p60)
- Cortes: removidas 3 palavras de preenchimento, 1 retake (12s–18s)
- Grade: neutral_punch
- Legendas: sim, chunks de 2 palavras
- Resultado: final.mp4 (31s)
- Pendente: ajustar overlay do logo no fim
```

---

## 12 Regras Não Negociáveis

1. **Legendas aplicadas POR ÚLTIMO** — depois de todos os overlays, ou ficam escondidas
2. **Extração por segmento + concat lossless** — nunca single-pass filtergraph
3. **Fades de áudio de 30ms nas junções** — previne cliques
4. **Overlays usam `setpts=PTS-STARTPTS+T/TB`** — alinhamento correto de frames
5. **SRT master usa offsets da timeline de output** — legendas alinhadas após concat
6. **Cortar apenas em word boundaries** — nunca a meio de uma palavra
7. **Padding de 30–200ms nas bordas do corte** — absorve drift da transcrição
8. **ASR verbatim word-level** — preservar todas as pausas e marcadores de filler
9. **Cache de transcrições por source** — nunca re-transcrever ficheiros inalterados
10. **Sub-agentes paralelos para animações** — spawnar todos de uma vez, não sequencialmente
11. **Confirmar estratégia antes de executar** — sempre obter aprovação do utilizador
12. **Todos os outputs em `edit/`** — nunca dentro do diretório do projeto raiz

---

## Estratégia de Edição (Audio-First)

- Candidatos a corte: boundaries de fala + silêncios ≥ 400ms
- Handoffs entre speakers: 400–600ms de ar
- Preservar picos (risos, punch lines)
- Verificar cortes em AMBAS as tracks (áudio + vídeo)
- Padding 50–80ms (context-dependent)
- Cada corte deve resultar numa transição de áudio limpa

---

## Formatos de Qualidade

| Modo | Resolução | Preset | CRF |
|---|---|---|---|
| `--preview` | 720p | ultrafast | 28 |
| default | 1080p | fast | 20 |
| `--hq` | 1080p | slow | 18 |

---

## Normalização de Loudness (padrão broadcast)

- Integrated loudness: **-14 LUFS**
- Peak: **-1 dBTP**
- LRA: **11 LU**

Compatível com YouTube, Instagram, TikTok, LinkedIn.

---

## Variáveis de Ambiente Necessárias

```bash
ELEVENLABS_API_KEY=...   # https://elevenlabs.io/app/settings/api-keys
```

Criar ficheiro `.env` em `video-studio/` com estas variáveis.
