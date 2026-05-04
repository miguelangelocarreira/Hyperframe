Regista um resumo desta sessão de edição em `edit/project.md`.

Passos:
1. Recolhe automaticamente a informação disponível:
   - Nome do vídeo source (de `edit/edl.json` se existir)
   - Número de segmentos e duração total (calculado a partir do EDL)
   - Grade utilizada (do EDL)
   - Se foram geradas legendas (do EDL)
   - Ficheiro de output gerado em `edit/`
2. Pergunta ao utilizador:
   - Breve descrição dos cortes feitos (ex: "3 fillers removidos, 1 retake de 8s")
   - Notas pendentes para a próxima sessão (opcional)
3. Regista com `session_log.py`:
   ```bash
   .venv/bin/python helpers/session_log.py \
     "<video> (<duração>, <resolução>)" \
     "<descrição dos cortes>" \
     "<grade>" \
     "<resultado>" \
     [--subtitles] \
     [--pending "<notas>"] \
     --edit-dir edit
   ```
4. Mostra o conteúdo adicionado ao `edit/project.md`.
