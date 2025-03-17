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

# ... (demais definições de funções como run_command, normalize_path, etc., permanecem inalteradas) ...

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
               "    ./puretone.py --skip-existing --log output.log /path/to/directory",
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

    # ... (restante do código do main() permanece inalterado) ...

if __name__ == "__main__":
    main()