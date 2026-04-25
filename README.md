# Hyperframe — AI Video Editing Pipeline

Pipeline completo de edição de vídeo com IA: transcrição → cortes → motion graphics → render final.

## Stack

| Ferramenta | Papel |
|---|---|
| **ElevenLabs Scribe** | Transcrição word-level com timestamps |
| **FFmpeg** | Cortes, color grade, concat, loudness |
| **HyperFrames** | Motion graphics HTML→MP4 |
| **Python helpers** | Orquestração do pipeline |

## Estrutura

```
├── CLAUDE.md                          # Instruções para o agente AI
├── .env.example                       # Variáveis de ambiente necessárias
├── pyproject.toml                     # Dependências Python
├── edit/                              # Outputs do pipeline (transcripts, EDL, final)
├── helpers/
│   ├── transcribe.py                  # Transcrição via ElevenLabs Scribe
│   ├── pack_transcripts.py            # Agrupa palavras em frases legíveis
│   ├── grade.py                       # Color grade automático via FFmpeg
│   ├── render.py                      # Render final baseado em EDL
│   └── timeline_view.py               # Verificação visual de cortes
└── compositions/
    └── overlays/
        ├── lower_third.html           # Overlay: barra com nome e cargo
        ├── subtitles_karaoke.html     # Overlay: legendas karaoke word-level
        └── stat_counter.html          # Overlay: contador de estatísticas animado
```

## Setup

```bash
cp .env.example .env
# Preenche ELEVENLABS_API_KEY em .env
pip install -e .
```

## Uso

Ver [CLAUDE.md](CLAUDE.md) para instruções completas do pipeline.
