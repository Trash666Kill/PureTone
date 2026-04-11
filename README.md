# PureTone

**PureTone** é uma ferramenta de linha de comando para converter arquivos DSD (`.dsf`) e ISOs de SACD em formatos de áudio de alta qualidade — WAV, WavPack e FLAC — com controle preciso de volume, reamostragem de alta fidelidade e geração de visualizações de espectro.

---

## Sumário

- [Visão Geral](#visão-geral)
- [Dependências](#dependências)
- [Instalação e Build](#instalação-e-build)
- [Fluxo de Processamento](#fluxo-de-processamento)
- [Modos de Entrada](#modos-de-entrada)
- [Ajuste de Volume](#ajuste-de-volume)
  - [Modo `auto`: Compensação DSD → PCM](#modo-auto-compensação-dsd--pcm)
  - [Verificação de Headroom e Ajuste Uniforme](#verificação-de-headroom-e-ajuste-uniforme)
  - [Volume Increase](#volume-increase)
  - [Addition](#addition)
  - [Volume Final](#volume-final)
  - [Modo `loudnorm` (padrão sem `--volume`)](#modo-loudnorm-padrão-sem---volume)
  - [Modo fixo](#modo-fixo)
- [Reamostragem](#reamostragem)
- [Visualizações](#visualizações)
- [Metadados FLAC](#metadados-flac)
- [Paralelismo](#paralelismo)
- [Referência de Argumentos](#referência-de-argumentos)
- [Exemplos de Uso](#exemplos-de-uso)
- [Estrutura de Saída](#estrutura-de-saída)
- [Logs e Relatórios](#logs-e-relatórios)

---

## Visão Geral

O DSD (Direct Stream Digital) é o formato de áudio usado em SACDs, com taxas de amostragem altíssimas (2,8 MHz / 5,6 MHz) representadas em 1 bit. A conversão para PCM de alta resolução não é trivial: o processo de decimação filtragem introduz mudanças de nível e exige correções precisas para preservar a dinâmica original.

O PureTone resolve isso com um pipeline em três estágios:

```
[DSD / ISO] → Extração → Reamostragem + Ajuste de Volume → [WAV / WavPack / FLAC]
```

---

## Dependências

| Dependência | Função |
|---|---|
| `ffmpeg` | Conversão, reamostragem, análise de volume e geração de visualizações |
| `ffprobe` | Inspeção de metadados dos arquivos de entrada |
| `metaflac` | Escrita de tags em arquivos FLAC |
| `sacd_extract` | Extração de DSFs a partir de ISOs de SACD (embutido no binário ou no PATH do sistema) |

---

## Instalação e Build

O PureTone pode ser executado diretamente via Python ou compilado em um binário único e portátil com [Nuitka](https://nuitka.net/).

### Dependências do sistema

```bash
sudo apt install gcc ccache build-essential patchelf \
    python3 python3-dev python3-pip \
    libpython3-dev python3-venv
```

### Ambiente virtual e compilação

```bash
# Criar e ativar o ambiente virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependências Python
pip install nuitka zstandard

# Compilar o binário portátil
python3 -m nuitka \
    --onefile \
    --product-name=puretone \
    --product-version=1.0.0 \
    --onefile-tempdir-spec="{CACHE_DIR}/{PRODUCT}/{VERSION}" \
    --include-data-files=bin/sacd_extract=bin/sacd_extract \
    --output-filename=puretone \
    --output-dir=dist \
    --assume-yes-for-downloads \
    --remove-output \
    puretone.py
```

O binário gerado em `dist/puretone` inclui o `sacd_extract` embutido e não depende de nenhum ambiente Python externo.

---

## Fluxo de Processamento

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Entrada do usuário                         │
│              .iso  /  .dsf  /  diretório com .dsf                   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │   Extração de ISO (SACD)   │  ← sacd_extract --2ch-tracks --output-dsf
              │   (apenas se entrada .iso) │
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │   Análise de volume (auto) │  ← ffmpeg volumedetect + astats
              │   por arquivo / diretório  │
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  Reamostragem + Volume     │  ← ffmpeg aresample (soxr) + volume=
              │  (WAV intermediário 24-bit)│     ou loudnorm (2 passes)
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  Codificação final         │  ← WAV / WavPack / FLAC
              │  + metadados (FLAC)        │
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  Visualização (opcional)   │  ← showspectrumpic / showwavespic
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  Limpeza de temporários    │  ← DSF, WAV intermediário, /tmp/*
              └─────────────────────────────┘
```

---

## Modos de Entrada

### Arquivo ISO (`.iso`)

O PureTone localiza o binário `sacd_extract` (primeiro no caminho embutido `bin/sacd_extract`, depois no PATH do sistema) e extrai as faixas de 2 canais em formato DSF:

```
<output_dir>/
└── <nome_do_iso>/
    ├── dsf/          ← DSFs extraídos (removidos ao final, salvo com --keep-dsf)
    └── flac/         ← (ou wv/ ou wvpk/) arquivos convertidos
```

### Arquivo DSF (`.dsf`)

Processamento direto. Com `--volume auto`, o cálculo de compensação é feito individualmente antes da conversão.

### Diretório

O PureTone busca arquivos `.dsf` no diretório raiz e em **cada subdiretório** que contenha DSFs. O ajuste de volume automático é calculado **por grupo** (raiz e cada subdiretório são tratados separadamente), preservando a relação de volume entre faixas de um mesmo álbum.

---

## Ajuste de Volume

Esta é a parte mais sofisticada do PureTone. O objetivo é corrigir automaticamente a perda de nível que ocorre na conversão DSD → PCM, e opcionalmente maximizar o volume dentro de um limite de headroom seguro.

---

### Modo `auto`: Compensação DSD → PCM

A decimação DSD para PCM via `ffmpeg` altera o nível de pico do sinal. Para cada arquivo de entrada, o PureTone mede os picos antes e depois da conversão usando `ffmpeg volumedetect`:

Seja:

- $V_{DSD}$ = volume máximo medido do arquivo DSD original (em dBFS)
- $V_{WAV}$ = volume máximo medido do WAV temporário gerado pela reamostragem (em dBFS)

A **compensação de conversão** para cada arquivo $i$ é:

$$y_i = -(V_{WAV,i} - V_{DSD,i}) = V_{DSD,i} - V_{WAV,i}$$

> **Interpretação:** se a conversão reduziu o nível em 3 dB (i.e., $V_{WAV} = V_{DSD} - 3$), então $y = +3\,\text{dB}$, e esse valor é aplicado como ganho para restaurar o nível original.

---

### Verificação de Headroom e Ajuste Uniforme

Após calcular $y_i$ para todos os arquivos do grupo, o PureTone determina o **volume ajustado resultante** de cada faixa:

$$V_{adj,i} = V_{WAV,i} + y_i$$

Note que, por definição, $V_{adj,i} = V_{DSD,i}$. O nível mais alto do grupo é:

$$V_{max} = \max_i \left( V_{adj,i} \right)$$

Se $V_{max}$ ultrapassar o **headroom limit** $H$ (padrão: $-0{,}5\,\text{dBFS}$):

$$V_{max} > H$$

é aplicado um **ajuste uniforme** (o mesmo para todos os arquivos do grupo):

$$\Delta = H - V_{max}$$

O ajuste final para cada arquivo passa a ser:

$$y'_i = y_i + \Delta$$

Isso garante que o arquivo mais alto do grupo toque exatamente em $H$, e todos os outros são abaixados proporcionalmente, mantendo os níveis relativos entre as faixas do álbum.

Se $V_{max} \leq H$, nenhum ajuste uniforme é necessário e cada arquivo usa seu próprio $y_i$:

$$y'_i = y_i$$

---

### Volume Increase

Quando `--volume auto` está ativo e **nenhum** `--addition` foi especificado, o PureTone verifica se **todas** as faixas possuem headroom suficiente para um ganho adicional.

Seja $G$ o aumento desejado (`--volume-increase`, padrão: $1\,\text{dB}$). A condição verificada é:

$$\forall i:\quad V_{WAV,i} + G \leq H$$

Se a condição for satisfeita para todas as faixas, o ganho $G$ é somado ao ajuste de cada arquivo:

$$y'_i = y_i + G \quad \text{(ou } y_i + \Delta + G \text{ se houve ajuste uniforme)}$$

Se qualquer faixa não tiver headroom suficiente, o `volume-increase` **não é aplicado** e o fluxo segue o padrão.

> **Raciocínio:** o `volume-increase` só faz sentido como um bloco — ou todas as faixas do álbum sobem juntas, ou nenhuma sobe. Aplicar em apenas algumas faixas quebraria a coerência de nível do álbum.

---

### Addition

O parâmetro `--addition` (exclusivo do modo `auto`) permite um ganho extra **incondicional**, aplicado por cima de tudo o que foi calculado. Diferente do `volume-increase`, ele não verifica headroom.

$$y_{final,i} = y'_i + A$$

onde $A \geq 0$ é o valor de `--addition` em dB. Valores negativos não são aceitos.

---

### Volume Final

Reunindo todas as etapas, o volume aplicado a cada arquivo é:

$$\boxed{y_{final,i} = y_i + \Delta_{uniform} + G_{increase} + A_{addition}}$$

onde cada termo é opcional e pode ser zero:

| Termo | Símbolo | Condição de aplicação |
|---|---|---|
| Compensação DSD→PCM | $y_i$ | Sempre (modo `auto`) |
| Ajuste uniforme de headroom | $\Delta$ | Se $V_{max} > H$ |
| Volume increase | $G$ | Se `--volume-increase` e todas as faixas têm margem |
| Addition | $A$ | Se `--addition` foi especificado |

Este valor é passado diretamente ao filtro `volume=` do ffmpeg durante a conversão final.

---

### Resumo dos parâmetros de volume

**`--volume`** é o ponto de partida — define a estratégia geral. Com `auto`, toda a lógica de compensação e headroom entra em ação. Com um valor fixo como `3dB`, esse ganho é aplicado a todos os arquivos sem nenhuma análise. Sem `--volume`, o modo `loudnorm` é usado no lugar.

**`--volume-increase`** só tem efeito com `auto`. Representa um ganho extra que o PureTone *tenta* aplicar após os ajustes individuais — mas só o faz se todas as faixas do grupo tiverem headroom suficiente para absorvê-lo. Se uma única faixa não couber, o aumento é descartado para o grupo inteiro. A lógica é de bloco: ou todas as faixas do álbum sobem juntas, ou nenhuma sobe.

**`--addition`** também é exclusivo do `auto`, mas com comportamento oposto: é um ganho extra **incondicional**. Não verifica headroom, não tem condição de grupo — simplesmente soma ao ajuste calculado. Útil quando o álbum está muito baixo e você quer empurrar o nível além do que o algoritmo automático faria.

**`--headroom-limit`** define o teto máximo de pico permitido na saída (padrão: `-0.5 dBFS`). Atua de duas formas: aciona o ajuste uniforme se o arquivo mais alto do grupo ultrapassar esse limite, e serve de guarda para o `volume-increase` — a verificação compara o pico de cada faixa com `headroom-limit` antes de permitir o ganho extra. O valor `-0.5` (em vez de `0`) existe para evitar clipping por erros de arredondamento na codificação final.

---

### Modo `loudnorm` (padrão sem `--volume`)

Quando nenhum `--volume` é especificado, o PureTone aplica normalização de loudness em **dois passes** usando o filtro `loudnorm` do ffmpeg, conforme o padrão EBU R128:

**Passe 1 — Análise:**

O ffmpeg analisa o arquivo e extrai as métricas de loudness integrado:

- $I_{measured}$: loudness integrado medido (LUFS)
- $LRA_{measured}$: faixa dinâmica de loudness (LU)  
- $TP_{measured}$: true peak medido (dBTP)
- $thresh_{measured}$: limiar interno de medição

**Passe 2 — Normalização com ganho linear:**

Com as métricas do passe 1 como parâmetros fixos, o ffmpeg aplica normalização para atingir os alvos:

$$I_{target} = -14\,\text{LUFS} \quad TP_{target} = -1\,\text{dBTP} \quad LRA_{target} = 20\,\text{LU}$$

O ganho aplicado é:

$$G_{loudnorm} = I_{target} - I_{measured}$$

sujeito ao limite de true peak $TP_{target}$. O uso de dois passes garante que a normalização seja linear (sem compressão dinâmica), produzindo um resultado matematicamente exato.

---

### Modo fixo

Com `--volume 3dB` (ou qualquer valor no formato `XdB`), o valor é aplicado diretamente a todas as faixas sem nenhuma análise prévia:

$$y_{final,i} = \text{valor fixo} \quad \forall i$$

---

## Reamostragem

O DSD original opera em 2,8224 MHz (DSD64) ou 5,6448 MHz (DSD128). O PureTone faz a decimação para PCM em 176.400 Hz (padrão) usando o engine **SoX Resampler (soxr)** com configuração de alta qualidade:

| Parâmetro | Padrão | Descrição |
|---|---|---|
| `--sample-rate` | 176400 Hz | Taxa de saída (ex.: 88200, 96000, 192000) |
| `--resampler` | `soxr` | Engine de reamostragem |
| `--precision` | 28 | Precisão do filtro FIR (bits). 28 = qualidade máxima |
| `--cheby` | 1 | Modo Chebyshev: minimiza o ripple de passband ao custo de um rolloff levemente mais suave |
| `--codec` | `pcm_s24le` | Codec PCM de 24 bits, little-endian |

A cadeia de filtros do ffmpeg gerada é:

```
aresample=resampler=soxr:precision=28:cheby=1
```

O arquivo WAV intermediário em 24-bit / 176.4 kHz é então codificado no formato de saída desejado (WAV final, WavPack ou FLAC).

---

## Visualizações

Com `--spectrogram`, o PureTone gera uma imagem PNG para cada arquivo convertido, salva em `<output_dir>/spectrogram/`.

| Tipo | Filtro ffmpeg | Descrição |
|---|---|---|
| `spectrogram` (padrão) | `showspectrumpic` | Espectrograma frequência × tempo em escala logarítmica |
| `waveform` | `showwavespic` | Forma de onda amplitude × tempo |

**Modos do espectrograma:**

- `combined` (padrão): canais L e R sobrepostos em uma única imagem
- `separate`: canais L e R em linhas separadas

**Resolução:**

Padrão `1920x1080`. Pode ser alterada para qualquer valor `WxH` (ex.: `3840x2160` para 4K).

**Sintaxe:**

```bash
# Padrão (1920x1080, spectrogram, combined)
--spectrogram

# Waveform
--spectrogram waveform

# Spectrogram com canais separados
--spectrogram spectrogram separate

# 4K spectrogram com canais separados
--spectrogram 3840x2160 spectrogram separate
```

---

## Metadados FLAC

Ao converter para FLAC, o PureTone escreve automaticamente uma tag `COMMENT` com o histórico completo do processamento usando `metaflac`:

```
DSF > WAV > FLAC, Codec: pcm_s24le, Resampler: soxr with precision 28 and cheby,
Applied Volume: 2.3dB, Compression Level: 12
```

Isso preserva a rastreabilidade do processo diretamente no arquivo de áudio.

**Nível de compressão FLAC:** 0 (mais rápido, arquivo maior) a 12 (mais lento, melhor compressão). FLAC é sempre lossless independente do nível.

---

## Paralelismo

O PureTone processa múltiplos arquivos em paralelo usando `ThreadPoolExecutor`. O número de workers é controlado por `--parallel` (padrão: 2).

> **Nota:** A análise de volume (`--volume auto`) é sempre sequencial por design — ela precisa do conjunto completo de picos para calcular o ajuste uniforme correto. O paralelismo se aplica à etapa de conversão, após o cálculo dos ajustes.

---

## Referência de Argumentos

| Argumento | Padrão | Descrição |
|---|---|---|
| `path` | — | Caminho para `.dsf`, `.iso` ou diretório |
| `--format` | `wav` | Formato de saída: `wav`, `wavpack`, `flac` |
| `--codec` | `pcm_s24le` | Codec do WAV intermediário |
| `--sample-rate` | `176400` | Taxa de amostragem de saída em Hz |
| `--volume` | `None` | `auto`, `analysis` ou valor fixo como `3dB`, `-1.5dB` |
| `--volume-increase` | `1dB` | Ganho extra aplicado quando todas as faixas têm headroom |
| `--addition` | `0dB` | Ganho adicional incondicional (somente com `--volume auto`) |
| `--headroom-limit` | `-0.5` | Pico máximo permitido em dBFS |
| `--loudnorm-I` | `-14` | Alvo de loudness integrado em LUFS |
| `--loudnorm-TP` | `-1` | Limite de true peak em dBTP |
| `--loudnorm-LRA` | `20` | Faixa de loudness alvo em LU |
| `--resampler` | `soxr` | Engine de reamostragem |
| `--precision` | `28` | Precisão do resampler (20–28) |
| `--cheby` | `1` | Modo Chebyshev: `0` ou `1` |
| `--spectrogram` | desativado | Gera visualização (ver sintaxe acima) |
| `--compression-level` | `0` | Compressão: 0–6 para WavPack, 0–12 para FLAC |
| `--parallel` | `2` | Número de jobs paralelos |
| `--log` | `None` | Arquivo de log para salvar relatório de volume |
| `--skip-existing` | `False` | Pula arquivos já convertidos |
| `--keep-dsf` | `False` | Mantém os DSFs extraídos do ISO |
| `--extract-only` | `False` | Apenas extrai DSFs do ISO, sem converter |
| `--output-dir` | dir. do ISO | Diretório de saída (apenas para entrada `.iso`) |
| `--debug` | `False` | Ativa logging detalhado |

---

## Exemplos de Uso

### Converter um ISO de SACD para FLAC

```bash
./puretone --format flac --compression-level 12 --volume auto \
           --volume-increase 2dB --parallel 6 --log log.txt \
           "Michael Jackson - Off The Wall.iso"
```

### Processar um diretório com espectrograma e log

```bash
./puretone --format flac --compression-level 12 --sample-rate 88200 \
           --parallel 6 --volume auto --volume-increase 2dB \
           --spectrogram --log log.txt --keep-dsf \
           /mnt/Music/Albums/
```

### Extrair DSFs do ISO sem converter

```bash
./puretone --extract-only /path/to/album.iso
```

### Converter com ganho fixo

```bash
./puretone --format wavpack --volume 3dB --parallel 4 /path/to/album/
```

### Converter com espectrograma 4K e canais separados

```bash
./puretone --format flac --volume auto \
           --spectrogram 3840x2160 spectrogram separate \
           /path/to/file.dsf
```

### Adicionar ganho extra sobre o auto (útil para álbuns muito baixos)

```bash
./puretone --format flac --volume auto --addition 2dB /path/to/album/
```

---

## Estrutura de Saída

### Entrada: diretório com DSFs

```
<input_dir>/
└── flac/               ← (ou wv/ ou wvpk/)
    ├── track01.flac
    ├── track02.flac
    ├── ...
    └── spectrogram/    ← gerado com --spectrogram
        ├── track01.png
        └── track02.png
```

### Entrada: ISO de SACD

```
<output_dir>/
└── <nome_do_iso>/
    ├── dsf/            ← extraídos temporariamente (removidos salvo --keep-dsf)
    │   └── track01.dsf
    └── flac/
        ├── track01.flac
        └── spectrogram/
            └── track01.png
```

---

## Logs e Relatórios

Com `--log arquivo.txt`, o PureTone grava um relatório detalhado incluindo:

- Valores de $V_{DSD}$, $V_{WAV}$ e $y$ por arquivo
- Ajuste uniforme aplicado (se houver)
- Volume final aplicado a cada faixa
- Tabela resumo ao final do processamento

O log também é exibido no terminal ao final da execução:

```
=== Volume Adjustment Summary ===
File                                              y (dB) ffmpeg   WAV Max Volume (dB)   Applied Volume (dB)
────────────────────────────────────────────────────────────────────────────────────────────────────────────
/path/track01.dsf                                    2.3              -3.1                   2.3dB
/path/track02.dsf                                    1.8              -2.6                   1.8dB
```

Todos os arquivos temporários (`/tmp/puretone_<pid>_*`) são removidos automaticamente ao final ou em caso de interrupção via `SIGINT`/`SIGTERM`.
