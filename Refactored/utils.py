import subprocess
import os
import re
import shutil
import uuid
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger('puretone')

def run_command(cmd: List[str], capture_output: bool = True) -> Tuple[str, str, int]:
    """Executa um comando e retorna stdout, stderr e código de retorno."""
    logger.debug(f"Executing command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=capture_output, text=True, check=False)
        if result.returncode != 0:
            logger.error(f"Command failed with return code {result.returncode}: {result.stderr}")
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        logger.error(f"Failed to execute command {' '.join(cmd)}: {e}")
        return "", str(e), 1

def normalize_path(path: str) -> str:
    """Normaliza um caminho, removendo barras duplicadas."""
    return os.path.normpath(path).replace('//', '/')

def validate_resolution(resolution: str) -> bool:
    """Valida se a resolução está no formato 'widthxheight'."""
    return bool(re.match(r'^\d+x\d+$', resolution))

def validate_volume(volume: str) -> bool:
    """Valida se o volume está no formato 'XdB'."""
    return bool(re.match(r'^[-+]?[0-9]*\.?[0-9]+dB$', volume))

def validate_addition(addition: str) -> bool:
    """Valida se o ajuste adicional de volume é válido e não negativo."""
    if not validate_volume(addition):
        return False
    value = float(addition.replace('dB', ''))
    return value >= 0

def add_db(value_db: str, addition_db: str) -> str:
    """Soma dois valores em dB."""
    value = float(value_db.replace('dB', '')) if value_db != 'N/A' else 0
    addition = float(addition_db.replace('dB', '')) if addition_db else 0
    return f"{(value + addition):.1f}dB"

def get_temp_file_path(basename: str) -> str:
    """Gera um caminho único para arquivo temporário."""
    unique_id = str(uuid.uuid4())
    return f"/tmp/puretone_{unique_id}_{basename}"

def check_dependencies():
    """Verifica se FFmpeg e ffprobe estão instalados e suportam os filtros necessários."""
    for cmd in ['ffmpeg', 'ffprobe']:
        if shutil.which(cmd) is None:
            logger.error(f"{cmd} não encontrado. Por favor, instale-o.")
            sys.exit(1)

    # Verificar versão mínima do FFmpeg
    stdout, _, rc = run_command(['ffmpeg', '-version'])
    version_match = re.search(r'ffmpeg version (\d+\.\d+\.\d+)', stdout)
    if not version_match:
        logger.error("Não foi possível determinar a versão do FFmpeg.")
        sys.exit(1)
    version = version_match.group(1)
    if tuple(map(int, version.split('.'))) < (4, 3, 0):
        logger.error("FFmpeg versão 4.3.0 ou superior é requerido.")
        sys.exit(1)

    # Testar suporte a filtros
    _, stderr, rc = run_command(['ffmpeg', '-filters'])
    required_filters = ['loudnorm', 'showspectrumpic', 'volumedetect', 'astats']
    for filt in required_filters:
        if filt not in stderr:
            logger.error(f"Filtro FFmpeg '{filt}' não suportado nesta instalação.")
            sys.exit(1)