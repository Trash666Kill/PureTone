#!/usr/bin/env python3
import subprocess
import os
import argparse
import logging
import time
import sys
import signal
import shutil
import termios  # Adicionado
import tty      # Adicionado
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

# Salvar o estado do terminal no início
ORIGINAL_TERMINAL_STATE = None
if sys.stdin.isatty():
    ORIGINAL_TERMINAL_STATE = termios.tcgetattr(sys.stdin)

# Configuração de logging
START_TIME = time.time()
logging.basicConfig(
    format='[%(relativeCreated)d] [%(levelname)s] %(message)s',
    level=logging.INFO
)
logger = logging.getLogger('downmix')

# Classe de configuração
class DownmixConfig:
    def __init__(self):
        self.FLAC_COMPRESSION = '12'  # Padrão para compressão FLAC
        self.CHANNELS = 2
        self.OVERWRITE = True
        self.SKIP_EXISTING = False
        self.PARALLEL_JOBS = 2
        self.CODEC = 's32'  # Padrão para codec (24-bit)
        self.SAMPLE_RATE = '192000'  # Padrão para sample rate (192 kHz)

CONFIG = DownmixConfig()

# Diretório de saída
OUTPUT_DIR = 'flac'

# Arquivos temporários
TEMP_FILES = {
    'INFO_LOG': f"/tmp/downmix_{os.getpid()}_info.log"
}

def run_command(cmd: List[str], capture_output: bool = True, debug: bool = False) -> Tuple[str, str, int]:
    if debug:
        logger.debug(f"Executing command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture_output, text=True)
    if result.returncode != 0:
        logger.error(f"Command failed with return code {result.returncode}: {result.stderr}")
    return result.stdout, result.stderr, result.returncode

def convert_mlp_to_flac(input_file: str, output_file: str, codec: str, sample_rate: str, compression_level: str, debug: bool = False) -> bool:
    """Converte arquivo MLP para FLAC usando valores fornecidos."""
    try:
        command = [
            'ffmpeg', '-y', '-i', str(input_file),
            '-c:a', 'flac', '-compression_level', compression_level,
            '-sample_fmt', codec, '-ar', sample_rate
        ]
        command.append(str(output_file))
        
        stdout, stderr, rc = run_command(command, debug=debug)
        if rc != 0:
            logger.error(f"Erro ao converter MLP {input_file}")
            if debug:
                logger.debug(f"Saída FFmpeg: {stdout}\nErro FFmpeg: {stderr}")
            return False

        logger.info(f"Arquivo MLP convertido para FLAC: {output_file}")
        return True
    except Exception as e:
        logger.error(f"Erro inesperado ao converter MLP {input_file}: {e}")
        return False

def downmix_flac(input_file: str, output_file: str, codec: str, sample_rate: str, compression_level: str, debug: bool = False) -> bool:
    """Faz downmix de arquivo FLAC para 2 canais usando valores fornecidos."""
    try:
        command = [
            'ffmpeg', '-y', '-i', str(input_file),
            '-c:a', 'flac', '-compression_level', compression_level,
            '-ac', str(CONFIG.CHANNELS), '-sample_fmt', codec, '-ar', sample_rate
        ]
        command.append(str(output_file))
        
        stdout, stderr, rc = run_command(command, debug=debug)
        if rc != 0:
            logger.error(f"Erro ao fazer downmix de {input_file}")
            if debug:
                logger.debug(f"Saída FFmpeg: {stdout}\nErro FFmpeg: {stderr}")
            return False

        logger.info(f"Arquivo FLAC downmixed: {output_file}")
        return True
    except Exception as e:
        logger.error(f"Erro inesperado ao fazer downmix de {input_file}: {e}")
        return False

def process_file(input_file: str, output_dir: str, codec: str, sample_rate: str, compression_level: str, debug: bool = False) -> bool:
    """Processa um arquivo MLP: converte para FLAC intermediário e faz downmix, mantendo o nome da fonte."""
    logger.debug(f"Processando arquivo: {input_file}")
    base_name = Path(input_file).stem
    intermediate_flac = os.path.join(output_dir, f"{base_name}_pcm.flac")  # Arquivo intermediário
    output_flac = os.path.join(output_dir, f"{base_name}.flac")  # Arquivo final com nome da fonte

    os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(output_flac):
        if CONFIG.SKIP_EXISTING:
            logger.info(f"Pulando {input_file}: {output_flac} já existe (--skip-existing ativado)")
            return True
        elif not CONFIG.OVERWRITE:
            logger.info(f"Pulando {input_file}: {output_flac} já existe e OVERWRITE não está ativado")
            return True

    # Converte MLP para FLAC intermediário
    success = convert_mlp_to_flac(input_file, intermediate_flac, codec, sample_rate, compression_level, debug)
    if not success:
        return False

    # Faz downmix do FLAC intermediário para o nome final
    success = downmix_flac(intermediate_flac, output_flac, codec, sample_rate, compression_level, debug)
    if not success:
        if os.path.exists(intermediate_flac):
            os.remove(intermediate_flac)
        return False

    # Remove o arquivo intermediário após o downmix
    if os.path.exists(intermediate_flac):
        try:
            os.remove(intermediate_flac)
            logger.debug(f"Removido arquivo intermediário: {intermediate_flac}")
        except Exception as e:
            logger.error(f"Falha ao remover arquivo intermediário {intermediate_flac}: {e}")

    return True

def process_files_in_parallel(files: List[str], output_dir: str, codec: str, sample_rate: str, compression_level: str, debug: bool = False) -> bool:
    """Processa arquivos em paralelo usando ThreadPoolExecutor."""
    logger.info(f"Iniciando processamento paralelo com {CONFIG.PARALLEL_JOBS} trabalhadores para {len(files)} arquivos")
    with ThreadPoolExecutor(max_workers=CONFIG.PARALLEL_JOBS) as executor:
        results = [executor.submit(process_file, file, output_dir, codec, sample_rate, compression_level, debug) for file in files]
        outcomes = [future.result() for future in results]
    success = all(outcomes)
    logger.info(f"Concluído processamento paralelo para {len(files)} arquivos. Sucesso: {success}")
    return success

def cleanup(signum=None, frame=None):
    """Remove arquivos temporários e finaliza o script."""
    elapsed_time = int(time.time() - START_TIME)
    logger.info(f"Script interrompido após {elapsed_time} segundos. Limpando arquivos temporários...")
    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                logger.debug(f"Removido arquivo temporário: {temp_file}")
            except Exception as e:
                logger.error(f"Falha ao remover {temp_file}: {e}")
    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)
    logger.info("Limpeza concluída. Saindo.")
    sys.exit(1)

def main():
    description = """
Downmix - Conversor de MLP para FLAC com Downmix Estéreo

Descrição:
----------
Downmix é um script Python que converte arquivos MLP para FLAC com compressão ajustável, e faz downmix automático para estéreo. Suporta arquivos únicos ou diretórios, com processamento paralelo para maior eficiência. O arquivo final mantém o nome da fonte com extensão .flac.

Fluxo de Funcionamento:
-----------------------
1. **Validação de Dependências**: Verifica se ffmpeg está instalado.
2. **Análise de Caminho**: Aceita um arquivo .mlp ou diretório como entrada.
3. **Processamento**:
   - Converte MLP para FLAC intermediário (_pcm.flac) com compressão, codec e sample rate fornecidos.
   - Faz downmix para estéreo, salvando como <nome_original>.flac.
   - Remove arquivo intermediário (_pcm.flac).
4. **Saída**: Salva arquivos em subdiretório 'flac' (ex.: track-01-01[1]-03-[L-R]-24-192000.flac).
5. **Limpeza**: Remove arquivos temporários e restaura o terminal ao finalizar ou em caso de interrupção.

Valores Padrão:
---------------
- Formato de saída: FLAC
- Compressão FLAC (--compression-level): 12
- Canais para downmix: 2 (estéreo)
- Codec (--codec): s32 (24-bit)
- Sample rate (--sample-rate): 192000 Hz
- Pular existentes (--skip-existing): False
- Número de tarefas paralelas (--parallel): 2
- Modo depuração (--debug): False

Exemplos:
---------
1. Converter um único arquivo MLP com padrões:
   ./downmix.py /path/to/file.mlp

2. Converter todos os arquivos MLP em um diretório com compressão 8, codec s32 e sample rate 192000:
   ./downmix.py --compression-level 8 --codec s32 --sample-rate 192000 /path/to/directory

3. Ativar modo depuração para logs detalhados:
   ./downmix.py --debug /path/to/directory

4. Processar em paralelo com 4 trabalhadores e compressão 5:
   ./downmix.py --parallel 4 --compression-level 5 /path/to/directory
"""

    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )

    parser.add_argument('-h', '--help', action='help', help="Mostra esta mensagem de ajuda e sai.")
    parser.add_argument('path', nargs='?', default=os.getcwd(), help="Caminho para um arquivo .mlp ou diretório (padrão: diretório atual)")
    parser.add_argument('--codec', default='s32', help="Formato de amostra para saída FLAC (ex.: s32, s16). Padrão: s32")
    parser.add_argument('--sample-rate', default='192000', help="Taxa de amostragem em Hz (ex.: 192000, 96000). Padrão: 192000")
    parser.add_argument('--compression-level', type=str, default='12', help="Nível de compressão FLAC (0-12). Padrão: 12")
    parser.add_argument('--parallel', type=int, help=f"Número de tarefas paralelas (padrão: {CONFIG.PARALLEL_JOBS})")
    parser.add_argument('--skip-existing', action='store_true', help="Pula arquivos se a saída já existir (padrão: False)")
    parser.add_argument('--debug', action='store_true', help="Ativa logs de depuração, incluindo comandos executados (padrão: False)")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.parallel:
        CONFIG.PARALLEL_JOBS = max(1, args.parallel)
    if args.skip_existing:
        CONFIG.SKIP_EXISTING = True
    CONFIG.CODEC = args.codec
    CONFIG.SAMPLE_RATE = args.sample_rate
    CONFIG.FLAC_COMPRESSION = args.compression_level

    # Verificar dependências
    if not shutil.which('ffmpeg'):
        logger.error("ffmpeg não encontrado. Por favor, instale-o.")
        sys.exit(1)

    # Inicializar arquivos temporários
    for temp_file in TEMP_FILES.values():
        with open(temp_file, 'w'): pass

    path = Path(args.path)
    start_time = time.time()
    success = True

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    if not path.exists():
        logger.error(f"Caminho não existe: {args.path}")
        sys.exit(1)

    if path.is_file() and path.suffix.lower() == '.mlp':
        output_dir = os.path.join(path.parent, OUTPUT_DIR)
        success = process_file(str(path), output_dir, CONFIG.CODEC, CONFIG.SAMPLE_RATE, CONFIG.FLAC_COMPRESSION, args.debug)
    elif path.is_dir():
        os.chdir(path)
        files = [str(f) for f in Path('.').glob('*.mlp')]
        subdirs = [d for d in Path('.').glob('*') if d.is_dir() and any(f.suffix.lower() == '.mlp' for f in d.glob('*.mlp'))]

        if files:
            logger.info(f"Processando diretório: {path}")
            success &= process_files_in_parallel(files, os.path.join(path, OUTPUT_DIR), CONFIG.CODEC, CONFIG.SAMPLE_RATE, CONFIG.FLAC_COMPRESSION, args.debug)
        if subdirs:
            logger.info(f"Processando subdiretórios em {path}: {', '.join(str(s) for s in subdirs)}")
            for subdir in subdirs:
                subdir_files = [str(f) for f in subdir.glob('*.mlp')]
                success &= process_files_in_parallel(subdir_files, os.path.join(subdir, OUTPUT_DIR), CONFIG.CODEC, CONFIG.SAMPLE_RATE, CONFIG.FLAC_COMPRESSION, args.debug)
        if not files and not subdirs:
            logger.error(f"Nenhum arquivo .mlp encontrado em {path} ou seus subdiretórios")
            success = False
    else:
        logger.error(f"Caminho inválido: {args.path}")
        sys.exit(1)

    elapsed_time = int(time.time() - start_time)
    if success:
        logger.info("Processo concluído com sucesso!")
    else:
        logger.error("Processo concluído com erros!")
    logger.info(f"Tempo decorrido: {elapsed_time} segundos")

    # Limpeza final
    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            os.remove(temp_file)

    # Restaurar o estado do terminal
    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)

if __name__ == "__main__":
    main()