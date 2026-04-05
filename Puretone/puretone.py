#!/usr/bin/env python3
import subprocess
import os
import argparse
import logging
import time
import re
import sys
import signal
import stat
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Optional
import shutil
import termios
import tty

# Save terminal state at startup
ORIGINAL_TERMINAL_STATE = None
if sys.stdin.isatty():
    ORIGINAL_TERMINAL_STATE = termios.tcgetattr(sys.stdin)

# Logging configuration
START_TIME = time.time()
logging.basicConfig(
    format='[%(relativeCreated)d] [%(levelname)s] %(message)s',
    level=logging.INFO
)
logger = logging.getLogger('puretone')

# Configuration class
class PureToneConfig:
    def __init__(self):
        self.ACODEC = 'pcm_s24le'
        self.AR = '176400'
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
        # SACD
        self.KEEP_DSF = False
        self.EXTRACT_ONLY = False

CONFIG = PureToneConfig()

# Output directories by format
OUTPUT_DIRS = {'wav': 'wv', 'wavpack': 'wvpk', 'flac': 'flac', 'dsf': 'dsf'}

# File extensions by format
FORMAT_EXTENSIONS = {'wav': 'wav', 'wavpack': 'wv', 'flac': 'flac'}

# Temporary files
TEMP_FILES = {
    'PEAK_LOG': f"/tmp/puretone_{os.getpid()}_peaks.log",
    'VOLUME_LOG': f"/tmp/puretone_{os.getpid()}_volume.log",
}

# Temporary directory for sacd_extract (cfg + embedded binary)
SACD_TEMP_DIR = f"/tmp/puretone_{os.getpid()}_sacd"

def run_command(cmd: List[str], capture_output: bool = True, cwd: Optional[str] = None) -> Tuple[str, str, int]:
    logger.debug(f"Executing command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture_output, text=True, cwd=cwd)
    stdout = result.stdout or ''
    stderr = result.stderr or ''
    if result.returncode != 0:
        logger.error(f"Command failed with return code {result.returncode}: {stderr}")
    return stdout, stderr, result.returncode

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

        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG.ACODEC, '-ar', CONFIG.AR,
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
                f.write(f"File {entry['file']}: DSD->WAV y = {entry['y']:.1f} dB, WAV Max Volume = {entry['wav_max_volume']:.1f} dB\n")
            if highest_volume > CONFIG.HEADROOM_LIMIT:
                f.write(f"Applied uniform adjustment of {adjustment:.1f} dB to keep highest volume at {CONFIG.HEADROOM_LIMIT} dB\n")
            else:
                f.write(f"Used individual y values as no volumes exceed {CONFIG.HEADROOM_LIMIT} dB\n")
            if CONFIG.ADDITION != '0dB':
                f.write(f"Applied additional volume adjustment: {CONFIG.ADDITION}\n")

    return final_volumes, volume_adjustments

def process_file(input_file: str, output_dir: str, volume: str = None, log_file: Optional[str] = None) -> bool:
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

    if volume:
        af = f"{af_base},volume={volume}"
        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG.ACODEC, '-ar', CONFIG.AR, '-af', af, intermediate_wav, '-y']
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(intermediate_wav):
            logger.error(f"Error creating intermediate WAV for {input_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
            return False
    else:
        af_first = f"{af_base},loudnorm=I={CONFIG.LOUDNORM_I}:TP={CONFIG.LOUDNORM_TP}:LRA={CONFIG.LOUDNORM_LRA}:print_format=summary"
        _, stderr, rc = run_command(['ffmpeg', '-i', input_file, '-acodec', CONFIG.ACODEC, '-ar', CONFIG.AR, '-af', af_first, '-f', 'null', '-'])
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
        cmd = ['ffmpeg', '-i', input_file, '-acodec', CONFIG.ACODEC, '-ar', CONFIG.AR, '-af', af_second, intermediate_wav, '-y']
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
    with open(TEMP_FILES['PEAK_LOG']) as f:
        for line in f:
            if line.startswith(f"{output_file}:Output:"):
                _, _, output_max_volume, output_peak_level = line.strip().split(':', 3)
                break
    file_size_kb = os.path.getsize(output_file) / 1024
    logger.info(f"Converted {input_file} -> {output_file} (Size: {file_size_kb:.1f} KB)")
    logger.debug(f"Output - Max Volume: {output_max_volume}, Peak Level: {output_peak_level}")

    if CONFIG.OUTPUT_FORMAT == 'flac':
        if volume:
            applied_volume = volume
        else:
            applied_volume = f"loudnorm=I={CONFIG.LOUDNORM_I}:TP={CONFIG.LOUDNORM_TP}:LRA={CONFIG.LOUDNORM_LRA}"
        comment_content = (
            f"DSF > WAV > FLAC, Codec: {CONFIG.ACODEC}, "
            f"Resampler: {CONFIG.RESAMPLER} with precision {CONFIG.PRECISION} and cheby, "
            f"Applied Volume: {applied_volume}, Compression Level: {CONFIG.FLAC_COMPRESSION}"
        )
        metaflac_cmd = ['metaflac', '--set-tag', f"COMMENT={comment_content}", output_file]
        _, stderr, rc = run_command(metaflac_cmd)
        if rc != 0:
            logger.error(f"Failed to apply COMMENT to {output_file}: {stderr}")
            return False
        logger.debug(f"Applied COMMENT to {output_file}: {comment_content}")
        verify_cmd = ['metaflac', '--list', '--block-type=VORBIS_COMMENT', output_file]
        stdout, stderr, rc = run_command(verify_cmd)
        if rc == 0 and "COMMENT=" in stdout:
            logger.debug(f"Verified COMMENT in {output_file}: Present")
        else:
            logger.error(f"COMMENT not found in {output_file} after application:\n{stdout}\n{stderr}")
            return False

    if CONFIG.ENABLE_VISUALIZATION:
        vis_file = normalize_path(os.path.join(spectrogram_dir, f"{base_name}.png"))
        if CONFIG.VISUALIZATION_TYPE == 'waveform':
            cmd = ['ffmpeg', '-i', output_file, '-filter_complex', f"showwavespic=s={CONFIG.VISUALIZATION_SIZE}", vis_file, '-y']
        else:
            cmd = ['ffmpeg', '-i', output_file, '-lavfi', f"showspectrumpic=s={CONFIG.VISUALIZATION_SIZE}:mode={CONFIG.SPECTROGRAM_MODE}", vis_file, '-y']
        _, stderr, rc = run_command(cmd)
        if rc != 0:
            logger.error(f"Error generating {CONFIG.VISUALIZATION_TYPE} for {output_file}. Check {local_log}")
            with open(local_log, 'a') as f:
                f.write(stderr + '\n')
        else:
            logger.info(f"Generated {CONFIG.VISUALIZATION_TYPE}: {vis_file}")

    return True

# ---------------------------------------------------------------------------
# SACD / ISO extraction
# ---------------------------------------------------------------------------

def locate_sacd_extract() -> Optional[str]:
    """Locate the sacd_extract binary: first checks the embedded Nuitka path, then the system PATH."""
    # Embedded binary via Nuitka (--include-data-files=bin/sacd_extract=bin/sacd_extract)
    embedded = os.path.join(os.path.dirname(__file__), 'bin', 'sacd_extract')
    if os.path.isfile(embedded):
        # Ensure execute permission (Nuitka does not preserve execute bits)
        current_mode = os.stat(embedded).st_mode
        if not (current_mode & stat.S_IXUSR):
            os.chmod(embedded, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            logger.debug(f"Applied +x to embedded sacd_extract: {embedded}")
        return embedded

    # Fallback: system PATH
    system_bin = shutil.which('sacd_extract')
    if system_bin:
        logger.debug(f"Using system sacd_extract: {system_bin}")
        return system_bin

    return None

def prepare_sacd_cfg() -> str:
    """Create the temporary directory and sacd_extract.cfg required for execution."""
    os.makedirs(SACD_TEMP_DIR, exist_ok=True)
    cfg_path = os.path.join(SACD_TEMP_DIR, 'sacd_extract.cfg')
    with open(cfg_path, 'w') as f:
        f.write('id3tag=5\n')
    logger.debug(f"Created sacd_extract.cfg at {cfg_path}")
    return SACD_TEMP_DIR

def extract_iso(iso_path: str, sacd_bin: str, output_dir: Optional[str] = None) -> Optional[str]:
    """
    Extract DSFs from a SACD ISO to <base_dir>/<iso_stem>/dsf/.
    The iso_stem (filename without extension) scopes each album to its own
    directory, mirroring the way the original DSF flow derives output dirs
    from the input path — preventing collisions between different albums.
    If output_dir is not provided, uses the ISO's own directory as base.
    Returns the dsf/ directory path on success, None on failure.
    """
    iso_path = os.path.abspath(iso_path)
    iso_stem = Path(iso_path).stem
    base_dir = os.path.abspath(output_dir) if output_dir else os.path.dirname(iso_path)

    # <output_dir>/<iso_stem>/dsf/  — isolated per album
    album_dir = normalize_path(os.path.join(base_dir, iso_stem))
    dsf_dir = normalize_path(os.path.join(album_dir, OUTPUT_DIRS['dsf']))

    os.makedirs(dsf_dir, exist_ok=True)
    logger.info(f"Extracting ISO: {iso_path} -> {dsf_dir}")

    cfg_cwd = prepare_sacd_cfg()

    cmd = [
        sacd_bin,
        '--2ch-tracks',
        '--output-dsf',
        '-i', iso_path,
        '--output-dir-conc', dsf_dir,
    ]

    # In debug mode, let sacd_extract write directly to the terminal
    capture = not logger.isEnabledFor(logging.DEBUG)
    stdout, stderr, rc = run_command(cmd, capture_output=capture, cwd=cfg_cwd)

    if rc != 0:
        logger.error(f"sacd_extract failed (rc={rc}):\n{stderr}")
        return None

    # sacd_extract may create a subdirectory named after the album inside dsf_dir
    # e.g.: dsf/Stones/*.dsf — find the actual DSF location
    dsf_files = list(Path(dsf_dir).rglob('*.dsf'))
    if not dsf_files:
        logger.error(f"sacd_extract completed but no .dsf files found in {dsf_dir}")
        return None

    # Return the actual directory where DSFs reside
    actual_dsf_dir = str(dsf_files[0].parent)
    logger.info(f"Extracted {len(dsf_files)} DSF file(s) to {actual_dsf_dir}")
    return actual_dsf_dir

def cleanup_dsf_dir(dsf_dir: str):
    """
    Remove the dsf/ subtree after conversion, unless --keep-dsf is active.
    dsf_dir may be the internal album subdir (dsf/<album>/) — in that case
    we remove the parent dsf/ directory to clean up completely.
    """
    if CONFIG.KEEP_DSF:
        logger.info(f"Keeping DSF directory: {dsf_dir}")
        return
    # If dsf_dir is <album_dir>/dsf/<internal>/, remove <album_dir>/dsf/ entirely
    parent = os.path.dirname(dsf_dir)
    target = parent if os.path.basename(parent) == OUTPUT_DIRS['dsf'] else dsf_dir
    try:
        shutil.rmtree(target)
        logger.info(f"Removed DSF directory: {target}")
    except Exception as e:
        logger.error(f"Failed to remove DSF directory {target}: {e}")

# ---------------------------------------------------------------------------

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
    # Clean up sacd_extract temporary directory
    if os.path.exists(SACD_TEMP_DIR):
        try:
            shutil.rmtree(SACD_TEMP_DIR)
            logger.debug(f"Removed SACD temp dir: {SACD_TEMP_DIR}")
        except Exception as e:
            logger.error(f"Failed to remove SACD temp dir {SACD_TEMP_DIR}: {e}")
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
    logger.info(f"Starting parallel processing with {CONFIG.PARALLEL_JOBS} workers for {len(files)} files")
    with ThreadPoolExecutor(max_workers=CONFIG.PARALLEL_JOBS) as executor:
        results = []
        for file, volume in volume_map:
            results.append(executor.submit(process_file, file, output_dir, volume, log_file))
        outcomes = [future.result() for future in results]
    success = all(outcomes)
    logger.info(f"Completed parallel processing for {len(files)} files. Success: {success}")
    return success

def print_volume_summary(volume_data: List[dict], volume_maps: List[List[Tuple[str, str]]], log_file: Optional[str] = None):
    logger.info("\n=== Volume Adjustment Summary ===")
    col_widths = [60, 15, 20, 20]
    logger.info(f"{'File':<60} {'y (dB) ffmpeg':^15} {'WAV Max Volume (dB)':^20} {'Applied Volume (dB)':^20}")
    logger.info("-" * sum(col_widths))

    volume_dict = {}
    for v_map in volume_maps:
        volume_dict.update({file: vol for file, vol in v_map})

    for entry in volume_data:
        applied_volume = volume_dict.get(entry['file'], "N/A")
        logger.info(f"{entry['file'][:58]:<60} {entry['y']:^15.1f} {entry['wav_max_volume']:^20.1f} {applied_volume:^20}")
    logger.info("-" * sum(col_widths))

    if CONFIG.ADDITION != '0dB':
        logger.info(f"Applied additional volume adjustment: {CONFIG.ADDITION}")

    if log_file:
        with open(log_file, 'a') as f:
            f.write("\n=== Volume Adjustment Summary ===\n")
            f.write(f"{'File':<60} {'y (dB) ffmpeg':^15} {'WAV Max Volume (dB)':^20} {'Applied Volume (dB)':^20}\n")
            f.write("-" * sum(col_widths) + "\n")
            for entry in volume_data:
                applied_volume = volume_dict.get(entry['file'], "N/A")
                f.write(f"{entry['file'][:58]:<60} {entry['y']:^15.1f} {entry['wav_max_volume']:^20.1f} {applied_volume:^20}\n")
            f.write("-" * sum(col_widths) + "\n")
            if CONFIG.ADDITION != '0dB':
                f.write(f"Applied additional volume adjustment: {CONFIG.ADDITION}\n")

def process_dsf_directory(dsf_dir: str, args, log_file: Optional[str]) -> bool:
    """Process a directory of DSF files — used by both the ISO flow and the direct DSF flow."""
    files = [str(f) for f in Path(dsf_dir).glob('*.dsf')]
    if not files:
        logger.error(f"No .dsf files found in {dsf_dir}")
        return False

    # Walk up from the actual DSF directory to find the album container:
    # <output_dir>/<iso_stem>/dsf/<album_internal>/  -> actual_dsf_dir  (4 levels)
    # <output_dir>/<iso_stem>/dsf/                   -> dsf_parent
    # <output_dir>/<iso_stem>/                       -> album_dir  (sibling of dsf/)
    # Converted files go to <album_dir>/<format>/
    dsf_parent = os.path.dirname(dsf_dir)
    if os.path.basename(dsf_parent) == OUTPUT_DIRS['dsf']:
        # dsf_dir is the album subdirectory inside dsf/ — go up two levels
        album_dir = os.path.dirname(dsf_parent)
    else:
        # dsf_dir is dsf/ itself (no internal album subdir) — go up one level
        album_dir = dsf_parent
    output_dir = os.path.join(album_dir, OUTPUT_DIRS[args.format])
    all_volume_data = []
    all_volume_maps = []
    success = True

    if args.volume == 'auto':
        volume_map, volume_data = calculate_volume_adjustment(files, dsf_dir, log_file)
        all_volume_data.extend(volume_data)
        all_volume_maps.append(volume_map)
        success = process_files_in_parallel(files, output_dir, volume_map, log_file)
    else:
        volume_map = [(f, args.volume) for f in files]
        success = process_files_in_parallel(files, output_dir, volume_map, log_file)

    if all_volume_data and args.volume == 'auto':
        print_volume_summary(all_volume_data, all_volume_maps, log_file)

    return success

def main():
    description = """
PureTone - DSD to High-Quality Audio Converter

Description:
------------
PureTone is a Python script that converts DSD files (.dsf) to high-quality audio formats
(WAV, WavPack, FLAC), with advanced audio processing options including volume normalization,
resampling, and visualization (spectrograms or waveforms). Supports direct extraction from
SACD ISOs via sacd_extract (embedded or system-installed). Supports parallel processing
and detailed logging.

Detailed Workflow:
------------------
1. Dependency Check: Verifies that ffmpeg and ffprobe are installed.
2. Path Analysis: Accepts a .dsf file, .iso file, or directory as input.
   - .iso: extracts DSFs via sacd_extract, then processes normally.
   - .dsf: processes the file directly.
   - directory: recursively processes all .dsf files found.
3. ISO Extraction (if input is .iso):
   - Locates sacd_extract (embedded or in PATH).
   - Generates sacd_extract.cfg in a temporary directory.
   - Extracts DSFs to <output_dir>/dsf/ using --2ch-tracks --output-dsf.
   - If --extract-only, stops after extraction.
4. Volume Analysis (if --volume auto): same as the standard flow.
5. File Processing: same as the standard flow.
6. Cleanup: removes dsf/ unless --keep-dsf is active.

Directory Structure (ISO input):
---------------------------------
<output_dir>/
└── dsf/          # Extracted DSFs (removed at the end unless --keep-dsf)
└── wv/           # or wvpk/ or flac/, depending on --format
    └── *.wav/wv/flac

Defaults:
---------
- Output format (--format): wav
- Audio codec (--codec): pcm_s24le
- Sample rate (--sample-rate): 176400 Hz
- Integrated loudness target (--loudnorm-I): -14 LUFS
- True peak limit (--loudnorm-TP): -1 dBTP
- Loudness range (--loudnorm-LRA): 20 LU
- Volume adjustment (--volume): None (uses loudnorm by default)
- Optional volume increase (--volume-increase): 1dB
- Additional adjustment (--addition): 0dB
- Headroom limit (--headroom-limit): -0.5 dB
- Resampler (--resampler): soxr
- Resampler precision (--precision): 28
- Chebyshev mode (--cheby): 1
- Visualization (--spectrogram): Disabled
- Compression level (--compression-level): 0
- Skip existing (--skip-existing): False
- Parallel jobs (--parallel): 2
- Log file (--log): None
- Keep extracted DSFs (--keep-dsf): False
- Extract DSFs only (--extract-only): False
- Debug mode (--debug): False

Practical Examples:
-------------------
1. Convert a SACD ISO to FLAC with automatic volume adjustment:
   ./puretone --format flac --compression-level 12 --volume auto --volume-increase 2dB /path/to/album.iso

2. Extract DSFs from an ISO without converting:
   ./puretone --extract-only /path/to/album.iso

3. Convert ISO and keep the extracted DSFs:
   ./puretone --format flac --keep-dsf /path/to/album.iso

4. Convert all DSF files in a directory to WavPack:
   ./puretone --format wavpack --volume auto --parallel 4 /path/to/directory

5. Convert a single DSF file to WAV with loudness normalization:
   ./puretone /path/to/file.dsf
"""

    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False
    )

    parser.add_argument('-h', '--help', action='help', help="Show this help message and exit.")
    parser.add_argument('--format', choices=['wav', 'wavpack', 'flac'], default='wav', help="Output format: 'wav', 'wavpack' or 'flac'. Default: wav")
    parser.add_argument('--codec', help="Audio codec for WAV output (e.g. pcm_s32le). Default: pcm_s24le")
    parser.add_argument('--sample-rate', type=int, help="Sample rate in Hz (e.g. 88200). Default: 176400")
    parser.add_argument('--loudnorm-I', help="Integrated loudness target in LUFS. Default: -14")
    parser.add_argument('--loudnorm-TP', help="True peak limit in dBTP. Default: -1")
    parser.add_argument('--loudnorm-LRA', help="Loudness range in LU. Default: 20")
    parser.add_argument('--volume', help="Volume adjustment: fixed value (e.g. '2.5dB'), 'auto' or 'analysis'. Default: None")
    parser.add_argument('--volume-increase', default='1dB', help="Optional volume increase (e.g. '1dB') applied when --volume auto and all tracks have headroom. Default: 1dB")
    parser.add_argument('--addition', help="Additional volume adjustment (e.g. '1dB'), only with --volume auto. Negative values not allowed. Default: 0dB")
    parser.add_argument('--headroom-limit', type=float, help="Maximum allowed volume in dB. Default: -0.5")
    parser.add_argument('--resampler', help="Resampling engine (e.g. soxr). Default: soxr")
    parser.add_argument('--precision', type=int, help="Resampler precision (e.g. 20-28). Default: 28")
    parser.add_argument('--cheby', choices=['0', '1'], help="Enable Chebyshev mode for SoX resampler. Default: 1")
    parser.add_argument('--spectrogram', nargs='*', help="Enable visualization: '<width>x<height> [type [mode]]'. Default: disabled")
    parser.add_argument('--compression-level', type=int, help="Compression level: 0-6 for WavPack, 0-12 for FLAC. Default: 0")
    parser.add_argument('--skip-existing', action='store_true', help="Skip if the output file already exists. Default: False")
    parser.add_argument('--parallel', type=int, help="Number of parallel jobs. Default: 2")
    parser.add_argument('--log', help="File to save analysis results. Default: None")
    parser.add_argument('--debug', action='store_true', help="Enable debug logging. Default: False")
    # SACD arguments
    parser.add_argument('--keep-dsf', action='store_true', help="Keep extracted .dsf files after conversion. Default: False")
    parser.add_argument('--extract-only', action='store_true', help="Extract DSFs from the ISO without converting. Implies --keep-dsf. Default: False")
    parser.add_argument('--output-dir', help="Output directory for extracted DSFs and converted files (ISO input only). Default: same directory as the ISO")
    parser.add_argument('path', help="Path to a .dsf file, .iso file, or directory")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    CONFIG.OUTPUT_FORMAT = args.format
    if args.volume:
        if args.volume not in ('auto', 'analysis') and not validate_volume(args.volume):
            logger.error("Volume must be 'auto', 'analysis', or in the format 'XdB' (e.g. '3dB', '-2.5dB')")
            sys.exit(1)
        CONFIG.VOLUME = args.volume

    if args.volume_increase:
        if not validate_volume(args.volume_increase):
            logger.error("volume-increase must be in the format 'XdB' (e.g. '1dB', '3.5dB')")
            sys.exit(1)
        CONFIG.VOLUME_INCREASE = args.volume_increase

    if args.addition:
        if not validate_addition(args.addition):
            logger.error("Addition must be in the format 'XdB' (e.g. '1dB', '2.5dB') and cannot be negative")
            sys.exit(1)
        if args.volume != 'auto':
            logger.error("--addition can only be used with --volume auto")
            sys.exit(1)
        CONFIG.ADDITION = args.addition

    if args.codec: CONFIG.ACODEC = args.codec
    if args.sample_rate: CONFIG.AR = str(args.sample_rate)
    if args.loudnorm_I: CONFIG.LOUDNORM_I = args.loudnorm_I
    if args.loudnorm_TP: CONFIG.LOUDNORM_TP = args.loudnorm_TP
    if args.loudnorm_LRA: CONFIG.LOUDNORM_LRA = args.loudnorm_LRA
    if args.headroom_limit is not None: CONFIG.HEADROOM_LIMIT = args.headroom_limit
    if args.resampler: CONFIG.RESAMPLER = args.resampler
    if args.precision: CONFIG.PRECISION = str(args.precision)
    if args.cheby: CONFIG.CHEBY = args.cheby
    if args.spectrogram:
        CONFIG.ENABLE_VISUALIZATION = True
        if args.spectrogram and validate_resolution(args.spectrogram[0]):
            CONFIG.VISUALIZATION_SIZE = args.spectrogram[0]
            if len(args.spectrogram) > 1:
                CONFIG.VISUALIZATION_TYPE = args.spectrogram[1]
                if len(args.spectrogram) > 2 and CONFIG.VISUALIZATION_TYPE == 'spectrogram':
                    CONFIG.SPECTROGRAM_MODE = args.spectrogram[2]
    if args.compression_level:
        if CONFIG.OUTPUT_FORMAT == 'wavpack' and 0 <= args.compression_level <= 6:
            CONFIG.WAVPACK_COMPRESSION = str(args.compression_level)
        elif CONFIG.OUTPUT_FORMAT == 'flac' and 0 <= args.compression_level <= 12:
            CONFIG.FLAC_COMPRESSION = str(args.compression_level)
        else:
            logger.error(f"Invalid compression level for {CONFIG.OUTPUT_FORMAT}")
            sys.exit(1)
    if args.skip_existing: CONFIG.SKIP_EXISTING = True
    if args.parallel: CONFIG.PARALLEL_JOBS = max(1, args.parallel)
    CONFIG.KEEP_DSF = args.keep_dsf or args.extract_only
    CONFIG.EXTRACT_ONLY = args.extract_only
    log_file = args.log

    # Verify base dependencies
    required_commands = ['ffmpeg', 'ffprobe']
    if CONFIG.OUTPUT_FORMAT == 'flac':
        required_commands.append('metaflac')
    for cmd in required_commands:
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

    # ------------------------------------------------------------------
    # ISO SACD flow
    # ------------------------------------------------------------------
    if path.is_file() and path.suffix.lower() == '.iso':
        sacd_bin = locate_sacd_extract()
        if sacd_bin is None:
            logger.error("sacd_extract not found. Install it on the system or place the binary at bin/sacd_extract.")
            sys.exit(1)

        output_dir = os.path.abspath(args.output_dir) if args.output_dir else None
        dsf_dir = extract_iso(str(path), sacd_bin, output_dir)
        if dsf_dir is None:
            logger.error("ISO extraction failed. Aborting.")
            sys.exit(1)

        if CONFIG.EXTRACT_ONLY:
            logger.info(f"--extract-only active. DSFs available at: {dsf_dir}")
        else:
            success = process_dsf_directory(dsf_dir, args, log_file)
            cleanup_dsf_dir(dsf_dir)

    # ------------------------------------------------------------------
    # Single DSF file flow
    # ------------------------------------------------------------------
    elif path.is_file() and path.suffix == '.dsf':
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

    # ------------------------------------------------------------------
    # Directory flow
    # ------------------------------------------------------------------
    elif path.is_dir():
        abs_path = path.resolve()
        files = [str(f) for f in abs_path.glob('*.dsf')]
        subdirs = [d for d in abs_path.iterdir() if d.is_dir() and any(f.suffix == '.dsf' for f in d.glob('*.dsf'))]

        if args.volume == 'auto':
            if files:
                logger.info(f"Processing directory: {abs_path}")
                volume_map, volume_data = calculate_volume_adjustment(files, "", log_file)
                all_volume_data.extend(volume_data)
                all_volume_maps.append(volume_map)
                success &= process_files_in_parallel(files, str(abs_path / OUTPUT_DIRS[args.format]), volume_map, log_file)
            if subdirs:
                logger.info(f"Processing subdirectories in {abs_path}: {', '.join(d.name for d in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    volume_map, volume_data = calculate_volume_adjustment(subdir_files, str(subdir), log_file)
                    all_volume_data.extend(volume_data)
                    all_volume_maps.append(volume_map)
                    success &= process_files_in_parallel(subdir_files, str(subdir / OUTPUT_DIRS[args.format]), volume_map, log_file)
            if not files and not subdirs:
                logger.error(f"No .dsf files found in {abs_path} or its subdirectories")
                success = False
        else:
            if files:
                logger.info(f"Processing directory: {abs_path}")
                success &= process_files_in_parallel(files, str(abs_path / OUTPUT_DIRS[args.format]), [(f, args.volume) for f in files], log_file)
            if subdirs:
                logger.info(f"Processing subdirectories in {abs_path}: {', '.join(d.name for d in subdirs)}")
                for subdir in subdirs:
                    subdir_files = [str(f) for f in subdir.glob('*.dsf')]
                    success &= process_files_in_parallel(subdir_files, str(subdir / OUTPUT_DIRS[args.format]), [(f, args.volume) for f in subdir_files], log_file)
            if not files and not subdirs:
                logger.error(f"No .dsf files found in {abs_path} or its subdirectories")
                success = False
    else:
        logger.error(f"Invalid path or unsupported format: {args.path}")
        sys.exit(1)

    elapsed_time = int(time.time() - start_time)
    if success:
        logger.info("Process completed successfully!")
    else:
        logger.error("Process completed with errors!")
    logger.info(f"Elapsed time: {elapsed_time} seconds")

    if all_volume_data and args.volume == 'auto':
        print_volume_summary(all_volume_data, all_volume_maps, log_file)

    # Clean up temporary files
    for temp_file in TEMP_FILES.values():
        if os.path.exists(temp_file):
            os.remove(temp_file)
    if os.path.exists(SACD_TEMP_DIR):
        shutil.rmtree(SACD_TEMP_DIR, ignore_errors=True)

    if ORIGINAL_TERMINAL_STATE is not None and sys.stdin.isatty():
        sys.stdout.flush()
        sys.stderr.flush()
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, ORIGINAL_TERMINAL_STATE)

if __name__ == "__main__":
    main()