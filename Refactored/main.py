#!/usr/bin/env python3
import sys
import signal
import time
import os
import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, List, Tuple
import termios
from utils import run_command, normalize_path, check_dependencies, get_temp_file_path, validate_resolution, validate_volume, validate_addition
from audio_processing import analyze_peaks_and_volume, calculate_volume_adjustment, process_file, process_files_in_parallel
from visualization import generate_visualization

# Configuração de logging
START_TIME = time.time()
logger = logging.getLogger('puretone')

# Estado do terminal
ORIGINAL_TERMINAL_STATE = None
if sys.stdin.isatty():
    ORIGINAL_TERMINAL_STATE = termios.tcgetattr(sys.stdin)

# Classe de Configuração
class PureToneConfig:
    def __init__(self):
        self.config = {
            'ACODEC': 'pcm_s24le',
            'AR': '176400',
            'MAP_METADATA': '0',
            'LOUDNORM_I': '-14',
            'LOUDNORM_TP': '-1',
            'LOUDNORM_LRA': '20',
            'VOLUME': None,
            'RESAMPLER': 'soxr',
            'PRECISION': '28',
            'CHEBY': '1',
            'OUTPUT_FORMAT': 'wav',
            'WAVPACK_COMPRESSION': '0',
            'FLAC_COMPRESSION': '0',
            'OVERWRITE': True,
            'SKIP_EXISTING': False,
            'PARALLEL_JOBS': 2,
            'ENABLE_VISUALIZATION': False,
            'VISUALIZATION_TYPE': 'spectrogram',
            'VISUALIZATION_SIZE': '1920x1080',
            'SPECTROGRAM_MODE': 'combined',
            'HEADROOM_LIMIT': -0.5,
            'ADDITION': '0dB',
        }
        self.output_dirs = {'wav': 'wv', 'wavpack': 'wvpk', 'flac': 'flac'}
        self.format_extensions = {'wav': 'wav', 'wavpack': 'wv', 'flac': 'flac'}

    def __getitem__(self, key):
        return self.config[key]

    def __setitem__(self, key, value):
        self.config[key] = value

CONFIG = PureToneConfig()
TEMP_FILES = {
    'PEAK_LOG': get_temp_file_path("peaks.log"),
    'VOLUME_LOG': get_temp_file_path("volume.log"),
}

def setup_logging(debug: bool, log_file: Optional[str] = None):
    handlers = []
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('[%(relativeCreated)d] [%(levelname)s] %(message)s'))
    handlers.append(console_handler)

    if log_file:
        file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setFormatter(logging.Formatter('[%(relativeCreated)d] [%(levelname)s] %(message)s'))
        handlers.append(file_handler)

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        handlers=handlers
    )

def cleanup(signum=None, frame=None):
    elapsed_time = int(time.time() - START_TIME)
    logger.info(f"Script interrupted after {elapsed_time} seconds. Cleaning up temporary files...")
    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                logger.debug(f"Removed temporary file: {temp_file}")
            except Exception as e:
                logger.error(f"Failed to remove {temp_file}: {e}")
    for dirpath, _, filenames in os.walk('.'):
        for file in [f for f in filenames if f.endswith('_intermediate.wav')]:
            file_path = os.path.join(dirpath, file)
            try:
                os.remove(file_path)
                logger.debug(f"Removed intermediate file: {file_path}")
            except Exception as e:
                logger.error(f"Failed to remove {file_path}: {e}")
    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)
    logger.info("Cleanup completed. Exiting.")
    sys.exit(1)

def resolve_path(path_str: str) -> Path:
    if '/' in path_str or path_str.startswith('./') or path_str.startswith('../'):
        return Path(path_str)
    return Path(os.path.join(os.getcwd(), path_str))

def print_final_summary(success: bool, elapsed_time: int, processed_files: int, failed_files: int, log_file: Optional[str] = None):
    summary = f"""
=== Final Summary ===
Processed Files: {processed_files}
Failed Files: {failed_files}
Elapsed Time: {elapsed_time} seconds
Status: {'Success' if success else 'Completed with Errors'}
"""
    logger.info(summary)
    if log_file:
        try:
            with open(log_file, 'a') as f:
                f.write(summary)
        except IOError as e:
            logger.error(f"Failed to write final summary to log file {log_file}: {e}")

def main():
    description = """
PureTone - Conversor de DSD para Áudio de Alta Qualidade

Descrição:
----------
PureTone é um script Python que converte arquivos DSD (.dsf) para formatos de áudio de alta qualidade (WAV, WavPack, FLAC), com opções avançadas de processamento de áudio.

Exemplos Práticos:
-----------------
1. Converter um único arquivo DSD para WAV com loudness normalizado:
   ./puretone.py /path/to/file.dsf

2. Converter todos os arquivos DSD em um diretório para WavPack com ajuste automático de volume:
   ./puretone.py --format wavpack --volume auto --parallel 4 /path/to/directory
"""
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )
    parser.add_argument('-h', '--help', action='help', help="Mostra esta mensagem de ajuda e sai.")
    parser.add_argument('--format', choices=['wav', 'wavpack', 'flac'], default='wav', help="Formato de saída: 'wav', 'wavpack' ou 'flac'. Padrão: wav")
    parser.add_argument('--codec', help="Codec de áudio para saída WAV (ex.: pcm_s32le). Padrão: pcm_s24le")
    parser.add_argument('--sample-rate', type=int, help="Taxa de amostragem em Hz (ex.: 88200). Padrão: 176400")
    parser.add_argument('--map-metadata', help="Mapeamento de metadados (ex.: 0 para manter). Padrão: 0")
    parser.add_argument('--loudnorm-I', help="Alvo de loudness integrado em LUFS. Padrão: -14")
    parser.add_argument('--loudnorm-TP', help="Limite de pico verdadeiro em dBTP. Padrão: -1")
    parser.add_argument('--loudnorm-LRA', help="Faixa de loudness em LU. Padrão: 20")
    parser.add_argument('--volume', help="Ajuste de volume: valor fixo (ex.: '2.5dB'), 'auto' ou 'analysis'. Padrão: None")
    parser.add_argument('--addition', help="Ajuste adicional de volume (ex.: '1dB') a ser aplicado apenas com --volume auto. Padrão: 0dB")
    parser.add_argument('--headroom-limit', type=float, help="Volume máximo permitido em dB. Padrão: -0.5")
    parser.add_argument('--resampler', help="Motor de resampling (ex.: soxr). Padrão: soxr")
    parser.add_argument('--precision', type=int, help="Precisão do resampler (ex.: 20-28). Padrão: 28")
    parser.add_argument('--cheby', choices=['0', '1'], help="Ativa modo Chebyshev para resampler SoX. Padrão: 1")
    parser.add_argument('--spectrogram', nargs='*', help="Ativa visualização: '<width>x<height> [type [mode]]'. Padrão: desabilitado")
    parser.add_argument('--compression-level', type=int, help="Nível de compressão: 0-6 para WavPack, 0-12 para FLAC. Padrão: 0")
    parser.add_argument('--skip-existing', action='store_true', help="Pula se o arquivo de saída já existe. Padrão: False")
    parser.add_argument('--parallel', type=int, help="Número de tarefas paralelas. Padrão: 2")
    parser.add_argument('--log', help="Arquivo para salvar resultados da análise. Padrão: None")
    parser.add_argument('--debug', action='store_true', help="Ativa logs de depuração. Padrão: False")
    parser.add_argument('path', help="Caminho para um arquivo .dsf ou diretório")

    args = parser.parse_args()
    setup_logging(args.debug, args.log)
    check_dependencies()

    # Configurações
    CONFIG['OUTPUT_FORMAT'] = args.format
    if args.volume:
        if args.volume not in ('auto', 'analysis') and not validate_volume(args.volume):
            logger.error("Volume deve ser 'auto', 'analysis', ou no formato 'XdB' (ex.: '3dB', '-2.5dB')")
            sys.exit(1)
        CONFIG['VOLUME'] = args.volume

    if args.addition:
        if not validate_addition(args.addition):
            logger.error("Addition deve estar no formato 'XdB' (ex.: '1dB', '2.5dB') e não pode ser negativo")
            sys.exit(1)
        if args.volume != 'auto':
            logger.error("--addition só pode ser usado com --volume auto")
            sys.exit(1)
        CONFIG['ADDITION'] = args.addition

    if args.codec: CONFIG['ACODEC'] = args.codec
    if args.sample_rate: CONFIG['AR'] = str(args.sample_rate)
    if args.map_metadata: CONFIG['MAP_METADATA'] = args.map_metadata
    if args.loudnorm_I: CONFIG['LOUDNORM_I'] = args.loudnorm_I
    if args.loudnorm_TP: CONFIG['LOUDNORM_TP'] = args.loudnorm_TP
    if args.loudnorm_LRA: CONFIG['LOUDNORM_LRA'] = args.loudnorm_LRA
    if args.headroom_limit is not None: CONFIG['HEADROOM_LIMIT'] = args.headroom_limit
    if args.resampler: CONFIG['RESAMPLER'] = args.resampler
    if args.precision: CONFIG['PRECISION'] = str(args.precision)
    if args.cheby: CONFIG['CHEBY'] = args.cheby
    if args.spectrogram:
        CONFIG['ENABLE_VISUALIZATION'] = True
        if args.spectrogram and validate_resolution(args.spectrogram[0]):
            CONFIG['VISUALIZATION_SIZE'] = args.spectrogram[0]
            if len(args.spectrogram) > 1:
                CONFIG['VISUALIZATION_TYPE'] = args.spectrogram[1]
                if len(args.spectrogram) > 2 and CONFIG['VISUALIZATION_TYPE'] == 'spectrogram':
                    CONFIG['SPECTROGRAM_MODE'] = args.spectrogram[2]
    if args.compression_level:
        if CONFIG['OUTPUT_FORMAT'] == 'wavpack' and 0 <= args.compression_level <= 6:
            CONFIG['WAVPACK_COMPRESSION'] = str(args.compression_level)
        elif CONFIG['OUTPUT_FORMAT'] == 'flac' and 0 <= args.compression_level <= 12:
            CONFIG['FLAC_COMPRESSION'] = str(args.compression_level)
        else:
            logger.error(f"Nível de compressão inválido para {CONFIG['OUTPUT_FORMAT']}")
            sys.exit(1)
    if args.skip_existing: CONFIG['SKIP_EXISTING'] = True
    if args.parallel: CONFIG['PARALLEL_JOBS'] = max(1, args.parallel)

    log_file = args.log

    for temp_file in TEMP_FILES.values():
        try:
            with open(temp_file, 'w'): pass
        except IOError as e:
            logger.error(f"Failed to create temp file {temp_file}: {e}")
            sys.exit(1)

    path = resolve_path(args.path)
    start_time = time.time()
    success = True
    processed_files = 0
    failed_files = 0
    all_volume_data = []
    all_volume_maps = []

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    if path.is_file() and path.suffix == '.dsf':
        output_dir = os.path.join(path.parent, CONFIG.output_dirs[args.format])
        if args.volume == 'auto':
            volume_map, volume_data = calculate_volume_adjustment([str(path)], "", log_file)
            all_volume_data.extend(volume_data)
            all_volume_maps.append(volume_map)
            if volume_map:
                success &= process_file(str(path), output_dir, volume_map[0][1], log_file)
                processed_files += 1
                failed_files += 0 if success else 1
            else:
                success = False
                failed_files += 1
        else:
            success &= process_file(str(path), output_dir, args.volume, log_file)
            processed_files += 1
            failed_files += 0 if success else 1
    elif path.is_dir():
        os.chdir(path)
        files = [str(f) for f in Path('.').glob('*.dsf')]
        subdirs = [d for d in Path('.').glob('*') if d.is_dir() and any(f.suffix == '.dsf' for f in d.glob('*.dsf'))]

        if args.volume == 'auto':
            if files:
                logger.info(f"Processando diretório: {path}")
                volume_map, volume_data = calculate_volume_adjustment(files, "", log_file)
                all_volume_data.extend(volume_data)
                all_volume_maps.append(volume_map)
                success &= process_files_in_parallel(files, os.path.join(path, CONFIG.output_dirs[args.format]), volume_map, log_file)
                processed_files += len(files)
                failed_files += sum(1 for _ in files if not success)
            if subdirs:
                logger.info(f"Processando subdiretórios em {path}: {', '.join(str(s) for s in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    volume_map, volume_data = calculate_volume_adjustment(subdir_files, str(subdir), log_file)
                    all_volume_data.extend(volume_data)
                    all_volume_maps.append(volume_map)
                    success &= process_files_in_parallel(subdir_files, os.path.join(subdir, CONFIG.output_dirs[args.format]), volume_map, log_file)
                    processed_files += len(subdir_files)
                    failed_files += sum(1 for _ in subdir_files if not success)
            if not files and not subdirs:
                logger.error(f"Nenhum arquivo .dsf encontrado em {path} ou seus subdiretórios")
                success = False
        else:
            if files:
                logger.info(f"Processando diretório: {path}")
                success &= process_files_in_parallel(files, os.path.join(path, CONFIG.output_dirs[args.format]), [(f, args.volume) for f in files], log_file)
                processed_files += len(files)
                failed_files += sum(1 for _ in files if not success)
            if subdirs:
                logger.info(f"Processando subdiretórios em {path}: {', '.join(str(s) for s in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    success &= process_files_in_parallel(subdir_files, os.path.join(subdir, CONFIG.output_dirs[args.format]), [(f, args.volume) for f in subdir_files], log_file)
                    processed_files += len(subdir_files)
                    failed_files += sum(1 for _ in subdir_files if not success)
            if not files and not subdirs:
                logger.error(f"Nenhum arquivo .dsf encontrado em {path} ou seus subdiretórios")
                success = False
    else:
        logger.error(f"Caminho inválido: {args.path}")
        sys.exit(1)

    elapsed_time = int(time.time() - start_time)
    print_final_summary(success, elapsed_time, processed_files, failed_files, log_file)

    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception as e:
                logger.error(f"Failed to remove temp file {temp_file}: {e}")

    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)

if __name__ == "__main__":
    main()