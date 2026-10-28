# Limpa Metadados

Versão local, inspirada no DeleteFootprints.ai, para remover metadados de imagens
(EXIF, GPS, IPTC, XMP, C2PA/"Feito com IA" e textos de PNG) **sem recomprimir e sem
alterar os pixels**. Nada sai do seu computador.

## Como rodar

Precisa só do Python 3.9 ou mais novo, sem instalar nenhuma biblioteca.

```bash
python3 -m metaclean            # abre a interface em http://127.0.0.1:8765
```

No Windows use `py -m metaclean`. Arraste até 5 imagens, veja os metadados (os sinais
de IA aparecem primeiro, com o motivo), clique em **Remover todos os metadados** e baixe.

Também funciona pela linha de comando:

```bash
python3 -m metaclean inspect foto.jpg
python3 -m metaclean clean *.jpg -o limpas/          # cria foto_limpo.jpg
python3 -m metaclean clean foto.jpg --sem-orientacao # remove até a tag Orientation
```

## O que é removido e o que é mantido

| Formato | Removido | Mantido |
|---|---|---|
| JPEG | APP1 (EXIF, XMP, XMP estendido), APP13 (IPTC/Photoshop), APP11 (C2PA/JUMBF), MPF, comentários, outros APPn, dados após o fim da imagem | JFIF, perfil de cor ICC, bloco Adobe (cores) e todos os dados de imagem, byte a byte |
| PNG | tEXt, zTXt, iTXt (inclui prompts do Stable Diffusion/ComfyUI), eXIf, caBX (C2PA), tIME e blocos desconhecidos | blocos de imagem, cor, transparência, DPI e animação |
| WebP | EXIF, XMP, C2PA e blocos desconhecidos | imagem, alfa, animação e ICC |
| TIFF/HEIC | tudo, via [exiftool](https://exiftool.org) (opcional) | tags estruturais e ICC |

A tag **Orientation** é mantida por padrão para a foto do celular não aparecer
deitada. Desmarque a opção na interface (ou use `--sem-orientacao`) para tirar também.

Em fotos HDR (Ultra HDR, gain map) a parte HDR fica em dados extras do arquivo e é
removida; a imagem continua normal, só sem o realce HDR.

## Detecção de IA

Marcamos como sinal de IA o que plataformas como Instagram e Facebook usam para
aplicar o rótulo de IA: manifestos C2PA (Content Credentials), `DigitalSourceType`
do IPTC (`trainedAlgorithmicMedia` e variações), `dcterms:provenance` e assinaturas
de geradores (OpenAI/DALL·E, Midjourney, Firefly, Stable Diffusion, ComfyUI, Gemini/Imagen,
Meta AI e outros). Marcas d'água nos pixels, como o SynthID, não são metadados e não
são removidas.

## Estrutura

```
metaclean/
  core.py       detecção do formato, leitura e limpeza de JPEG, PNG e WebP
  parsers.py    leitores de EXIF/TIFF, XMP, IPTC, C2PA e textos PNG
  flags.py      classificação: IA, localização, aparelho e autoria
  exiftool.py   suporte opcional a TIFF e HEIC
  server.py     servidor local (só aceita conexões de 127.0.0.1)
  static/       interface web
tests/          testes (usam Pillow só para comparar pixels)
```

Testes: `python3 -m unittest discover -s tests -t .` (com `pip install pillow`).
