#!/usr/bin/env python3
import subprocess
import os
import argparse
import logging
import time
import sys
import signal
import shutil
import termios
import tty
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

ORIGINAL_TERMINAL_STATE = None
if sys.stdin.isatty():
    ORIGINAL_TERMINAL_STATE = termios.tcgetattr(sys.stdin)

START_TIME = time.time()
logging.basicConfig(
    format='[%(relativeCreated)d] [%(levelname)s] %(message)s',
    level=logging.INFO
)
logger = logging.getLogger('downmix')

class DownmixConfig:
    def __init__(self):
        self.FLAC_COMPRESSION = '12'
        self.OVERWRITE = True
        self.SKIP_EXISTING = False
        self.PARALLEL_JOBS = 2

CONFIG = DownmixConfig()
OUTPUT_DIR = 'flac'
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
    try:
        command = [
            'ffmpeg', '-y', '-i', str(input_file),
            '-c:a', 'flac', '-compression_level', compression_level,
            '-sample_fmt', codec, '-ar', sample_rate, str(output_file)
        ]
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

def convert_pcm_to_flac(input_file: str, output_file: str, codec: str, sample_rate: str, compression_level: str, debug: bool = False) -> bool:
    try:
        pcm_format = 's16le' if codec == 's16' else 's32le'
        command = [
            'ffmpeg', '-y', '-f', pcm_format, '-ar', sample_rate, '-i', str(input_file),
            '-c:a', 'flac', '-compression_level', compression_level,
            '-sample_fmt', codec, '-ar', sample_rate, str(output_file)
        ]
        stdout, stderr, rc = run_command(command, debug=debug)
        if rc != 0:
            logger.error(f"Erro ao converter PCM {input_file}")
            if debug:
                logger.debug(f"Saída FFmpeg: {stdout}\nErro FFmpeg: {stderr}")
            return False
        logger.info(f"Arquivo PCM convertido para FLAC: {output_file}")
        return True
    except Exception as e:
        logger.error(f"Erro inesperado ao converter PCM {input_file}: {e}")
        return False

def downmix_flac(input_file: str, output_file: str, codec: str, sample_rate: str, compression_level: str, channels: int, debug: bool = False) -> bool:
    try:
        command = [
            'ffmpeg', '-y', '-i', str(input_file),
            '-c:a', 'flac', '-compression_level', compression_level,
            '-ac', str(channels), '-sample_fmt', codec, '-ar', sample_rate, str(output_file)
        ]
        stdout, stderr, rc = run_command(command, debug=debug)
        if rc != 0:
            logger.error(f"Erro ao fazer downmix de {input_file}")
            if debug:
                logger.debug(f"Saída FFmpeg: {stdout}\nErro FFmpeg: {stderr}")
            return False
        logger.info(f"Arquivo FLAC downmixed para {channels} canais: {output_file}")
        return True
    except Exception as e:
        logger.error(f"Erro inesperado ao fazer downmix de {input_file}: {e}")
        return False

def apply_flac_metadata(output_file: str, input_format: str, codec: str, compression_level: str, debug: bool = False) -> bool:
    comment_content = f"{input_format.upper()} > FLAC, Codec: {codec}, Compression Level: {compression_level}"
    metaflac_cmd = ['metaflac', '--set-tag', f"COMMENT={comment_content}", output_file]
    _, stderr, rc = run_command(metaflac_cmd, debug=debug)
    if rc != 0:
        logger.error(f"Failed to apply COMMENT to {output_file}: {stderr}")
        return False
    logger.info(f"Metadados aplicados a {output_file}: {comment_content}")
    return True

def process_file(input_file: str, output_dir: str, codec: str, sample_rate: str, channels: Optional[int], compression_level: str, debug: bool = False) -> bool:
    logger.debug(f"Processando arquivo: {input_file}")
    base_name = Path(input_file).stem
    intermediate_flac = os.path.join(output_dir, f"{base_name}_temp.flac")
    output_flac = os.path.join(output_dir, f"{base_name}.flac")
    input_format = Path(input_file).suffix.lower()[1:]

    os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(output_flac):
        if CONFIG.SKIP_EXISTING:
            logger.info(f"Pulando {input_file}: {output_flac} já existe (--skip-existing ativado)")
            return True
        elif not CONFIG.OVERWRITE:
            logger.info(f"Pulando {input_file}: {output_flac} já existe e OVERWRITE não está ativado")
            return True

    if input_format == 'mlp':
        success = convert_mlp_to_flac(input_file, intermediate_flac, codec, sample_rate, compression_level, debug)
    elif input_format == 'pcm':
        success = convert_pcm_to_flac(input_file, intermediate_flac, codec, sample_rate, compression_level, debug)
    else:
        logger.error(f"Formato de arquivo não suportado: {input_file}")
        return False

    if not success:
        return False

    if channels is not None:
        # Realiza downmix se channels for especificado
        success = downmix_flac(intermediate_flac, output_flac, codec, sample_rate, compression_level, channels, debug)
    else:
        # Sem downmix, apenas move o arquivo temporário para o final
        logger.info(f"Pulando downmix para {input_file}: número de canais não especificado")
        success = shutil.move(intermediate_flac, output_flac) is not None

    if not success:
        if os.path.exists(intermediate_flac):
            os.remove(intermediate_flac)
        return False

    success = apply_flac_metadata(output_flac, input_format, codec, compression_level, debug)
    if not success:
        if os.path.exists(output_flac):
            os.remove(output_flac)
        return False

    if os.path.exists(intermediate_flac):
        try:
            os.remove(intermediate_flac)
            logger.debug(f"Removido arquivo intermediário: {intermediate_flac}")
        except Exception as e:
            logger.error(f"Falha ao remover arquivo intermediário {intermediate_flac}: {e}")

    return True

def process_files_in_parallel(files: List[str], output_dir: str, codec: str, sample_rate: str, channels: Optional[int], compression_level: str, debug: bool = False) -> bool:
    logger.info(f"Iniciando processamento paralelo com {CONFIG.PARALLEL_JOBS} trabalhadores para {len(files)} arquivos")
    with ThreadPoolExecutor(max_workers=CONFIG.PARALLEL_JOBS) as executor:
        results = [executor.submit(process_file, file, output_dir, codec, sample_rate, channels, compression_level, debug) for file in files]
        outcomes = [future.result() for future in results]
    success = all(outcomes)
    logger.info(f"Concluído processamento paralelo para {len(files)} arquivos. Sucesso: {success}")
    return success

def cleanup(signum=None, frame=None):
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
Downmix - Conversor de MLP/PCM para FLAC com Downmix Opcional

Descrição:
----------
Converte arquivos MLP ou PCM para FLAC usando parâmetros fornecidos manualmente. O downmix é realizado apenas se o número de canais for especificado; caso contrário, mantém os canais originais.

Fluxo de Funcionamento:
-----------------------
1. **Validação**: Verifica ffmpeg e metaflac.
2. **Processamento**:
   - Converte MLP/PCM para FLAC com codec e sample rate fornecidos.
   - Faz downmix se --channels for especificado; caso contrário, mantém os canais originais.
   - Aplica metadados com formato, codec e compression level.
3. **Saída**: Salva em subdiretório 'flac'.

Parâmetros Obrigatórios:
------------------------
- --codec: Formato de amostra (s16 ou s32)
- --sample-rate: Taxa de amostragem em Hz

Parâmetros Opcionais:
---------------------
- --channels: Número de canais para downmix (se omitido, não realiza downmix)

Exemplos:
---------
1. Converter sem downmix:
   ./downmix.py --codec s32 --sample-rate 44100 /path/to/directory

2. Converter com downmix para 2 canais:
   ./downmix.py --codec s32 --sample-rate 44100 --channels 2 /path/to/directory

3. Modo debug com downmix para 6 canais:
   ./downmix.py --codec s32 --sample-rate 192000 --channels 6 --debug /path/to/directory
"""
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )
    parser.add_argument('-h', '--help', action='help', help="Mostra esta mensagem de ajuda e sai.")
    parser.add_argument('path', nargs='?', default=os.getcwd(), help="Caminho para um arquivo .mlp/.pcm ou diretório (padrão: diretório atual)")
    parser.add_argument('--codec', required=True, choices=['s16', 's32'], help="Formato de amostra para saída FLAC (s16 ou s32)")
    parser.add_argument('--sample-rate', required=True, type=str, help="Taxa de amostragem em Hz (ex.: 44100, 192000)")
    parser.add_argument('--channels', type=int, help="Número de canais para downmix (se omitido, não realiza downmix)")
    parser.add_argument('--compression-level', type=str, default='12', help="Nível de compressão FLAC (0-12). Padrão: 12")
    parser.add_argument('--parallel', type=int, help=f"Número de tarefas paralelas (padrão: {CONFIG.PARALLEL_JOBS})")
    parser.add_argument('--skip-existing', action='store_true', help="Pula arquivos se a saída já existir (padrão: False)")
    parser.add_argument('--debug', action='store_true', help="Ativa logs de depuração (padrão: False)")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if args.parallel:
        CONFIG.PARALLEL_JOBS = max(1, args.parallel)
    if args.skip_existing:
        CONFIG.SKIP_EXISTING = True
    CONFIG.FLAC_COMPRESSION = args.compression_level

    # Aviso se --channels não for especificado
    if args.channels is None:
        logger.warning("Número de canais não especificado. Downmix não será realizado.")

    for cmd in ['ffmpeg', 'metaflac']:
        if not shutil.which(cmd):
            logger.error(f"{cmd} não encontrado. Por favor, instale-o.")
            sys.exit(1)

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

    if path.is_file() and path.suffix.lower() in ('.mlp', '.pcm'):
        output_dir = os.path.join(path.parent, OUTPUT_DIR)
        success = process_file(str(path), output_dir, args.codec, args.sample_rate, args.channels, CONFIG.FLAC_COMPRESSION, args.debug)
    elif path.is_dir():
        os.chdir(path)
        files = [str(f) for f in Path('.').glob('*.mlp')] + [str(f) for f in Path('.').glob('*.pcm')]
        subdirs = [d for d in Path('.').glob('*') if d.is_dir() and any(f.suffix.lower() in ('.mlp', '.pcm') for f in d.glob('*'))]

        if files:
            logger.info(f"Processando diretório: {path}")
            success &= process_files_in_parallel(files, os.path.join(path, OUTPUT_DIR), args.codec, args.sample_rate, args.channels, CONFIG.FLAC_COMPRESSION, args.debug)
        if subdirs:
            logger.info(f"Processando subdiretórios em {path}: {', '.join(str(s) for s in subdirs)}")
            for subdir in subdirs:
                subdir_files = [str(f) for f in subdir.glob('*.mlp')] + [str(f) for f in subdir.glob('*.pcm')]
                success &= process_files_in_parallel(subdir_files, os.path.join(subdir, OUTPUT_DIR), args.codec, args.sample_rate, args.channels, CONFIG.FLAC_COMPRESSION, args.debug)
        if not files and not subdirs:
            logger.error(f"Nenhum arquivo .mlp ou .pcm encontrado em {path} ou seus subdiretórios")
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

    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            os.remove(temp_file)

    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)

if __name__ == "__main__":
    main()