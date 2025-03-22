import os
import re
import logging
from pathlib import Path
from typing import List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor
from utils import run_command, normalize_path, add_db

logger = logging.getLogger('puretone')

def analyze_peaks_and_volume(file: str, peak_log: str, log_type: str) -> Tuple[Optional[float], Optional[str]]:
    """Analisa picos e volume máximo de um arquivo de áudio."""
    cmd = [
        'ffmpeg', '-i', file,
        '-af', 'volumedetect,astats=metadata=1,ametadata=print:key=lavfi.astats.Overall.Peak_level',
        '-f', 'null', '-'
    ]
    _, stderr, rc = run_command(cmd)
    if rc != 0:
        logger.error(f"Failed to analyze peaks and volume for {file}: {stderr}")
        return None, None

    max_volume = re.search(r'max_volume: ([-0-9.]* dB)', stderr)
    max_volume_db = float(max_volume.group(1).replace(' dB', '')) if max_volume else None
    if max_volume_db is None:
        logger.warning(f"Max volume not detected for {file}")

    peak_match = re.search(r'Peak_level=([-0-9.]+)', stderr)
    peak_level = f"{peak_match.group(1)} dBFS" if peak_match else 'Not detected'

    try:
        with open(peak_log, 'a') as f:
            f.write(f"{file}:{log_type}:{max_volume_db if max_volume_db is not None else 'Not detected'}:{peak_level}\n")
    except IOError as e:
        logger.error(f"Failed to write to peak log {peak_log}: {e}")
        return None, None

    return max_volume_db, peak_level

def calculate_volume_adjustment(files: List[str], subdir: str, log_file: Optional[str], config) -> Tuple[List[Tuple[str, str]], List[dict]]:
    """Calcula ajustes de volume para uma lista de arquivos."""
    temp_files = []
    volume_adjustments = []

    for temp_file in [config.TEMP_FILES['PEAK_LOG'], config.TEMP_FILES['VOLUME_LOG']]:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError as e:
                logger.error(f"Failed to remove temp file {temp_file}: {e}")

    for input_file in files:
        base_name = Path(input_file).stem
        temp_wav = f"/tmp/puretone_{os.getpid()}_{base_name}_temp.wav"
        temp_files.append(temp_wav)

        cmd = [
            'ffmpeg', '-i', input_file,
            '-acodec', config['ACODEC'], '-ar', config['AR'],
            '-map_metadata', config['MAP_METADATA'],
            '-af', f"aresample=resampler={config['RESAMPLER']}:precision={config['PRECISION']}:cheby={config['CHEBY']}",
            temp_wav, '-y'
        ]
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(temp_wav):
            logger.error(f"Failed to create temporary WAV for {input_file}: {stderr}")
            continue

        dsd_max_volume, _ = analyze_peaks_and_volume(input_file, config.TEMP_FILES['PEAK_LOG'], "DSD")
        wav_max_volume, _ = analyze_peaks_and_volume(temp_wav, config.TEMP_FILES['PEAK_LOG'], "WAV")

        if dsd_max_volume is None or wav_max_volume is None:
            logger.warning(f"Skipping volume calculation for {input_file}: peak data unavailable")
            continue

        y = -(wav_max_volume - dsd_max_volume)
        logger.info(f"File {input_file}: DSD Max Volume = {dsd_max_volume:.1f} dB, WAV Max Volume = {wav_max_volume:.1f} dB, y = {y:.1f} dB")

        try:
            with open(config.TEMP_FILES['VOLUME_LOG'], 'a') as f:
                f.write(f"{input_file}:{y:.1f}:{wav_max_volume:.1f}\n")
        except IOError as e:
            logger.error(f"Failed to write to volume log {config.TEMP_FILES['VOLUME_LOG']}: {e}")

        volume_adjustments.append({'file': input_file, 'y': y, 'wav_max_volume': wav_max_volume})

    for temp_wav in temp_files:
        if os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except OSError as e:
                logger.error(f"Failed to remove temp file {temp_wav}: {e}")

    if not volume_adjustments:
        logger.error(f"No valid volume data calculated for files in {subdir or 'current directory'}")
        return [], []

    final_volumes = []
    max_volumes = [entry['wav_max_volume'] + entry['y'] for entry in volume_adjustments]
    highest_volume = max(max_volumes)

    if highest_volume > config['HEADROOM_LIMIT']:
        adjustment = config['HEADROOM_LIMIT'] - highest_volume
        logger.info(f"Highest adjusted volume ({highest_volume:.1f} dB) exceeds limit ({config['HEADROOM_LIMIT']} dB). Applying uniform adjustment of {adjustment:.1f} dB")
        for entry in volume_adjustments:
            base_volume = f"{(entry['y'] + adjustment):.1f}dB"
            final_volume = add_db(base_volume, config['ADDITION'])
            final_volumes.append((entry['file'], final_volume))
    else:
        logger.info(f"No adjusted volumes exceed {config['HEADROOM_LIMIT']} dB. Using individual y values as volume adjustments")
        for entry in volume_adjustments:
            base_volume = f"{entry['y']:.1f}dB"
            final_volume = add_db(base_volume, config['ADDITION'])
            final_volumes.append((entry['file'], final_volume))

    if log_file:
        try:
            with open(log_file, 'a') as f:
                for entry in volume_adjustments:
                    f.write(f"File {entry['file']}: DSD->WAV y = {entry['y']:.1f} dB, WAV Max Volume = {entry['wav_max_volume']:.1f} dB\n")
                if highest_volume > config['HEADROOM_LIMIT']:
                    f.write(f"Applied uniform adjustment of {adjustment:.1f} dB to keep highest volume at {config['HEADROOM_LIMIT']} dB\n")
                else:
                    f.write(f"Used individual y values as no volumes exceed {config['HEADROOM_LIMIT']} dB\n")
                if config['ADDITION'] != '0dB':
                    f.write(f"Applied additional volume adjustment: {config['ADDITION']}\n")
        except IOError as e:
            logger.error(f"Failed to write volume adjustment to log file {log_file}: {e}")

    return final_volumes, volume_adjustments

def process_file(input_file: str, output_dir: str, volume: str, log_file: Optional[str], config) -> bool:
    """Processa um único arquivo de áudio."""
    logger.debug(f"Processing file: {input_file}")
    base_name = Path(input_file).stem
    intermediate_wav = normalize_path(os.path.join(output_dir, f"{base_name}_intermediate.wav"))
    output_file = normalize_path(os.path.join(output_dir, f"{base_name}.{config.format_extensions[config['OUTPUT_FORMAT']]}"))
    local_log = normalize_path(os.path.join(output_dir, 'log.txt'))

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create output directory {output_dir}: {e}")
        return False

    if os.path.exists(output_file):
        if config['SKIP_EXISTING']:
            logger.info(f"Skipping {input_file}: {output_file} already exists (--skip-existing enabled)")
            return True
        elif config['OVERWRITE']:
            logger.info(f"Overwriting {output_file} due to OVERWRITE=True")

    af_base = f"aresample=resampler={config['RESAMPLER']}:precision={config['PRECISION']}:cheby={config['CHEBY']}"
    analyze_peaks_and_volume(input_file, config.TEMP_FILES['PEAK_LOG'], "Input")

    if volume:
        af = f"{af_base},volume={volume}"
        cmd = [
            'ffmpeg', '-i', input_file,
            '-acodec', config['ACODEC'], '-ar', config['AR'],
            '-map_metadata', config['MAP_METADATA'], '-af', af,
            intermediate_wav, '-y'
        ]
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(intermediate_wav):
            logger.error(f"Error creating intermediate WAV for {input_file}. Check {local_log}")
            try:
                with open(local_log, 'a') as f:
                    f.write(stderr + '\n')
            except IOError as e:
                logger.error(f"Failed to write to local log {local_log}: {e}")
            return False
    else:
        af_first = f"{af_base},loudnorm=I={config['LOUDNORM_I']}:TP={config['LOUDNORM_TP']}:LRA={config['LOUDNORM_LRA']}:print_format=summary"
        _, stderr, rc = run_command([
            'ffmpeg', '-i', input_file,
            '-acodec', config['ACODEC'], '-ar', config['AR'],
            '-map_metadata', config['MAP_METADATA'], '-af', af_first,
            '-f', 'null', '-'
        ])
        if rc != 0:
            logger.error(f"Error analyzing loudness for {input_file}. Check {local_log}")
            try:
                with open(local_log, 'a') as f:
                    f.write(stderr + '\n')
            except IOError as e:
                logger.error(f"Failed to write to local log {local_log}: {e}")
            return False

        metrics = {
            'measured_I': re.search(r'Input Integrated: *([-0-9.]*)', stderr),
            'measured_LRA': re.search(r'Input LRA: *([0-9.]*)', stderr),
            'measured_TP': re.search(r'Input True Peak: *([-0-9.]*)', stderr),
            'measured_thresh': re.search(r'Input Threshold: *([-0-9.]*)', stderr)
        }
        if not all(m.group(1) for m in metrics.values() if m):
            logger.error(f"Failed to extract loudness metrics for {input_file}. Check {local_log}")
            try:
                with open(local_log, 'a') as f:
                    f.write(stderr + '\n')
            except IOError as e:
                logger.error(f"Failed to write to local log {local_log}: {e}")
            return False

        af_second = (
            f"{af_base},loudnorm=I={config['LOUDNORM_I']}:TP={config['LOUDNORM_TP']}:LRA={config['LOUDNORM_LRA']}:" +
            f"measured_I={metrics['measured_I'].group(1)}:measured_LRA={metrics['measured_LRA'].group(1)}:" +
            f"measured_TP={metrics['measured_TP'].group(1)}:measured_thresh={metrics['measured_thresh'].group(1)}"
        )
        cmd = [
            'ffmpeg', '-i', input_file,
            '-acodec', config['ACODEC'], '-ar', config['AR'],
            '-map_metadata', config['MAP_METADATA'], '-af', af_second,
            intermediate_wav, '-y'
        ]
        _, stderr, rc = run_command(cmd)
        if rc != 0 or not os.path.exists(intermediate_wav):
            logger.error(f"Error creating intermediate WAV for {input_file}. Check {local_log}")
            try:
                with open(local_log, 'a') as f:
                    f.write(stderr + '\n')
            except IOError as e:
                logger.error(f"Failed to write to local log {local_log}: {e}")
            return False

    if config['OUTPUT_FORMAT'] == 'wav':
        try:
            os.rename(intermediate_wav, output_file)
        except OSError as e:
            logger.error(f"Failed to rename {intermediate_wav} to {output_file}: {e}")
            return False
    else:
        final_cmd = ['ffmpeg', '-i', intermediate_wav, '-c:a', config['OUTPUT_FORMAT']]
        if config['OUTPUT_FORMAT'] == 'wavpack':
            final_cmd.extend(['-compression_level', config['WAVPACK_COMPRESSION']])
        elif config['OUTPUT_FORMAT'] == 'flac':
            final_cmd.extend(['-compression_level', config['FLAC_COMPRESSION']])
        final_cmd.extend([output_file, '-y'])
        try:
            _, stderr, rc = run_command(final_cmd)
            if rc != 0:
                logger.error(f"Error converting {input_file} to {config['OUTPUT_FORMAT']}. Check {local_log}")
                try:
                    with open(local_log, 'a') as f:
                        f.write(stderr + '\n')
                except IOError as e:
                    logger.error(f"Failed to write to local log {local_log}: {e}")
                return False
        finally:
            if os.path.exists(intermediate_wav):
                try:
                    os.remove(intermediate_wav)
                except OSError as e:
                    logger.error(f"Failed to remove intermediate file {intermediate_wav}: {e}")

    if not os.path.getsize(output_file):
        logger.error(f"Output file {output_file} is empty")
        return False

    max_volume_db, peak_level = analyze_peaks_and_volume(output_file, config.TEMP_FILES['PEAK_LOG'], "Output")
    file_size_kb = os.path.getsize(output_file) / 1024
    logger.info(f"Converted {input_file} -> {output_file} (Size: {file_size_kb:.1f} KB)")
    logger.debug(f"Output - Max Volume: {max_volume_db if max_volume_db is not None else 'N/A'}, Peak Level: {peak_level}")

    return True

def process_files_in_parallel(files: List[str], output_dir: str, volume_map: List[Tuple[str, str]], log_file: Optional[str], config) -> bool:
    """Processa arquivos em paralelo usando ProcessPoolExecutor."""
    logger.info(f"Starting parallel processing with {config['PARALLEL_JOBS']} workers for {len(files)} files")
    with ProcessPoolExecutor(max_workers=config['PARALLEL_JOBS']) as executor:
        results = []
        for file, volume in volume_map:
            results.append(executor.submit(process_file, file, output_dir, volume, log_file, config))
        outcomes = [future.result() for future in results]
    logger.info(f"Completed parallel processing for {len(files)} files")
    return all(outcomes)