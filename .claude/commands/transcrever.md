Transcreve todos os vídeos em `input/` que ainda não tenham transcrição em cache.

Passos:
1. Verifica se existe o ficheiro `.env` com `ELEVENLABS_API_KEY`. Se não existir, informa o utilizador e para.
2. Lista os ficheiros de vídeo em `input/` (extensões: .mp4, .mov, .avi, .mkv).
3. Se houver mais do que um vídeo, usa `transcribe_batch.py` com 4 workers paralelos:
   ```bash
   .venv/bin/python helpers/transcribe_batch.py input/ --edit-dir edit
   ```
4. Se houver apenas um vídeo, usa `transcribe.py`:
   ```bash
   .venv/bin/python helpers/transcribe.py input/<ficheiro> --edit-dir edit
   ```
5. Após a transcrição, corre `pack_transcripts.py` para gerar o resumo legível:
   ```bash
   .venv/bin/python helpers/pack_transcripts.py --edit-dir edit
   ```
6. Mostra o conteúdo de `edit/takes_packed.md` ao utilizador e pergunta se quer prosseguir para a análise de cortes.
