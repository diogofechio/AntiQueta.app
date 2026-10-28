# AntiQueta.IA

**Tire a etiqueta das suas imagens.** Remove o selo "Feito com IA" (C2PA), localização
GPS, dados do aparelho e demais metadados (EXIF, IPTC, XMP, textos de PNG) **sem
recomprimir e sem alterar os pixels**. Nada sai do seu computador.

## Como usar

1. Baixe a versão do seu sistema na página de [Releases](../../releases/latest):
   - **Windows:** `AntiQueta.IA-windows.exe`
   - **macOS:** `AntiQueta.IA-macos.zip` (descompacte)
   - **Linux:** `AntiQueta.IA-linux.tar.gz` (descompacte)
2. Abra o arquivo com dois cliques. O app abre sozinho no navegador.
3. Arraste até 5 imagens, confira o que cada uma revela e clique em
   **Remover metadados de todas**. Depois é só baixar.

Uma janela de terminal fica aberta enquanto o app roda; feche-a para encerrar.

**Na primeira vez**, o sistema pode avisar que o app é de um desenvolvedor não
identificado (o executável não tem assinatura digital paga):

- **Windows:** em "O Windows protegeu o computador", clique em **Mais informações** e
  depois em **Executar assim mesmo**.
- **macOS:** clique com o botão direito no app e escolha **Abrir**. Se não aparecer a
  opção, vá em **Ajustes do Sistema › Privacidade e Segurança** e clique em
  **Abrir Mesmo Assim**.

## Rodar pelo código-fonte

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

## Gerar o executável

Localmente: `pip install pyinstaller` e `python build.py` (o resultado fica em `dist/`).
Se existir `assets/icone.ico` (Windows) ou `assets/icone.icns` (macOS), ele vira o ícone.

Para publicar uma versão nova, crie e envie uma tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

O GitHub Actions ([.github/workflows/release.yml](.github/workflows/release.yml)) roda os
testes, gera os executáveis de Windows, macOS e Linux e os anexa ao Release.
