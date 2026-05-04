Analisa a transcrição, propõe cortes e — após aprovação — renderiza o vídeo final.

Passos:
1. Lê `edit/takes_packed.md`. Se não existir, diz ao utilizador para correr `/transcrever` primeiro.
2. Analisa o conteúdo e identifica:
   - Palavras de preenchimento ("hmm", "tipo", "pronto", "então", "basicamente")
   - Pausas longas (≥ 400ms entre frases)
   - Retakes e repetições
3. Propõe uma estratégia de cortes em 4–8 frases, clara e concisa.
4. **Aguarda aprovação do utilizador antes de continuar.**
5. Após aprovação, gera `edit/edl.json` com os segmentos aprovados. Inclui campos `beat`, `quote` e `reason` em cada segmento.
6. Pergunta ao utilizador:
   - Que grade pretende? (subtle / neutral_punch / warm_cinematic / none)
   - O vídeo é HDR? (para usar flag --hdr)
   - Quer legendas automáticas?
7. Renderiza:
   ```bash
   .venv/bin/python helpers/render.py edit/edl.json -o edit/final.mp4 [--hdr] [--build-subtitles]
   ```
8. Mostra o resumo: duração final, número de cortes, ficheiro gerado.
9. Pergunta se quer registar a sessão com `/sessao`.
