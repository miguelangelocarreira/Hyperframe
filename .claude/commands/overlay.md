Renderiza um overlay HyperFrames e compõe-o sobre o vídeo final.

Passos:
1. Lista as composições disponíveis em `compositions/overlays/`:
   - `lower_third.html` — barra de nome/título
   - `stat_counter.html` — contador animado de estatísticas
   - `subtitles_karaoke.html` — legendas karaoke word-level
2. Pergunta ao utilizador qual composição quer usar e em que intervalo de tempo (start–end em segundos).
3. Verifica se o `npx hyperframes` está disponível:
   ```bash
   npx hyperframes --version
   ```
   Se não estiver, instala: `npm install -g @hyperframes/cli`
4. Faz preview da composição:
   ```bash
   npx hyperframes preview compositions/overlays/<ficheiro>.html
   ```
5. Renderiza o overlay para MP4:
   ```bash
   npx hyperframes render compositions/overlays/<ficheiro>.html -o edit/overlay_<nome>.mp4
   ```
6. Compõe o overlay sobre o vídeo base usando FFmpeg:
   ```bash
   ffmpeg -i edit/final.mp4 -i edit/overlay_<nome>.mp4 \
     -filter_complex "[0:v][1:v]overlay=0:0" \
     -c:a copy edit/final_with_overlay.mp4
   ```
7. Informa o utilizador do ficheiro gerado.

Nota: se o utilizador quiser adicionar o overlay diretamente no EDL (antes do render), edita `edit/edl.json` adicionando a chave `overlays` com `source`, `start` e `end`.
