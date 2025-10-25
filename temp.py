#!/usr/bin/env python3
import subprocess
import os
import argparse
import logging
import time
import re
import sys
import signal
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import List, Tuple, Optional, Dict
import shutil
import termios
import tty

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
logger = logging.getLogger('puretone')

# Classe de configuração
class PureToneConfig:
    def __init__(self):
        self.ACODEC = 'pcm_s24le'
        self.AR = '176400'  # padrão: DSD128
        self.LOUDNORM_I = '-14'
        self.LOUDNORM_TP = '-1'
        self.LOUDNORM_LRA = '20'
        self.VOLUME = None
        self.VOLUME_INCREASE = '1dB'
        self.RESAMPLER = 'soxr'
        self.PRECISION = '28'
        self.CHEBY = '1'
        self.OUTPUT_FORMAT = 'wav'
        self.WAVPACK_COMPRESSION = '0'
        self.FLAC_COMPRESSION = '0'
        self.OVERWRITE = True
        self.SKIP_EXISTING = False
        self.PARALLEL_JOBS = 2
        self.ENABLE_VISUALIZATION = False
        self.VISUALIZATION_TYPE = 'spectrogram'
        self.VISUALIZATION_SIZE = '1920x1080'
        self.SPECTROGRAM_MODE = 'combined'
        self.HEADROOM_LIMIT = -0.5
        self.ADDITION = '0dB'
        self.AUTO_RATE = True  # <-- NOVA OPÇÃO: auto-sample-rate

CONFIG = PureToneConfig()

# Diretórios de saída por formato
OUTPUT_DIRS = {'wav': 'wv', 'wavpack': 'wvpk', 'flac': 'flac'}
FORMAT_EXTENSIONS = {'wav': 'wav', 'wavpack': 'wv', 'flac': 'flac'}

# Arquivos temporários
TEMP_FILES = {
    'PEAK_LOG': f"/tmp/puretone_{os.getpid()}_peaks.log",
    'VOLUME_LOG': f"/tmp/puretone_{os.getpid()}_volume.log",
}

# Mapeamento DSD → Taxa de saída recomendada
DSD_TO_RATE = {
    "DSD64":  88200,
    "DSD128": 176400,
    "DSD256": 352800,
    "DSD512": 705600,
}

def run_command(cmd: List[str], capture_output: bool = True) -> Tuple[str, str, int]:
    logger.debug(f"Executing command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture_output, text=True)
    if result.returncode != 0:
        logger.error(f"Command failed with return code {result.returncode}: {result.stderr}")
    return result.stdout, result.stderr, result.returncode

def normalize_path(path: str) -> str:
    return os.path.normpath(path).replace('//', '/')

def validate_resolution(resolution: str) -> bool:
    return bool(re.match(r'^\d+x\d+$', resolution))

def validate_volume(volume: str) -> bool:
    return bool(re.match(r'^[-+]?[0-9]*\.?[0-9]+dB$', volume))

def validate_addition(addition: str) -> bool:
    if not validate_volume(addition):
        return False
    value = float(addition.replace('dB', ''))
    return value >= 0

def add_db(value_db: str, addition_db: str) -> str:
    value = float(value_db.replace('dB', '')) if value_db != 'N/A' else 0
    addition = float(addition_db.replace('dB', '')) if addition_db else 0
    return f"{(value + addition):.1f}dB"

# === DETECÇÃO DE DSD TYPE POR BITRATE ===
def detect_dsd_type(input_file: str) -> Optional[str]:
    """Detecta DSD64, DSD128, DSD256, DSD512 via BITRATE do stream."""
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=bit_rate', '-of', 'csv=p=0', input_file
    ]
    try:
        output = subprocess.check_output(cmd, text=True).strip()
        if not output or output == 'N/A':
            return None
        bitrate = int(output) // 1000  # kb/s
        # Tolerância para variações
        if 5400 <= bitrate <= 5900:
            return "DSD64"
        elif 11000 <= bitrate <= 11600:
            return "DSD128"
        elif 22000 <= bitrate <= 23000:
            return "DSD256"
        elif 44000 <= bitrate <= 46000:
            return "DSD512"
        else:
            return f"DSD Desconhecido ({bitrate} kb/s)"
    except Exception as e:
        logger.warning(f"Não foi possível detectar DSD bitrate de {input_file}: {e}")
        return None

def suggest_output_rate(dsd_type: str) -> int:
    """Sugere taxa de saída baseada no DSD."""
    return DSD_TO_RATE.get(dsd_type, 176400)  # fallback DSD128

# === FIM DETECÇÃO ===

def analyze_peaks(file: str, peak_log: str, log_type: str) -> Optional[float]:
    _, stderr, rc = run_command(['ffmpeg', '-i', file, '-af', 'volumedetect', '-f', 'null', '-'])
    max_volume = re.search(r'max_volume: ([-0-9.]* dB)', stderr)
    max_volume_db = float(max_volume.group(1).replace(' dB', '')) if max_volume else None
    if max_volume_db is None:
        logger.warning(f"Max volume not detected for {file}")

    _, stderr, rc = run_command(['ffmpeg', '-i', file, '-af', 'astats=metadata=1,ametadata=print:key=lavfi.astats.Overall.Peak_level', '-f', 'null', '-'])
    peak_match = re.search(r'Peak_level=([-0-9.]+)', stderr)
    peak_level = f"{peak_match.group(1)} dBFS" if peak_match else 'Not detected'

    with open(peak_log, 'a') as f:
        f.write(f"{file}:{log_type}:{max_volume_db if max_volume_db is not None else 'Not detected'}:{peak_level}\n")
    return max_volume_db

def calculate_volume_adjustment(files: List[str], subdir: str, log_file: Optional[str] = None) -> Tuple[List[Tuple[str, str]], List[dict]]:
    if os.path.exists(TEMP_FILES['PEAK_LOG']):
        os.remove(TEMP_FILES['PEAK_LOG'])
    if os.path.exists(TEMP_FILES['VOLUME_LOG']):
        os.remove(TEMP_FILES['VOLUME_LOG'])

    volume_adjustments = []
    temp_wav_files = []
    dsd_types = {}  # Para resumo final

    for input_file in files:
        base_name = Path(input_file).stem
        temp_wav = f"/tmp/puretone_{os.getpid()}_{base_name}_temp.wav"
        temp_wav_files.append(temp_wav)

        # === DETECÇÃO DSD ===
        dsd_type = detect_dsd_type(input_file)
        if dsd_type:
            dsd_types[input_file] = dsd_type
            logger.info(f"Detected: {input_file} → {dsd_type}")

        # Usar taxa sugerida por DSD type
        output_rate = suggest_output_rate(dsd_type) if dsd_type and CONFIG.AUTO_RATE else int(CONFIG.AR)

        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG.ACODEC, '-ar', str(output_rate),
               '-af', f"aresample=resampler={CONFIG.RESAMPLER}:precision={CONFIG.PRECISION}:cheby={CONFIG.CHEBY}", temp_wav, '-y']
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(temp_wav):
            logger.error(f"Failed to create temporary WAV for {input_file}: {stderr}")
            continue

        dsd_max_volume = analyze_peaks(input_file, TEMP_FILES['PEAK_LOG'], "DSD")
        wav_max_volume = analyze_peaks(temp_wav, TEMP_FILES['PEAK_LOG'], "WAV")

        if dsd_max_volume is None or wav_max_volume is None:
            logger.warning(f"Skipping volume calculation for {input_file}: peak data unavailable")
            continue

        y = -(wav_max_volume - dsd_max_volume)
        logger.info(f"File {input_file}: DSD Max Volume = {dsd_max_volume:.1f} dB, WAV Max Volume = {wav_max_volume:.1f} dB, y = {y:.1f} dB")

        with open(TEMP_FILES['VOLUME_LOG'], 'a') as f:
            f.write(f"{input_file}:{y:.1f}:{wav_max_volume:.1f}:{dsd_type or 'Unknown'}\n")
        volume_adjustments.append({'file': input_file, 'y': y, 'wav_max_volume': wav_max_volume, 'dsd_type': dsd_type})

    for temp_wav in temp_wav_files:
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

    if not volume_adjustments:
        logger.error(f"No valid volume data calculated for files in {subdir or 'current directory'}")
        return [], []

    final_volumes = []
    max_volumes = [entry['wav_max_volume'] + entry['y'] for entry in volume_adjustments]
    highest_volume = max(max_volumes)

    applied_increase = False
    volume_increase_db = float(CONFIG.VOLUME_INCREASE.replace('dB', ''))

    if CONFIG.VOLUME == 'auto' and CONFIG.ADDITION == '0dB':
        all_have_margin = all(entry['wav_max_volume'] + volume_increase_db <= CONFIG.HEADROOM_LIMIT for entry in volume_adjustments)
        if all_have_margin and volume_adjustments:
            logger.info(f"All tracks have sufficient headroom. Applying {volume_increase_db}dB increase to all tracks.")
            applied_increase = True
        else:
            logger.info(f"Not all tracks have sufficient headroom for {volume_increase_db}dB increase. Following standard flow.")

    if highest_volume > CONFIG.HEADROOM_LIMIT:
        adjustment = CONFIG.HEADROOM_LIMIT - highest_volume
        logger.info(f"Highest adjusted volume ({highest_volume:.1f} dB) exceeds limit ({CONFIG.HEADROOM_LIMIT} dB). Applying uniform adjustment of {adjustment:.1f} dB")
        for entry in volume_adjustments:
            base_volume = f"{(entry['y'] + adjustment):.1f}dB"
            if applied_increase:
                base_volume_value = float(base_volume.replace('dB', '')) + volume_increase_db
                base_volume = f"{base_volume_value:.1f}dB"
            final_volume = add_db(base_volume, CONFIG.ADDITION)
            final_volumes.append((entry['file'], final_volume))
    else:
        logger.info(f"No adjusted volumes exceed {CONFIG.HEADROOM_LIMIT} dB. Using individual y values as volume adjustments")
        for entry in volume_adjustments:
            base_volume = f"{entry['y']:.1f}dB"
            if applied_increase:
                base_volume_value = float(base_volume.replace('dB', '')) + volume_increase_db
                base_volume = f"{base_volume_value:.1f}dB"
            final_volume = add_db(base_volume, CONFIG.ADDITION)
            final_volumes.append((entry['file'], final_volume))

    if log_file:
        with open(log_file, 'a') as f:
            for entry in volume_adjustments:
                f.write(f"File {entry['file']}: DSD->WAV y = {entry['y']:.1f} dB, WAV Max Volume = {entry['wav_max_volume']:.1f} dB, DSD Type = {entry['dsd_type'] or 'Unknown'}\n")
            if highest_volume > CONFIG.HEADROOM_LIMIT:
                f.write(f"Applied uniform adjustment of {adjustment:.1f} dB to keep highest volume at {CONFIG.HEADROOM_LIMIT} dB\n")
            else:
                f.write(f"Used individual y values as no volumes exceed {CONFIG.HEADROOM_LIMIT} dB\n")
            if CONFIG.ADDITION != '0dB':
                f.write(f"Applied additional volume adjustment: {CONFIG.ADDITION}\n")

    return final_volumes, volume_adjustments

def process_file(args_tuple: Tuple[str, str, str, Optional[str]]) -> bool:
    input_file, output_dir, volume, log_file = args_tuple
    logger.debug(f"Processing file: {input_file}")
    base_name = Path(input_file).stem
    intermediate_wav = normalize_path(os.path.join(output_dir, f"{base_name}_intermediate.wav"))
    output_file = normalize_path(os.path.join(output_dir, f"{base_name}.{FORMAT_EXTENSIONS[CONFIG.OUTPUT_FORMAT]}"))
    spectrogram_dir = normalize_path(os.path.join(output_dir, 'spectrogram'))
    local_log = normalize_path(os.path.join(output_dir, 'log.txt'))

    os.makedirs(output_dir, exist_ok=True)
    if CONFIG.ENABLE_VISUALIZATION:
        os.makedirs(spectrogram_dir, exist_ok=True)

    if os.path.exists(output_file):
        if CONFIG.SKIP_EXISTING:
            logger.info(f"Skipping {input_file}: {output_file} already exists (--skip-existing enabled)")
            return True
        elif CONFIG.OVERWRITE:
            logger.info(f"Overwriting {output_file} due to OVERWRITE=True")

    af_base = f"aresample=resampler={CONFIG.RESAMPLER}:precision={CONFIG.PRECISION}:cheby={CONFIG.CHEBY}"
    analyze_peaks(input_file, TEMP_FILES['PEAK_LOG'], "Input")

    # === DETECÇÃO DSD ===
    dsd_type = detect_dsd_type(input_file)
    output_rate = suggest_output_rate(dsd_type) if dsd_type and CONFIG.AUTO_RATE else int(CONFIG.AR)

    if volume:
        af = f"{af_base},volume={volume}"
        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG.ACODEC, '-ar', str(output_rate), '-af', af, intermediate_wav, '-y']
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(intermediate_wav):
            logger.error(f"Error creating intermediate WAV for {input_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
            return False
    else:
        af_first = f"{af_base},loudnorm=I={CONFIG.LOUDNORM_I}:TP={CONFIG.LOUDNORM_TP}:LRA={CONFIG.LOUDNORM_LRA}:print_format=summary"
        _, stderr, rc = run_command(['ffmpeg', '-i', input_file, '-acodec', CONFIG.ACODEC, '-ar', str(output_rate), '-af', af_first, '-f', 'null', '-'])
        if rc != 0:
            logger.error(f"Error analyzing loudness for {input_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
            return False

        metrics = {
            'measured_I': re.search(r'Input Integrated: *([-0-9.]*)', stderr),
            'measured_LRA': re.search(r'Input LRA: *([0-9.]*)', stderr),
            'measured_TP': re.search(r'Input True Peak: *([-0-9.]*)', stderr),
            'measured_thresh': re.search(r'Input Threshold: *([-0-9.]*)', stderr)
        }
        if not all(m.group(1) for m in metrics.values() if m):
            logger.error(f"Failed to extract loudness metrics for {input_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
            return False

        af_second = (f"{af_base},loudnorm=I={CONFIG.LOUDNORM_I}:TP={CONFIG.LOUDNORM_TP}:LRA={CONFIG.LOUDNORM_LRA}:" +
                     f"measured_I={metrics['measured_I'].group(1)}:measured_LRA={metrics['measured_LRA'].group(1)}:" +
                     f"measured_TP={metrics['measured_TP'].group(1)}:measured_thresh={metrics['measured_thresh'].group(1)}")
        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG.ACODEC, '-ar', str(output_rate), '-af', af_second, intermediate_wav, '-y']
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(intermediate_wav):
            logger.error(f"Error creating intermediate WAV for {input_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
            return False

    if CONFIG.OUTPUT_FORMAT == 'wav':
        os.rename(intermediate_wav, output_file)
    else:
        final_cmd = ['ffmpeg', '-i', intermediate_wav, '-c:a', CONFIG.OUTPUT_FORMAT, '-map_metadata', '0']
        if CONFIG.OUTPUT_FORMAT == 'wavpack':
            final_cmd.extend(['-compression_level', CONFIG.WAVPACK_COMPRESSION])
        elif CONFIG.OUTPUT_FORMAT == 'flac':
            final_cmd.extend(['-compression_level', CONFIG.FLAC_COMPRESSION])
        final_cmd.extend([output_file, '-y'])
        try:
            _, stderr, rc = run_command(final_cmd)
            if rc != 0:
                logger.error(f"Error converting {input_file} to {CONFIG.OUTPUT_FORMAT}. Check {local_log}")
                with open(local_log, 'a') as f:
                    f.write(stderr + '\n')
                return False
        finally:
            if os.path.exists(intermediate_wav):
                os.remove(intermediate_wav)

    if not os.path.getsize(output_file):
        logger.error(f"Output file {output_file} is empty")
        return False

    analyze_peaks(output_file, TEMP_FILES['PEAK_LOG'], "Output")
    file_size_kb = os.path.getsize(output_file) / 1024
    logger.info(f"Converted {input_file} -> {output_file} (Size: {file_size_kb:.1f} KB)")

    if CONFIG.OUTPUT_FORMAT == 'flac':
        if volume:
            applied_volume = volume
        else:
            applied_volume = f"loudnorm=I={CONFIG.LOUDNORM_I}:TP={CONFIG.LOUDNORM_TP}:LRA={CONFIG.LOUDNORM_LRA}"
        comment_content = (
            f"DSF > WAV > FLAC, Codec: {CONFIG.ACODEC}, "
            f"Resampler: {CONFIG.RESAMPLER} with precision {CONFIG.PRECISION} and cheby, "
            f"Applied Volume: {applied_volume}, Compression Level: {CONFIG.FLAC_COMPRESSION}, "
            f"Output Rate: {output_rate} Hz"
        )
        metaflac_cmd = ['metaflac', '--set-tag', f"COMMENT={comment_content}", output_file]
        _, stderr, rc = run_command(metaflac_cmd)
        if rc != 0:
            logger.error(f"Failed to apply COMMENT to {output_file}: {stderr}")
            return False

    return True

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

def process_files_in_parallel(files: List[str], output_dir: str, volume_map: List[Tuple[str, str]], log_file: Optional[str] = None) -> bool:
    logger.info(f"Starting parallel processing with {CONFIG.PARALLEL_JOBS} processes for {len(files)} files")
    args_list = [(file, output_dir, volume, log_file) for file, volume in volume_map]
    with ProcessPoolExecutor(max_workers=CONFIG.PARALLEL_JOBS) as executor:
        results = list(executor.map(process_file, args_list))
    success = all(results)
    logger.info(f"Completed parallel processing for {len(files)} files. Success: {success}")
    return success

def print_volume_summary(volume_data: List[dict], volume_maps: List[List[Tuple[str, str]]], log_file: Optional[str] = None):
    logger.info("\n=== DSD & Volume Adjustment Summary ===")
    col_widths = [40, 15, 15, 15, 20]
    logger.info(f"{'File':<40} {'DSD Type':^15} {'Output Rate':^15} {'y (dB)':^15} {'Applied Volume':^20}")
    logger.info("-" * sum(col_widths))

    volume_dict = {}
    for v_map in volume_maps:
        volume_dict.update({file: vol for file, vol in v_map})

    for entry in volume_data:
        dsd_type = entry.get('dsd_type', 'Unknown')
        rate = DSD_TO_RATE.get(dsd_type, 0)
        rate_str = f"{rate} Hz" if rate else "Unknown"
        applied_volume = volume_dict.get(entry['file'], "N/A")
        logger.info(f"{entry['file'][:38]:<40} {dsd_type:^15} {rate_str:^15} {entry['y']:^15.1f} {applied_volume:^20}")
    logger.info("-" * sum(col_widths))

    if CONFIG.ADDITION != '0dB':
        logger.info(f"Applied additional volume adjustment: {CONFIG.ADDITION}")

    if log_file:
        with open(log_file, 'a') as f:
            f.write("\n=== DSD & Volume Adjustment Summary ===\n")
            f.write(f"{'File':<40} {'DSD Type':^15} {'Output Rate':^15} {'y (dB)':^15} {'Applied Volume':^20}\n")
            f.write("-" * sum(col_widths) + "\n")
            for entry in volume_data:
                dsd_type = entry.get('dsd_type', 'Unknown')
                rate = DSD_TO_RATE.get(dsd_type, 0)
                rate_str = f"{rate} Hz" if rate else "Unknown"
                applied_volume = volume_dict.get(entry['file'], "N/A")
                f.write(f"{entry['file'][:38]:<40} {dsd_type:^15} {rate_str:^15} {entry['y']:^15.1f} {applied_volume:^20}\n")
            f.write("-" * sum(col_widths) + "\n")
            if CONFIG.ADDITION != '0dB':
                f.write(f"Applied additional volume adjustment: {CONFIG.ADDITION}\n")

def main():
    description = """
PureTone - Conversor de DSD para Áudio de Alta Qualidade

[Descrição completa...]

Novidades:
---------
- Detecta automaticamente DSD64, DSD128, DSD256, DSD512 via bitrate
- --auto-rate: Ajusta --sample-rate automaticamente (padrão: ativado)
- Tabela de resumo com DSD Type e taxa de saída
- Processamento paralelo com ProcessPoolExecutor
"""

    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )

    parser.add_argument('-h', '--help', action='help', help="Mostra esta mensagem de ajuda e sai.")
    parser.add_argument('--format', choices=['wav', 'wavpack', 'flac'], default='wav', help="Formato de saída")
    parser.add_argument('--codec', help="Codec de áudio para saída WAV")
    parser.add_argument('--sample-rate', type=int, help="Taxa de amostragem em Hz. Ignorado se --auto-rate estiver ativo.")
    parser.add_argument('--auto-rate', action='store_true', default=True, help="Ajusta --sample-rate automaticamente com base no DSD (padrão: ativado)")
    parser.add_argument('--loudnorm-I', help="Alvo de loudness integrado")
    parser.add_argument('--loudnorm-TP', help="Limite de pico verdadeiro")
    parser.add_argument('--loudnorm-LRA', help="Faixa de loudness")
    parser.add_argument('--volume', help="Ajuste de volume: 'auto', 'analysis' ou valor fixo")
    parser.add_argument('--volume-increase', default='1dB', help="Aumento opcional com --volume auto")
    parser.add_argument('--addition', help="Ajuste adicional com --volume auto")
    parser.add_argument('--headroom-limit', type=float, help="Volume máximo permitido em dB")
    parser.add_argument('--resampler', help="Motor de resampling")
    parser.add_argument('--precision', type=int, help="Precisão do resampler")
    parser.add_argument('--cheby', choices=['0', '1'], help="Ativa modo Chebyshev")
    parser.add_argument('--spectrogram', nargs='*', help="Ativa visualização")
    parser.add_argument('--compression-level', type=int, help="Nível de compressão")
    parser.add_argument('--skip-existing', action='store_true', help="Pula arquivos existentes")
    parser.add_argument('--parallel', type=int, help="Número de processos paralelos")
    parser.add_argument('--log', help="Arquivo de log")
    parser.add_argument('--debug', action='store_true', help="Ativa logs de depuração")
    parser.add_argument('path', help="Caminho para arquivo .dsf ou diretório")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    CONFIG.OUTPUT_FORMAT = args.format
    CONFIG.AUTO_RATE = args.auto_rate

    if args.volume:
        if args.volume not in ('auto', 'analysis') and not validate_volume(args.volume):
            logger.error("Volume deve ser 'auto', 'analysis', ou no formato 'XdB'")
            sys.exit(1)
        CONFIG.VOLUME = args.volume

    if args.volume_increase and not validate_volume(args.volume_increase):
        logger.error("volume-increase deve estar no formato 'XdB'")
        sys.exit(1)
    CONFIG.VOLUME_INCREASE = args.volume_increase

    if args.addition:
        if not validate_addition(args.addition):
            logger.error("Addition deve estar no formato 'XdB' e não pode ser negativo")
            sys.exit(1)
        if args.volume != 'auto':
            logger.error("--addition só pode ser usado com --volume auto")
            sys.exit(1)
        CONFIG.ADDITION = args.addition

    if args.codec: CONFIG.ACODEC = args.codec
    if args.loudnorm_I: CONFIG.LOUDNORM_I = args.loudnorm_I
    if args.loudnorm_TP: CONFIG.LOUDNORM_TP = args.loudnorm_TP
    if args.loudnorm_LRA: CONFIG.LOUDNORM_LRA = args.loudnorm_LRA
    if args.headroom_limit is not None: CONFIG.HEADROOM_LIMIT = args.headroom_limit
    if args.resampler: CONFIG.RESAMPLER = args.resampler
    if args.precision: CONFIG.PRECISION = str(args.precision)
    if args.cheby: CONFIG.CHEBY = args.cheby
    if args.compression_level:
        if CONFIG.OUTPUT_FORMAT == 'wavpack' and 0 <= args.compression_level <= 6:
            CONFIG.WAVPACK_COMPRESSION = str(args.compression_level)
        elif CONFIG.OUTPUT_FORMAT == 'flac' and 0 <= args.compression_level <= 12:
            CONFIG.FLAC_COMPRESSION = str(args.compression_level)
        else:
            logger.error(f"Nível de compressão inválido para {CONFIG.OUTPUT_FORMAT}")
            sys.exit(1)
    if args.skip_existing: CONFIG.SKIP_EXISTING = True
    if args.parallel: CONFIG.PARALLEL_JOBS = max(1, args.parallel)
    log_file = args.log

    # Verificar dependências
    required_commands = ['ffmpeg', 'ffprobe']
    if CONFIG.OUTPUT_FORMAT == 'flac':
        required_commands.append('metaflac')
    for cmd in required_commands:
        if shutil.which(cmd) is None:
            logger.error(f"{cmd} não encontrado. Por favor, instale-o.")
            sys.exit(1)

    for temp_file in TEMP_FILES.values():
        with open(temp_file, 'w'): pass

    path = resolve_path(args.path)
    start_time = time.time()
    success = True
    all_volume_data = []
    all_volume_maps = []

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    if path.is_file() and path.suffix == '.dsf':
        output_dir = os.path.join(path.parent, OUTPUT_DIRS[args.format])
        dsd_type = detect_dsd_type(str(path))
        if dsd_type and CONFIG.AUTO_RATE and not args.sample_rate:
            suggested = suggest_output_rate(dsd_type)
            CONFIG.AR = str(suggested)
            logger.info(f"Auto-sample-rate: {dsd_type} → {suggested} Hz")

        if args.volume == 'auto':
            volume_map, volume_data = calculate_volume_adjustment([str(path)], "", log_file)
            all_volume_data.extend(volume_data)
            all_volume_maps.append(volume_map)
            if volume_map:
                success &= process_file((str(path), output_dir, volume_map[0][1], log_file))
            else:
                success = False
        else:
            success &= process_file((str(path), output_dir, args.volume, log_file))
    elif path.is_dir():
        os.chdir(path)
        files = [str(f) for f in Path('.').glob('*.dsf')]
        subdirs = [d for d in Path('.').glob('*') if d.is_dir() and any(f.suffix == '.dsf' for f in d.glob('*.dsf'))]

        if files or subdirs:
            # Ajuste automático de sample rate por subdir
            sample_rates = {}
            for f in files + [str(s) for s in subdirs]:
                dsd_type = detect_dsd_type(f)
                if dsd_type and CONFIG.AUTO_RATE and not args.sample_rate:
                    rate = suggest_output_rate(dsd_type)
                    sample_rates[f] = rate
                    if f in files:
                        logger.info(f"Auto-sample-rate: {Path(f).name} ({dsd_type}) → {rate} Hz")

            if args.volume == 'auto':
                if files:
                    volume_map, volume_data = calculate_volume_adjustment(files, "", log_file)
                    all_volume_data.extend(volume_data)
                    all_volume_maps.append(volume_map)
                    success &= process_files_in_parallel(files, os.path.join(path, OUTPUT_DIRS[args.format]), volume_map, log_file)
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    volume_map, volume_data = calculate_volume_adjustment(subdir_files, str(subdir), log_file)
                    all_volume_data.extend(volume_data)
                    all_volume_maps.append(volume_map)
                    success &= process_files_in_parallel(subdir_files, os.path.join(subdir, OUTPUT_DIRS[args.format]), volume_map, log_file)
            else:
                if files:
                    success &= process_files_in_parallel(files, os.path.join(path, OUTPUT_DIRS[args.format]), [(f, args.volume) for f in files], log_file)
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    success &= process_files_in_parallel(subdir_files, os.path.join(subdir, OUTPUT_DIRS[args.format]), [(f, args.volume) for f in subdir_files], log_file)
        else:
            logger.error(f"Nenhum arquivo .dsf encontrado em {path}")
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

    if all_volume_data and args.volume == 'auto':
        print_volume_summary(all_volume_data, all_volume_maps, log_file)

    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            os.remove(temp_file)

    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)

if __name__ == "__main__":
    main()