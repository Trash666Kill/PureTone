import os
import logging
from utils import run_command, normalize_path

logger = logging.getLogger('puretone')

def generate_visualization(input_file: str, output_dir: str, config) -> bool:
    """Gera visualizações (espectrograma ou forma de onda) para um arquivo de áudio."""
    if not config['ENABLE_VISUALIZATION']:
        return True

    spectrogram_dir = normalize_path(os.path.join(output_dir, 'spectrogram'))
    try:
        os.makedirs(spectrogram_dir, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create spectrogram directory {spectrogram_dir}: {e}")
        return False

    base_name = os.path.splitext(os.path.basename(input_file))[0]
    vis_file = normalize_path(os.path.join(spectrogram_dir, f"{base_name}.png"))

    if config['VISUALIZATION_TYPE'] == 'waveform':
        cmd = ['ffmpeg', '-i', input_file, '-filter_complex', f"showwavespic=s={config['VISUALIZATION_SIZE']}", vis_file, '-y']
    else:
        cmd = ['ffmpeg', '-i', input_file, '-lavfi', f"showspectrumpic=s={config['VISUALIZATION_SIZE']}:mode={config['SPECTROGRAM_MODE']}", vis_file, '-y']

    _, stderr, rc = run_command(cmd)
    if rc != 0:
        logger.error(f"Error generating {config['VISUALIZATION_TYPE']} for {input_file}: {stderr}")
        return False
    else:
        logger.info(f"Generated {config['VISUALIZATION_TYPE']}: {vis_file}")
        return True