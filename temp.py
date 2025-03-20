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
import termios
import tty

# Salvar o estado do terminal no início
ORIGINAL_TERMINAL_STATE = None
if sys.stdin.isatty():
    ORIGINAL_TERMINAL_STATE = termios.tcgetattr(sys.stdin)

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

# Diretórios de saída por formato
OUTPUT_DIRS = {'wav': 'wv', 'wavpack': 'wvpk', 'flac': 'flac'}

# Extensões de arquivo por formato
FORMAT_EXTENSIONS = {'wav': 'wav', 'wavpack': 'wv', 'flac': 'flac'}

# Arquivos temporários
TEMP_FILES = {
    'PEAK_LOG': f"/tmp/puretone_{os.getpid()}_peaks.log",
    'HEADROOM_LOG': f"/tmp/puretone_{os.getpid()}_headroom.log",
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

def analyze_peaks(file: str, peak_log: str, log_type: str) -> None:
    _, stderr, rc = run_command(['ffmpeg', '-i', file, '-af', 'volumedetect', '-f', 'null', '-'])
    max_volume = re.search(r'max_volume: ([-0-9.]* dB)', stderr)
    max_volume = max_volume.group(1) if max_volume else 'Not detected'

    _, stderr, rc = run_command(['ffmpeg', '-i', file, '-af', 'astats=metadata=1,ametadata=print:key=lavfi.astats.Overall.Peak_level', '-f', 'null', '-'])
    peak_match = re.search(r'Peak_level=([-0-9.]+)', stderr)
    peak_level = f"{peak_match.group(1)} dBFS" if peak_match else 'Not detected'

    with open(peak_log, 'a') as f:
        f.write(f"{file}:{log_type}:{max_volume}:{peak_level}\n")

def analyze_volume_file(input_file: str, headroom_log: str, log_file: Optional[str] = None) -> None:
    analyze_peaks(input_file, TEMP_FILES['PEAK_LOG'], "Input")
    with open(TEMP_FILES['PEAK_LOG']) as f:
        for line in f:
            if line.startswith(f"{input_file}:Input:"):
                _, _, max_volume, peak_level = line.strip().split(':', 3)
                break

    logger.info(f"Input File: {input_file}")
    logger.info(f"  Max Volume: {max_volume}")
    logger.info(f"  Peak Level: {peak_level}")
    if log_file:
        with open(log_file, 'a') as f:
            f.write(f"Input File: {input_file}\n  Max Volume: {max_volume}\n  Peak Level: {peak_level}\n")

    if max_volume != 'Not detected':
        max_value = float(max_volume.replace(' dB', ''))
        headroom = CONFIG['HEADROOM_LIMIT'] - max_value
        logger.info(f"  Headroom to {CONFIG['HEADROOM_LIMIT']} dB: {headroom:.1f} dB")
        if log_file:
            with open(log_file, 'a') as f:
                f.write(f"  Headroom to {CONFIG['HEADROOM_LIMIT']} dB: {headroom:.1f} dB\n")
        if max_value > CONFIG['HEADROOM_LIMIT']:
            logger.warning(f"Max Volume ({max_volume}) exceeds {CONFIG['HEADROOM_LIMIT']} dB, risk of clipping!")
            if log_file:
                with open(log_file, 'a') as f:
                    f.write(f"  WARNING: Max Volume ({max_volume}) exceeds {CONFIG['HEADROOM_LIMIT']} dB, risk of clipping!\n")
        with open(headroom_log, 'a') as f:
            f.write(f"{headroom:.1f}:{input_file}\n")
    else:
        logger.warning(f"Headroom not calculable for {input_file} (peak data unavailable)")
        if log_file:
            with open(log_file, 'a') as f:
                f.write(f"  Headroom not calculable for {input_file} (peak data unavailable)\n")

def calculate_auto_volume(files: List[str], subdir: str, log_file: Optional[str] = None) -> str:
    if os.path.exists(TEMP_FILES['HEADROOM_LOG']):
        os.remove(TEMP_FILES['HEADROOM_LOG'])
    
    for file in files:
        analyze_volume_file(file, TEMP_FILES['HEADROOM_LOG'], log_file)

    if not os.path.exists(TEMP_FILES['HEADROOM_LOG']) or os.stat(TEMP_FILES['HEADROOM_LOG']).st_size == 0:
        logger.error(f"No valid headroom data found for auto volume calculation in {subdir or 'current directory'}")
        return None

    headroom_log = []
    with open(TEMP_FILES['HEADROOM_LOG']) as f:
        for line in f:
            headroom, file = line.strip().split(':', 1)
            headroom_log.append({'headroom': float(headroom), 'file': file})

    min_headroom = min(entry['headroom'] for entry in headroom_log)
    min_file = next(entry['file'] for entry in headroom_log if entry['headroom'] == min_headroom)

    volume = min_headroom
    for entry in headroom_log:
        new_max_volume = (CONFIG['HEADROOM_LIMIT'] - entry['headroom']) + min_headroom
        if new_max_volume > CONFIG['HEADROOM_LIMIT']:
            safe_adjustment = CONFIG['HEADROOM_LIMIT'] - (CONFIG['HEADROOM_LIMIT'] - entry['headroom'])
            volume = safe_adjustment
            logger.info(f"Adjusted volume to {volume:.1f}dB to keep {entry['file']} below {CONFIG['HEADROOM_LIMIT']} dB")
            if log_file:
                with open(log_file, 'a') as f:
                    f.write(f"Adjusted volume to {volume:.1f}dB to keep {entry['file']} below {CONFIG['HEADROOM_LIMIT']} dB\n")
            break
    else:
        logger.info(f"Calculated volume adjustment: {volume:.1f}dB (smallest headroom from {min_file})")
        if log_file:
            with open(log_file, 'a') as f:
                f.write(f"Calculated volume adjustment: {volume:.1f}dB (smallest headroom from {min_file})\n")

    return f"{volume:.1f}dB"

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
    """Clean up temporary files and reset terminal state before exiting."""
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
    # Restaurar o estado original do terminal
    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)
    logger.info("Cleanup completed. Exiting.")
    sys.exit(1)

def resolve_path(path_str: str) -> Path:
    """Resolve the provided path, assuming current directory if no prefix is given."""
    if '/' in path_str or path_str.startswith('./') or path_str.startswith('../'):
        return Path(path_str)
    return Path(os.path.join(os.getcwd(), path_str))

def process_files_in_parallel(files: List[str], output_dir: str, volume: str = None, log_file: Optional[str] = None) -> bool:
    """Process a list of files in parallel using ThreadPoolExecutor."""
    logger.info(f"Starting parallel processing with {CONFIG['PARALLEL_JOBS']} workers for {len(files)} files")
    with ThreadPoolExecutor(max_workers=CONFIG['PARALLEL_JOBS']) as executor:
        results = list(executor.map(lambda f: process_file(f, output_dir, volume, log_file), files))
    logger.info(f"Completed parallel processing for {len(files)} files")
    return all(results)

def main():
    parser = argparse.ArgumentParser(
        description="""
PureTone - DSD to High-Quality Audio Converter

PureTone is a Python tool designed to convert DSD (.dsf) audio files into high-quality formats (WAV, WavPack, FLAC) using FFmpeg. It provides advanced features like volume normalization, resampling, peak analysis, and optional visualization (spectrograms or waveforms). The tool supports both single files and directories with parallel processing capabilities.

### Features:
- Convert .dsf files to WAV, WavPack, or FLAC with customizable codecs and compression.
- Adjust volume manually, automatically, or analyze without conversion.
- Resample audio with high precision using the SoX resampler (soxr).
- Generate spectrograms or waveforms for visual analysis.
- Process multiple files in parallel for efficiency.

### Usage Examples and Flow:
1. **Convert a single file to WAV with default settings:**
   `$ python3 puretone.py /path/to/file.dsf`
   - **Flow**: Checks if the path is a .dsf file, creates an output directory 'wv', processes the file using default loudness normalization (I=-14, TP=-1, LRA=20), resamples to 176400 Hz with soxr, and saves as WAV. No volume adjustment unless specified.

2. **Convert a directory to FLAC with automatic volume adjustment and 4 parallel jobs:**
   `$ python3 puretone.py --format flac --volume auto --parallel 4 /path/to/dir`
   - **Flow**: Scans the directory for .dsf files, creates a 'flac' subdirectory, analyzes headroom for all files, calculates a volume adjustment to avoid clipping (based on smallest headroom), processes files in parallel (4 threads), converts to FLAC with compression level 0, and cleans up temporary files.

3. **Analyze volume without conversion and save results to a log:**
   `$ python3 puretone.py --volume analysis --log results.txt /path/to/dir`
   - **Flow**: Scans the directory (and subdirectories) for .dsf files, analyzes peak volume and headroom for each, logs results (max volume, peak level, headroom) to 'results.txt', calculates statistics (min, max, avg headroom), and exits without conversion.

4. **Generate a spectrogram with custom resolution:**
   `$ python3 puretone.py --spectrogram 1280x720 spectrogram separate /path/to/file.dsf`
   - **Flow**: Processes the .dsf file to WAV (default format), creates a 'wv' directory, enables visualization, generates a spectrogram (1280x720, separate channels) in a 'spectrogram' subdirectory, and logs the result.

### Key Calculations and Logic:
- **Peak Analysis (analyze_peaks)**:
  - Uses FFmpeg's `volumedetect` to find `max_volume` (in dB) and `astats` for `Peak_level` (in dBFS).
  - Logic: Extracts peak data and writes to a log file for further processing.

- **Headroom Calculation (analyze_volume_file)**:
  - Formula: `headroom = HEADROOM_LIMIT - max_volume`.
  - If `max_volume > HEADROOM_LIMIT`, warns of clipping risk.
  - Example: If `max_volume = -0.2 dB` and `HEADROOM_LIMIT = -0.5 dB`, then `headroom = -0.5 - (-0.2) = -0.3 dB` (negative indicates clipping risk).

- **Auto Volume Adjustment (calculate_auto_volume)**:
  - Steps:
    1. Analyzes headroom for all files.
    2. Finds `min_headroom` (smallest headroom).
    3. Sets initial `volume = min_headroom`.
    4. For each file, checks if `new_max_volume = (HEADROOM_LIMIT - headroom) + min_headroom > HEADROOM_LIMIT`.
    5. If true, adjusts `volume = HEADROOM_LIMIT - (HEADROOM_LIMIT - headroom)` to prevent clipping.
  - Example: Files with headrooms [2.0, 1.0, 0.5], `HEADROOM_LIMIT = -0.5 dB`. Initial `volume = 0.5 dB`. If applying 0.5 dB to file with headroom 2.0 results in `-0.5 - 2.0 + 0.5 = -2.0 dB` (safe), but checks all files and adjusts if any exceed -0.5 dB.

- **Loudness Normalization (process_file)**:
  - Uses FFmpeg's `loudnorm` filter in two passes:
    1. Measures input metrics (I, LRA, TP, threshold).
    2. Applies normalization with target I, TP, LRA using measured values.
  - Formula: Adjusts audio to match `LOUDNORM_I`, `LOUDNORM_TP`, `LOUDNORM_LRA` while preserving dynamics.

### Default Parameters:
- ACODEC: pcm_s24le
- AR (Sample Rate): 176400 Hz
- MAP_METADATA: 0
- LOUDNORM_I: -14 LUFS
- LOUDNORM_TP: -1 dBTP
- LOUDNORM_LRA: 20 LU
- VOLUME: None
- RESAMPLER: soxr
- PRECISION: 28
- CHEBY: 1
- OUTPUT_FORMAT: wav
- WAVPACK_COMPRESSION: 0
- FLAC_COMPRESSION: 0
- OVERWRITE: True
- SKIP_EXISTING: False
- PARALLEL_JOBS: 2
- ENABLE_VISUALIZATION: False
- VISUALIZATION_TYPE: spectrogram
- VISUALIZATION_SIZE: 1920x1080
- SPECTROGRAM_MODE: combined
- HEADROOM_LIMIT: -0.5 dB
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )

    parser.add_argument(
        '-h', '--help', action='help',
        help="Show this help message and exit."
    )

    parser.add_argument('--format', choices=['wav', 'wavpack', 'flac'], default='wav',
                        help="Output format: 'wav' (uncompressed), 'wavpack' (lossless), or 'flac' (lossless). Default: wav")
    parser.add_argument('--codec', help="Audio codec for WAV output (e.g., pcm_s32le). Default: pcm_s24le")
    parser.add_argument('--sample-rate', type=int,
                        help="Sample rate in Hz (e.g., 88200, 176400). Default: 176400")
    parser.add_argument('--map-metadata', help="Metadata mapping (e.g., 0 to keep, -1 to strip). Default: 0")
    parser.add_argument('--loudnorm-I', help="Integrated loudness target in LUFS (e.g., -16). Default: -14")
    parser.add_argument('--loudnorm-TP', help="True peak limit in dBTP (e.g., -2). Default: -1")
    parser.add_argument('--loudnorm-LRA', help="Loudness range in LU (e.g., 15). Default: 20")
    parser.add_argument('--volume',
                        help="Volume adjustment: fixed value (e.g., '2.5dB', '-1dB'), 'auto' for automatic calculation, or 'analysis' to only analyze without conversion. Default: None")
    parser.add_argument('--headroom-limit', type=float,
                        help="Maximum allowed peak volume in dB before clipping warning (e.g., -1.0). Default: -0.5")
    parser.add_argument('--resampler', help="Resampler engine (e.g., soxr, speex). Default: soxr")
    parser.add_argument('--precision', type=int,
                        help="Resampler precision (higher is better, e.g., 20-28). Default: 28")
    parser.add_argument('--cheby', choices=['0', '1'],
                        help="Enable Chebyshev mode for SoX resampler (1 = on, 0 = off). Default: 1")
    parser.add_argument('--spectrogram', nargs='*',
                        help="Enable visualization: '<width>x<height> [type [mode]]' (e.g., '1920x1080 waveform' or '1280x720 spectrogram separate'). Types: 'spectrogram', 'waveform'. Modes: 'combined', 'separate'. Default: disabled")
    parser.add_argument('--compression-level', type=int,
                        help="Compression level: 0-6 for WavPack, 0-12 for FLAC. Default: 0")
    parser.add_argument('--skip-existing', action='store_true',
                        help="Skip processing if output file exists. Default: False (overwrites)")
    parser.add_argument('--parallel', type=int,
                        help="Number of parallel jobs for directory processing. Default: 2")
    parser.add_argument('--log', help="File to save analysis results (e.g., 'log.txt'). Default: None")
    parser.add_argument('--debug', action='store_true',
                        help="Enable detailed debug logging. Default: False")
    parser.add_argument('path', help="Path to a .dsf file or directory containing .dsf files")

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
    if args.parallel: CONFIG['PARALLEL_JOBS'] = max(1, args.parallel)  # Ensure at least 1 worker
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

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    if path.is_file() and path.suffix == '.dsf':
        output_dir = os.path.join(path.parent, OUTPUT_DIRS[args.format])
        if args.volume == 'analysis':
            analyze_volume_file(str(path), TEMP_FILES['HEADROOM_LOG'], log_file)
        elif args.volume == 'auto':
            volume = calculate_auto_volume([str(path)], "", log_file)
            if volume:
                success &= process_file(str(path), output_dir, volume, log_file)
        else:
            success &= process_file(str(path), output_dir, args.volume, log_file)
    elif path.is_dir():
        os.chdir(path)
        files = [str(f) for f in Path('.').glob('*.dsf')]
        subdirs = [d for d in Path('.').glob('*') if d.is_dir() and any(f.suffix == '.dsf' for f in d.glob('*.dsf'))]

        if args.volume == 'analysis':
            if files:
                logger.info(f"Analyzing directory: {path}")
                for file in files:
                    analyze_volume_file(file, TEMP_FILES['HEADROOM_LOG'], log_file)
            elif subdirs:
                logger.info(f"Analyzing subdirectories in {path}: {', '.join(str(s) for s in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    for file in subdir_files:
                        analyze_volume_file(file, TEMP_FILES['HEADROOM_LOG'], log_file)
            else:
                logger.error(f"No .dsf files found in {path} or its subdirectories")
                success = False

            if os.path.exists(TEMP_FILES['HEADROOM_LOG']) and os.stat(TEMP_FILES['HEADROOM_LOG']).st_size > 0:
                headroom_log = []
                with open(TEMP_FILES['HEADROOM_LOG']) as f:
                    for line in f:
                        headroom, _ = line.strip().split(':', 1)
                        headroom_log.append(float(headroom))
                min_h, max_h, avg_h = min(headroom_log), max(headroom_log), sum(headroom_log) / len(headroom_log)
                logger.info(f"Headroom Statistics (across {len(headroom_log)} files):")
                logger.info(f"  Min: {min_h:.1f} dB, Max: {max_h:.1f} dB, Avg: {avg_h:.1f} dB")
                if log_file:
                    with open(log_file, 'a') as f:
                        f.write(f"Headroom Statistics (across {len(headroom_log)} files):\n")
                        f.write(f"  Min: {min_h:.1f} dB, Max: {max_h:.1f} dB, Avg: {avg_h:.1f} dB\n")

        elif args.volume == 'auto':
            if files:
                logger.info(f"Processing directory: {path}")
                volume = calculate_auto_volume(files, "", log_file)
                if volume:
                    success &= process_files_in_parallel(files, os.path.join(path, OUTPUT_DIRS[args.format]), volume, log_file)
            if subdirs:  # Process subdirectories sequentially to respect headroom per subdir
                logger.info(f"Processing subdirectories in {path}: {', '.join(str(s) for s in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    volume = calculate_auto_volume(subdir_files, str(subdir), log_file)
                    if volume:
                        success &= process_files_in_parallel(subdir_files, os.path.join(subdir, OUTPUT_DIRS[args.format]), volume, log_file)
            if not files and not subdirs:
                logger.error(f"No .dsf files found in {path} or its subdirectories")
                success = False

        else:
            if files:
                logger.info(f"Processing directory: {path}")
                success &= process_files_in_parallel(files, os.path.join(path, OUTPUT_DIRS[args.format]), args.volume, log_file)
            if subdirs:  # Process subdirectories sequentially
                logger.info(f"Processing subdirectories in {path}: {', '.join(str(s) for s in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    success &= process_files_in_parallel(subdir_files, os.path.join(subdir, OUTPUT_DIRS[args.format]), args.volume, log_file)
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
    if log_file:
        with open(log_file, 'a') as f:
            f.write(f"{'Process completed successfully!' if success else 'Process completed with errors!'}\n")
            f.write(f"Elapsed time: {elapsed_time} seconds\n")

    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            os.remove(temp_file)
    
    # Restaurar o estado original do terminal ao final
    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)

if __name__ == "__main__":
    main()