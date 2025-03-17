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
from typing import List, Tuple, Dict, Optional
import shutil

# Configuração de logging (similar ao dmesg)
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
}

TEMP_FILES: Dict[str, str] = {}

def validate_volume(volume: str) -> bool:
    """Valida se o volume está no formato correto (ex.: '2.5dB', '-3dB')."""
    return bool(re.match(r'^-?\d+(\.\d+)?dB$', volume))

def validate_resolution(resolution: str) -> bool:
    """Valida se a resolução está no formato correto (ex.: '1920x1080')."""
    return bool(re.match(r'^\d+x\d+$', resolution))

def run_command(command: List[str], timeout: int = 600) -> Tuple[int, str, str]:
    """Executa um comando e retorna o código de saída, stdout e stderr."""
    try:
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return process.returncode, process.stdout, process.stderr
    except subprocess.TimeoutExpired as e:
        return 1, e.stdout.decode(), e.stderr.decode()

def get_max_volume(input_file: str) -> float:
    """Obtém o volume máximo usando o filtro 'volumedetect' do FFmpeg."""
    cmd = ['ffmpeg', '-i', input_file, '-af', 'volumedetect', '-f', 'null', '-']
    logger.debug(f"Executing command: {' '.join(cmd)}")
    ret, stdout, stderr = run_command(cmd)
    if ret != 0:
        logger.error(f"Failed to detect volume for {input_file}: {stderr}")
        return float('-inf')
    match = re.search(r'max_volume: (-?\d+\.\d+) dB', stderr)
    return float(match.group(1)) if match else float('-inf')

def get_peak_level(input_file: str) -> float:
    """Obtém o nível de pico usando o filtro 'astats' do FFmpeg."""
    cmd = ['ffmpeg', '-i', input_file, '-af', 'astats=metadata=1,ametadata=print:key=lavfi.astats.Overall.Peak_level', '-f', 'null', '-']
    logger.debug(f"Executing command: {' '.join(cmd)}")
    ret, stdout, stderr = run_command(cmd)
    if ret != 0:
        logger.error(f"Failed to detect peak level for {input_file}: {stderr}")
        return float('-inf')
    match = re.search(r'lavfi\.astats\.Overall\.Peak_level=(-?\d+\.\d+)', stderr)
    return float(match.group(1)) if match else float('-inf')

def measure_loudness(input_file: str) -> Dict[str, float]:
    """Mede os parâmetros de loudness usando o filtro 'loudnorm' do FFmpeg."""
    cmd = [
        'ffmpeg', '-i', input_file, '-acodec', CONFIG['ACODEC'], '-ar', CONFIG['AR'],
        '-map_metadata', CONFIG['MAP_METADATA'],
        '-af', f"aresample=resampler={CONFIG['RESAMPLER']}:precision={CONFIG['PRECISION']}:cheby={CONFIG['CHEBY']},loudnorm=I={CONFIG['LOUDNORM_I']}:TP={CONFIG['LOUDNORM_TP']}:LRA={CONFIG['LOUDNORM_LRA']}:print_format=summary",
        '-f', 'null', '-'
    ]
    logger.debug(f"Executing command: {' '.join(cmd)}")
    ret, stdout, stderr = run_command(cmd)
    if ret != 0:
        logger.error(f"Failed to measure loudness for {input_file}: {stderr}")
        return {}
    
    measures = {}
    patterns = {
        'measured_I': r'Input Integrated:\s+(-?\d+\.\d+)',
        'measured_LRA': r'Input LRA:\s+(-?\d+\.\d+)',
        'measured_TP': r'Input True Peak:\s+(-?\d+\.\d+)',
        'measured_thresh': r'Input Threshold:\s+(-?\d+\.\d+)'
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, stderr)
        if match:
            measures[key] = float(match.group(1))
    return measures

def convert_file(input_file: str, output_dir: str, volume_adjust: Optional[str] = None) -> bool:
    """Converte um arquivo DSF para o formato especificado."""
    output_ext = CONFIG['OUTPUT_FORMAT'] if CONFIG['OUTPUT_FORMAT'] != 'wavpack' else 'wv'
    output_file = os.path.join(output_dir, f"{Path(input_file).stem}.{output_ext}")
    intermediate_file = os.path.join(output_dir, f"{Path(input_file).stem}_intermediate.wav")
    TEMP_FILES[input_file] = intermediate_file

    if CONFIG['SKIP_EXISTING'] and os.path.exists(output_file):
        logger.info(f"Skipping {input_file}: {output_file} already exists (--skip-existing enabled)")
        return True

    if CONFIG['OVERWRITE'] and os.path.exists(output_file):
        logger.info(f"Overwriting {output_file} due to OVERWRITE=True")

    logger.debug(f"Processing file: {input_file}")
    measures = measure_loudness(input_file) if not volume_adjust else {}
    
    loudnorm_filter = (
        f"aresample=resampler={CONFIG['RESAMPLER']}:precision={CONFIG['PRECISION']}:cheby={CONFIG['CHEBY']},"
        f"loudnorm=I={CONFIG['LOUDNORM_I']}:TP={CONFIG['LOUDNORM_TP']}:LRA={CONFIG['LOUDNORM_LRA']}"
        f"{':measured_I='+str(measures['measured_I']) if measures else ''}"
        f"{':measured_LRA='+str(measures['measured_LRA']) if measures else ''}"
        f"{':measured_TP='+str(measures['measured_TP']) if measures else ''}"
        f"{':measured_thresh='+str(measures['measured_thresh']) if measures else ''}"
    )
    volume_filter = f",volume={volume_adjust}" if volume_adjust else ""
    
    cmd = [
        'ffmpeg', '-i', input_file, '-acodec', CONFIG['ACODEC'], '-ar', CONFIG['AR'],
        '-map_metadata', CONFIG['MAP_METADATA'], '-af', loudnorm_filter + volume_filter,
        intermediate_file, '-y'
    ]
    logger.debug(f"Executing command: {' '.join(cmd)}")
    ret, _, stderr = run_command(cmd)
    if ret != 0:
        logger.error(f"Failed to convert {input_file} to intermediate: {stderr}")
        return False

    if CONFIG['OUTPUT_FORMAT'] == 'flac':
        cmd = ['ffmpeg', '-i', intermediate_file, '-c:a', 'flac', '-compression_level', CONFIG['FLAC_COMPRESSION'], output_file, '-y']
    elif CONFIG['OUTPUT_FORMAT'] == 'wavpack':
        cmd = ['ffmpeg', '-i', intermediate_file, '-c:a', 'wavpack', '-compression_level', CONFIG['WAVPACK_COMPRESSION'], output_file, '-y']
    else:
        cmd = ['ffmpeg', '-i', intermediate_file, output_file, '-y']
    
    logger.debug(f"Executing command: {' '.join(cmd)}")
    ret, _, stderr = run_command(cmd)
    if ret != 0:
        logger.error(f"Failed to convert intermediate to {output_file}: {stderr}")
        return False

    size_kb = os.path.getsize(output_file) / 1024
    logger.info(f"Converted {input_file} -> {output_file} (Size: {size_kb:.1f} KB)")
    
    max_volume = get_max_volume(output_file)
    peak_level = get_peak_level(output_file)
    logger.debug(f"Output - Max Volume: {max_volume:.1f} dB, Peak Level: {peak_level:.6f} dBFS")
    
    return True

def process_subdirectory(subdir: str, volume_adjust: Optional[str] = None) -> bool:
    """Processa todos os arquivos DSF em um subdiretório."""
    output_dir = os.path.join(subdir, CONFIG['OUTPUT_FORMAT'])
    os.makedirs(output_dir, exist_ok=True)
    
    dsf_files = [f for f in os.listdir(subdir) if f.endswith('.dsf')]
    if not dsf_files:
        logger.warning(f"No .dsf files found in {subdir}")
        return True

    with ThreadPoolExecutor(max_workers=CONFIG['PARALLEL_JOBS']) as executor:
        futures = {executor.submit(convert_file, os.path.join(subdir, f), output_dir, volume_adjust): f for f in dsf_files}
        return all(future.result() for future in futures)

def analyze_volume(input_path: str) -> Tuple[List[float], bool]:
    """Analisa o volume de todos os arquivos DSF no caminho fornecido."""
    headrooms = []
    is_dir = os.path.isdir(input_path)
    files = [input_path] if not is_dir else [
        os.path.join(root, f) for root, _, fs in os.walk(input_path) for f in fs if f.endswith('.dsf')
    ]

    for input_file in files:
        max_volume = get_max_volume(input_file)
        peak_level = get_peak_level(input_file)
        headroom = CONFIG['HEADROOM_LIMIT'] - max_volume
        headrooms.append(headroom)
        
        logger.info(f"Input File: {input_file}")
        logger.info(f"  Max Volume: {max_volume:.1f} dB")
        logger.info(f"  Peak Level: {peak_level:.6f} dBFS")
        logger.info(f"  Headroom to {CONFIG['HEADROOM_LIMIT']} dB: {headroom:.1f} dB")
    
    return headrooms, True

def main():
    parser = argparse.ArgumentParser(
        description="PureTone - DSD to High-Quality Audio Converter\n\n"
                    "Converts DSD (.dsf) files to WAV, WavPack, or FLAC with advanced audio processing options.",
        epilog="Examples:\n"
               "  Basic conversion to WAV:\n"
               "    ./puretone.py /path/to/directory\n"
               "  Convert to FLAC with debug output:\n"
               "    ./puretone.py --format flac --debug /path/to/directory\n"
               "  Auto volume adjustment with 4 parallel jobs:\n"
               "    ./puretone.py --volume auto --parallel 4 /path/to/directory\n"
               "  Analyze volume without conversion:\n"
               "    ./puretone.py --volume analysis /path/to/directory\n"
               "  Manual volume boost by 2.5dB to FLAC:\n"
               "    ./puretone.py --format flac --volume 2.5dB /path/to/file.dsf\n"
               "  Custom loudnorm and codec settings:\n"
               "    ./puretone.py --loudnorm-I -16 --loudnorm-TP -2 --codec pcm_s32le --sample-rate 192000 /path/to/directory\n"
               "  Generate spectrograms with custom size:\n"
               "    ./puretone.py --spectrogram 1280x720 spectrogram separate /path/to/directory\n"
               "  Skip existing files with log output:\n"
               "    ./puretone.py --skip-existing --log output.log /path/to/directory\n\n"
               "Calculation Formulas:\n"
               "  1. Headroom Calculation (for '--volume auto' and '--volume analysis'):\n"
               "     Headroom = Target_Level - Max_Volume\n"
               "     - Target_Level: Desired headroom limit (default: -0.5 dB, adjustable via --headroom-limit).\n"
               "     - Max_Volume: Maximum volume detected by FFmpeg 'volumedetect' filter (in dB).\n"
               "     Example: If Max_Volume = -1.3 dB and Target_Level = -0.5 dB, Headroom = -0.5 - (-1.3) = 0.8 dB.\n"
               "  2. Volume Adjustment (for '--volume auto'):\n"
               "     Volume_Adjustment = min(Headroom_i) for all files i in a subdirectory.\n"
               "     - Applied as an FFmpeg 'volume' filter (e.g., 'volume=0.8dB').\n"
               "     Example: If Headroom for files is [0.8 dB, 2.2 dB], Volume_Adjustment = 0.8 dB.\n"
               "  3. Loudness Normalization (for '--loudnorm'):\n"
               "     Uses FFmpeg 'loudnorm' filter with two passes:\n"
               "     - Pass 1: Measures I (integrated loudness), LRA (loudness range), TP (true peak).\n"
               "     - Pass 2: Normalizes to target I, TP, and LRA values.\n"
               "     Formula: Output = Input * Gain, where Gain is calculated by FFmpeg based on:\n"
               "       I_target = --loudnorm-I (default: -14 LUFS),\n"
               "       TP_max = --loudnorm-TP (default: -1 dBTP),\n"
               "       LRA_target = --loudnorm-LRA (default: 20 LU).\n"
               "  4. Headroom Statistics (for '--volume analysis'):\n"
               "     - Min_Headroom = min(Headroom_i),\n"
               "     - Max_Headroom = max(Headroom_i),\n"
               "     - Avg_Headroom = sum(Headroom_i) / n,\n"
               "     where Headroom_i is the headroom for each file i, and n is the number of files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )
    
    parser.add_argument(
        'path',
        help="Path to a directory containing .dsf files or a single .dsf file.\n"
             "Example: './puretone.py Music/Aero' or './puretone.py Music/Test1/06 Sweet Emotion.dsf'"
    )
    parser.add_argument(
        '--format',
        choices=['wav', 'wavpack', 'flac'],
        default=CONFIG['OUTPUT_FORMAT'],
        help=f"Output format. Default: {CONFIG['OUTPUT_FORMAT']}.\n"
             "Example: '--format flac' converts to FLAC."
    )
    parser.add_argument(
        '--codec',
        default=CONFIG['ACODEC'],
        help=f"Audio codec for output. Default: {CONFIG['ACODEC']}.\n"
             "Example: '--codec pcm_s32le' for 32-bit PCM."
    )
    parser.add_argument(
        '--sample-rate',
        type=int,
        default=int(CONFIG['AR']),
        help=f"Sample rate in Hz. Default: {CONFIG['AR']}.\n"
             "Example: '--sample-rate 192000' for 192 kHz."
    )
    parser.add_argument(
        '--map-metadata',
        default=CONFIG['MAP_METADATA'],
        help=f"Metadata mapping (0 to keep, -1 to strip). Default: {CONFIG['MAP_METADATA']}.\n"
             "Example: '--map-metadata -1' removes metadata."
    )
    parser.add_argument(
        '--loudnorm-I',
        default=CONFIG['LOUDNORM_I'],
        help=f"Integrated loudness target in LUFS. Default: {CONFIG['LOUDNORM_I']}.\n"
             "Example: '--loudnorm-I -16' for quieter output."
    )
    parser.add_argument(
        '--loudnorm-TP',
        default=CONFIG['LOUDNORM_TP'],
        help=f"True peak limit in dBTP. Default: {CONFIG['LOUDNORM_TP']}.\n"
             "Example: '--loudnorm-TP -2' for lower peak limit."
    )
    parser.add_argument(
        '--loudnorm-LRA',
        default=CONFIG['LOUDNORM_LRA'],
        help=f"Loudness range target in LU. Default: {CONFIG['LOUDNORM_LRA']}.\n"
             "Example: '--loudnorm-LRA 15' for tighter range."
    )
    parser.add_argument(
        '--volume',
        default=CONFIG['VOLUME'],
        help=f"Volume adjustment: 'auto' for headroom-based, 'analysis' to only analyze, or a value like '2.5dB'. Default: {CONFIG['VOLUME']} (uses loudnorm).\n"
             "Examples: '--volume auto', '--volume analysis', '--volume -3dB'."
    )
    parser.add_argument(
        '--headroom-limit',
        type=float,
        default=CONFIG['HEADROOM_LIMIT'],
        help=f"Headroom limit in dB for '--volume auto'. Default: {CONFIG['HEADROOM_LIMIT']}.\n"
             "Example: '--headroom-limit -1.0' for more headroom."
    )
    parser.add_argument(
        '--resampler',
        default=CONFIG['RESAMPLER'],
        help=f"Resampler engine. Default: {CONFIG['RESAMPLER']}.\n"
             "Example: '--resampler soxr' for high-quality resampling."
    )
    parser.add_argument(
        '--precision',
        type=int,
        default=int(CONFIG['PRECISION']),
        help=f"Resampler precision in bits. Default: {CONFIG['PRECISION']}.\n"
             "Example: '--precision 20' for lower precision."
    )
    parser.add_argument(
        '--cheby',
        choices=['0', '1'],
        default=CONFIG['CHEBY'],
        help=f"Chebyshev mode for resampling (0 = off, 1 = on). Default: {CONFIG['CHEBY']}.\n"
             "Example: '--cheby 0' to disable."
    )
    parser.add_argument(
        '--spectrogram',
        nargs='*',
        default=None,
        help=f"Enable visualization: [size] [type] [mode]. Size (default: {CONFIG['VISUALIZATION_SIZE']}), type (default: {CONFIG['VISUALIZATION_TYPE']}), mode (default: {CONFIG['SPECTROGRAM_MODE']} for spectrogram).\n"
             "Example: '--spectrogram 1280x720 spectrogram separate' for separate spectrograms."
    )
    parser.add_argument(
        '--compression-level',
        type=int,
        default=None,
        help=f"Compression level: 0-6 for WavPack (default: {CONFIG['WAVPACK_COMPRESSION']}), 0-12 for FLAC (default: {CONFIG['FLAC_COMPRESSION']}).\n"
             "Example: '--compression-level 8' with '--format flac' for higher compression."
    )
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        default=CONFIG['SKIP_EXISTING'],
        help=f"Skip files that already exist. Default: {CONFIG['SKIP_EXISTING']}.\n"
             "Example: '--skip-existing' to avoid reprocessing."
    )
    parser.add_argument(
        '--parallel',
        type=int,
        default=CONFIG['PARALLEL_JOBS'],
        help=f"Number of parallel jobs for processing files within subdirectories. Default: {CONFIG['PARALLEL_JOBS']}.\n"
             "Example: '--parallel 4' for 4 concurrent conversions."
    )
    parser.add_argument(
        '--log',
        default=None,
        help="File to save analysis and processing logs. Default: None (terminal only).\n"
             "Example: '--log output.log' saves logs to 'output.log'."
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        default=False,
        help="Enable detailed debug logging. Default: False.\n"
             "Example: '--debug' to see FFmpeg commands and detailed steps."
    )
    parser.add_argument(
        '-h', '--help',
        action='help',
        help="Show this help message and exit."
    )

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    CONFIG['OUTPUT_FORMAT'] = args.format
    if args.volume:
        if args.volume not in ('auto', 'analysis') and not validate_volume(args.volume):
            logger.error("Volume must be 'auto', 'analysis', or in format 'XdB' (e.g., '3dB', '-2.5dB')")
            sys.exit(1)
        CONFIG['VOLUME'] = args.volume

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
    if args.parallel: CONFIG['PARALLEL_JOBS'] = args.parallel
    log_file = args.log

    start_time = time.time()
    success = True

    input_path = args.path
    if os.path.isfile(input_path) and input_path.endswith('.dsf'):
        output_dir = os.path.join(os.path.dirname(input_path), CONFIG['OUTPUT_FORMAT'])
        os.makedirs(output_dir, exist_ok=True)
        success = convert_file(input_path, output_dir)
    elif os.path.isdir(input_path):
        subdirs = [os.path.join(input_path, d) for d in os.listdir(input_path) if os.path.isdir(os.path.join(input_path, d))]
        logger.info(f"Processing subdirectories in {input_path}: {', '.join(os.path.basename(d) for d in subdirs)}")
        
        if CONFIG['VOLUME'] == 'analysis':
            headrooms, success = analyze_volume(input_path)
            if headrooms:
                logger.info(f"Headroom Statistics (across {len(headrooms)} files):")
                logger.info(f"  Min: {min(headrooms):.1f} dB, Max: {max(headrooms):.1f} dB, Avg: {sum(headrooms)/len(headrooms):.1f} dB")
        elif CONFIG['VOLUME'] == 'auto':
            headrooms, _ = analyze_volume(input_path)
            for subdir in subdirs:
                subdir_headrooms = [h for f, h in zip(files, headrooms) if os.path.dirname(f) == subdir]
                if subdir_headrooms:
                    volume_adjust = f"{min(subdir_headrooms):.1f}dB"
                    logger.info(f"Calculated volume adjustment: {volume_adjust} (smallest headroom from {os.path.basename(subdir)})")
                    success &= process_subdirectory(subdir, volume_adjust)
        else:
            volume_adjust = CONFIG['VOLUME'] if CONFIG['VOLUME'] and validate_volume(CONFIG['VOLUME']) else None
            for subdir in subdirs:
                success &= process_subdirectory(subdir, volume_adjust)
    else:
        logger.error(f"Invalid path: {input_path}")
        sys.exit(1)

    elapsed_time = int(time.time() - start_time)
    if success:
        logger.info("Process completed successfully!")
    else:
        logger.error("Process completed with errors!")
    logger.info(f"Elapsed time: {elapsed_time} seconds")
    if log_file:
        with open(log_file, 'a') as f:
            f.write(f"{'Process completed successfully!' if success else 'Process completed with errors!'}\n")
            f.write(f"Elapsed time: {elapsed_time} seconds\n")

    # Limpeza de arquivos temporários
    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            os.remove(temp_file)
    
    sys.stdout.flush()

if __name__ == "__main__":
    main()