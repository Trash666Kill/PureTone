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
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Optional
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

# Configurações padrão
CONFIG = {
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
    'ADDITION': '0dB',  # Novo parâmetro padrão para acréscimo
}

# Diretórios de saída por formato
OUTPUT_DIRS = {'wav': 'wv', 'wavpack': 'wvpk', 'flac': 'flac'}

# Extensões de arquivo por formato
FORMAT_EXTENSIONS = {'wav': 'wav', 'wavpack': 'wv', 'flac': 'flac'}

# Arquivos temporários
TEMP_FILES = {
    'PEAK_LOG': f"/tmp/puretone_{os.getpid()}_peaks.log",
    'VOLUME_LOG': f"/tmp/puretone_{os.getpid()}_volume.log",
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

def add_db(value_db: str, addition_db: str) -> str:
    value = float(value_db.replace('dB', '')) if value_db != 'N/A' else 0
    addition = float(addition_db.replace('dB', '')) if addition_db else 0
    return f"{(value + addition):.1f}dB"

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

    for input_file in files:
        base_name = Path(input_file).stem
        temp_wav = f"/tmp/puretone_{os.getpid()}_{base_name}_temp.wav"
        temp_wav_files.append(temp_wav)

        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG['ACODEC'], '-ar', CONFIG['AR'],
               '-map_metadata', CONFIG['MAP_METADATA'], '-af', f"aresample=resampler={CONFIG['RESAMPLER']}:precision={CONFIG['PRECISION']}:cheby={CONFIG['CHEBY']}", temp_wav, '-y']
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
            f.write(f"{input_file}:{y:.1f}:{wav_max_volume:.1f}\n")
        volume_adjustments.append({'file': input_file, 'y': y, 'wav_max_volume': wav_max_volume})

    for temp_wav in temp_wav_files:
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

    if not volume_adjustments:
        logger.error(f"No valid volume data calculated for files in {subdir or 'current directory'}")
        return [], []

    final_volumes = []
    max_volumes = [entry['wav_max_volume'] + entry['y'] for entry in volume_adjustments]
    highest_volume = max(max_volumes)

    if highest_volume > CONFIG['HEADROOM_LIMIT']:
        adjustment = CONFIG['HEADROOM_LIMIT'] - highest_volume
        logger.info(f"Highest adjusted volume ({highest_volume:.1f} dB) exceeds limit ({CONFIG['HEADROOM_LIMIT']} dB). Applying uniform adjustment of {adjustment:.1f} dB")
        for entry in volume_adjustments:
            base_volume = f"{(entry['y'] + adjustment):.1f}dB"
            final_volume = add_db(base_volume, CONFIG['ADDITION'])
            final_volumes.append((entry['file'], final_volume))
    else:
        logger.info(f"No adjusted volumes exceed {CONFIG['HEADROOM_LIMIT']} dB. Using individual y values as volume adjustments")
        for entry in volume_adjustments:
            base_volume = f"{entry['y']:.1f}dB"
            final_volume = add_db(base_volume, CONFIG['ADDITION'])
            final_volumes.append((entry['file'], final_volume))

    if log_file:
        with open(log_file, 'a') as f:
            for entry in volume_adjustments:
                f.write(f"File {entry['file']}: DSD->WAV y = {entry['y']:.1f} dB, WAV Max Volume = {entry['wav_max_volume']:.1f} dB\n")
            if highest_volume > CONFIG['HEADROOM_LIMIT']:
                f.write(f"Applied uniform adjustment of {adjustment:.1f} dB to keep highest volume at {CONFIG['HEADROOM_LIMIT']} dB\n")
            else:
                f.write(f"Used individual y values as no volumes exceed {CONFIG['HEADROOM_LIMIT']} dB\n")
            if CONFIG['ADDITION'] != '0dB':
                f.write(f"Applied additional volume adjustment: {CONFIG['ADDITION']}\n")

    return final_volumes, volume_adjustments

def process_file(input_file: str, output_dir: str, volume: str = None, log_file: Optional[str] = None) -> bool:
    logger.debug(f"Processing file: {input_file}")
    base_name = Path(input_file).stem
    intermediate_wav = normalize_path(os.path.join(output_dir, f"{base_name}_intermediate.wav"))
    output_file = normalize_path(os.path.join(output_dir, f"{base_name}.{FORMAT_EXTENSIONS[CONFIG['OUTPUT_FORMAT']]}"))
    spectrogram_dir = normalize_path(os.path.join(output_dir, 'spectrogram'))
    local_log = normalize_path(os.path.join(output_dir, 'log.txt'))

    os.makedirs(output_dir, exist_ok=True)
    if CONFIG['ENABLE_VISUALIZATION']:
        os.makedirs(spectrogram_dir, exist_ok=True)

    if os.path.exists(output_file):
        if CONFIG['SKIP_EXISTING']:
            logger.info(f"Skipping {input_file}: {output_file} already exists (--skip-existing enabled)")
            return True
        elif CONFIG['OVERWRITE']:
            logger.info(f"Overwriting {output_file} due to OVERWRITE=True")

    af_base = f"aresample=resampler={CONFIG['RESAMPLER']}:precision={CONFIG['PRECISION']}:cheby={CONFIG['CHEBY']}"
    analyze_peaks(input_file, TEMP_FILES['PEAK_LOG'], "Input")

    if volume:
        af = f"{af_base},volume={volume}"
        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG['ACODEC'], '-ar', CONFIG['AR'],
               '-map_metadata', CONFIG['MAP_METADATA'], '-af', af, intermediate_wav, '-y']
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(intermediate_wav):
            logger.error(f"Error creating intermediate WAV for {input_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
            return False
    else:
        af_first = f"{af_base},loudnorm=I={CONFIG['LOUDNORM_I']}:TP={CONFIG['LOUDNORM_TP']}:LRA={CONFIG['LOUDNORM_LRA']}:print_format=summary"
        _, stderr, rc = run_command(['ffmpeg', '-i', input_file, '-acodec', CONFIG['ACODEC'], '-ar', CONFIG['AR'],
                                     '-map_metadata', CONFIG['MAP_METADATA'], '-af', af_first, '-f', 'null', '-'])
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

        af_second = (f"{af_base},loudnorm=I={CONFIG['LOUDNORM_I']}:TP={CONFIG['LOUDNORM_TP']}:LRA={CONFIG['LOUDNORM_LRA']}:" +
                     f"measured_I={metrics['measured_I'].group(1)}:measured_LRA={metrics['measured_LRA'].group(1)}:" +
                     f"measured_TP={metrics['measured_TP'].group(1)}:measured_thresh={metrics['measured_thresh'].group(1)}")
        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG['ACODEC'], '-ar', CONFIG['AR'],
               '-map_metadata', CONFIG['MAP_METADATA'], '-af', af_second, intermediate_wav, '-y']
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(intermediate_wav):
            logger.error(f"Error creating intermediate WAV for {input_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
            return False

    if CONFIG['OUTPUT_FORMAT'] == 'wav':
        os.rename(intermediate_wav, output_file)
    else:
        final_cmd = ['ffmpeg', '-i', intermediate_wav, '-c:a', CONFIG['OUTPUT_FORMAT']]
        if CONFIG['OUTPUT_FORMAT'] == 'wavpack':
            final_cmd.extend(['-compression_level', CONFIG['WAVPACK_COMPRESSION']])
        elif CONFIG['OUTPUT_FORMAT'] == 'flac':
            final_cmd.extend(['-compression_level', CONFIG['FLAC_COMPRESSION']])
        final_cmd.extend([output_file, '-y'])
        try:
            _, stderr, rc = run_command(final_cmd)
            if rc != 0:
                logger.error(f"Error converting {input_file} to {CONFIG['OUTPUT_FORMAT']}. Check {local_log}")
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
    with open(TEMP_FILES['PEAK_LOG']) as f:
        for line in f:
            if line.startswith(f"{output_file}:Output:"):
                _, _, output_max_volume, output_peak_level = line.strip().split(':', 3)
                break
    file_size_kb = os.path.getsize(output_file) / 1024
    logger.info(f"Converted {input_file} -> {output_file} (Size: {file_size_kb:.1f} KB)")
    logger.debug(f"Output - Max Volume: {output_max_volume}, Peak Level: {output_peak_level}")

    if CONFIG['ENABLE_VISUALIZATION']:
        vis_file = normalize_path(os.path.join(spectrogram_dir, f"{base_name}.png"))
        if CONFIG['VISUALIZATION_TYPE'] == 'waveform':
            cmd = ['ffmpeg', '-i', output_file, '-filter_complex', f"showwavespic=s={CONFIG['VISUALIZATION_SIZE']}", vis_file, '-y']
        else:
            cmd = ['ffmpeg', '-i', output_file, '-lavfi', f"showspectrumpic=s={CONFIG['VISUALIZATION_SIZE']}:mode={CONFIG['SPECTROGRAM_MODE']}", vis_file, '-y']
        _, stderr, rc = run_command(cmd)
        if rc != 0:
            logger.error(f"Error generating {CONFIG['VISUALIZATION_TYPE']} for {output_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
        else:
            logger.info(f"Generated {CONFIG['VISUALIZATION_TYPE']}: {vis_file}")

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
    logger.info(f"Starting parallel processing with {CONFIG['PARALLEL_JOBS']} workers for {len(files)} files")
    with ThreadPoolExecutor(max_workers=CONFIG['PARALLEL_JOBS']) as executor:
        results = []
        for file, volume in volume_map:
            results.append(executor.submit(process_file, file, output_dir, volume, log_file))
        outcomes = [future.result() for future in results]
    logger.info(f"Completed parallel processing for {len(files)} files")
    return all(outcomes)

def print_volume_summary(volume_data: List[dict], volume_maps: List[List[Tuple[str, str]]], log_file: Optional[str] = None):
    logger.info("\n=== Volume Adjustment Summary ===")
    logger.info(f"{'File':<40} {'y (dB) ffmpeg auto-tuning':<25} {'WAV Max Volume (dB)':<20} {'Applied Volume (dB)':<20}")
    logger.info("-" * 105)

    volume_dict = {}
    for v_map in volume_maps:
        volume_dict.update({file: vol for file, vol in v_map})

    for entry in volume_data:
        applied_volume = volume_dict.get(entry['file'], "N/A")
        logger.info(f"{entry['file'][:38]:<40} {entry['y']:<25.1f} {entry['wav_max_volume']:<20.1f} {applied_volume:<20}")
    logger.info("-" * 105)

    if CONFIG['ADDITION'] != '0dB':
        logger.info(f"Applied additional volume adjustment: {CONFIG['ADDITION']}")

    if log_file:
        with open(log_file, 'a') as f:
            f.write("\n=== Volume Adjustment Summary ===\n")
            f.write(f"{'File':<40} {'y (dB) ffmpeg auto-tuning':<25} {'WAV Max Volume (dB)':<20} {'Applied Volume (dB)':<20}\n")
            f.write("-" * 105 + "\n")
            for entry in volume_data:
                applied_volume = volume_dict.get(entry['file'], "N/A")
                f.write(f"{entry['file'][:38]:<40} {entry['y']:<25.1f} {entry['wav_max_volume']:<20.1f} {applied_volume:<20}\n")
            f.write("-" * 105 + "\n")
            if CONFIG['ADDITION'] != '0dB':
                f.write(f"Applied additional volume adjustment: {CONFIG['ADDITION']}\n")

def main():
    parser = argparse.ArgumentParser(
        description="PureTone - DSD to High-Quality Audio Converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )

    parser.add_argument('-h', '--help', action='help', help="Show this help message and exit.")
    parser.add_argument('--format', choices=['wav', 'wavpack', 'flac'], default='wav', help="Output format: 'wav', 'wavpack', or 'flac'. Default: wav")
    parser.add_argument('--codec', help="Audio codec for WAV output (e.g., pcm_s32le). Default: pcm_s24le")
    parser.add_argument('--sample-rate', type=int, help="Sample rate in Hz (e.g., 88200). Default: 176400")
    parser.add_argument('--map-metadata', help="Metadata mapping (e.g., 0 to keep). Default: 0")
    parser.add_argument('--loudnorm-I', help="Integrated loudness target in LUFS. Default: -14")
    parser.add_argument('--loudnorm-TP', help="True peak limit in dBTP. Default: -1")
    parser.add_argument('--loudnorm-LRA', help="Loudness range in LU. Default: 20")
    parser.add_argument('--volume', help="Volume adjustment: fixed value (e.g., '2.5dB'), 'auto', or 'analysis'. Default: None")
    parser.add_argument('--addition', help="Additional volume adjustment (e.g., '1dB') to apply after auto calculation", default='0dB')
    parser.add_argument('--headroom-limit', type=float, help="Maximum allowed peak volume in dB. Default: -0.5")
    parser.add_argument('--resampler', help="Resampler engine (e.g., soxr). Default: soxr")
    parser.add_argument('--precision', type=int, help="Resampler precision (e.g., 20-28). Default: 28")
    parser.add_argument('--cheby', choices=['0', '1'], help="Enable Chebyshev mode for SoX resampler. Default: 1")
    parser.add_argument('--spectrogram', nargs='*', help="Enable visualization: '<width>x<height> [type [mode]]'. Default: disabled")
    parser.add_argument('--compression-level', type=int, help="Compression level: 0-6 for WavPack, 0-12 for FLAC. Default: 0")
    parser.add_argument('--skip-existing', action='store_true', help="Skip if output exists. Default: False")
    parser.add_argument('--parallel', type=int, help="Number of parallel jobs. Default: 2")
    parser.add_argument('--log', help="File to save analysis results. Default: None")
    parser.add_argument('--debug', action='store_true', help="Enable debug logging. Default: False")
    parser.add_argument('path', help="Path to a .dsf file or directory")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    CONFIG['OUTPUT_FORMAT'] = args.format
    if args.volume:
        if args.volume not in ('auto', 'analysis') and not validate_volume(args.volume):
            logger.error("Volume must be 'auto', 'analysis', or in format 'XdB' (e.g., '3dB', '-2.5dB')")
            sys.exit(1)
        CONFIG['VOLUME'] = args.volume

    if args.addition and not validate_volume(args.addition):
        logger.error("Addition must be in format 'XdB' (e.g., '1dB', '-2.5dB')")
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
            logger.error(f"Invalid compression level for {CONFIG['OUTPUT_FORMAT']}")
            sys.exit(1)
    if args.skip_existing: CONFIG['SKIP_EXISTING'] = True
    if args.parallel: CONFIG['PARALLEL_JOBS'] = max(1, args.parallel)
    log_file = args.log

    for cmd in ['ffmpeg', 'ffprobe']:
        if shutil.which(cmd) is None:
            logger.error(f"{cmd} not found. Please install it.")
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
        if args.volume == 'auto':
            volume_map, volume_data = calculate_volume_adjustment([str(path)], "", log_file)
            all_volume_data.extend(volume_data)
            all_volume_maps.append(volume_map)
            if volume_map:
                success &= process_file(str(path), output_dir, volume_map[0][1], log_file)
            else:
                success = False
        else:
            success &= process_file(str(path), output_dir, args.volume, log_file)
    elif path.is_dir():
        os.chdir(path)
        files = [str(f) for f in Path('.').glob('*.dsf')]
        subdirs = [d for d in Path('.').glob('*') if d.is_dir() and any(f.suffix == '.dsf' for f in d.glob('*.dsf'))]

        if args.volume == 'auto':
            if files:
                logger.info(f"Processing directory: {path}")
                volume_map, volume_data = calculate_volume_adjustment(files, "", log_file)
                all_volume_data.extend(volume_data)
                all_volume_maps.append(volume_map)
                success &= process_files_in_parallel(files, os.path.join(path, OUTPUT_DIRS[args.format]), volume_map, log_file)
            if subdirs:
                logger.info(f"Processing subdirectories in {path}: {', '.join(str(s) for s in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    volume_map, volume_data = calculate_volume_adjustment(subdir_files, str(subdir), log_file)
                    all_volume_data.extend(volume_data)
                    all_volume_maps.append(volume_map)
                    success &= process_files_in_parallel(subdir_files, os.path.join(subdir, OUTPUT_DIRS[args.format]), volume_map, log_file)
            if not files and not subdirs:
                logger.error(f"No .dsf files found in {path} or its subdirectories")
                success = False
        else:
            if files:
                logger.info(f"Processing directory: {path}")
                success &= process_files_in_parallel(files, os.path.join(path, OUTPUT_DIRS[args.format]), [(f, args.volume) for f in files], log_file)
            if subdirs:
                logger.info(f"Processing subdirectories in {path}: {', '.join(str(s) for s in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    success &= process_files_in_parallel(subdir_files, os.path.join(subdir, OUTPUT_DIRS[args.format]), [(f, args.volume) for f in subdir_files], log_file)
            if not files and not subdirs:
                logger.error(f"No .dsf files found in {path} or its subdirectories")
                success = False
    else:
        logger.error(f"Invalid path: {args.path}")
        sys.exit(1)

    elapsed_time = int(time.time() - start_time)
    if success:
        logger.info("Process completed successfully!")
    else:
        logger.error("Process completed with errors!")
    logger.info(f"Elapsed time: {elapsed_time} seconds")

    if all_volume_data and args.volume == 'auto':
        print_volume_summary(all_volume_data, all_volume_maps, log_file)

    if log_file:
        with open(log_file, 'a') as f:
            f.write(f"{'Process completed successfully!' if success else 'Process completed with errors!'}\n")
            f.write(f"Elapsed time: {elapsed_time} seconds\n")

    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            os.remove(temp_file)

    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)

if __name__ == "__main__":
    main()