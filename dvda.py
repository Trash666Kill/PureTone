import argparse
import subprocess
import sys
import os
from pathlib import Path

def downmix_wav(input_file, output_file, channels=2):
    try:
        command = ['ffmpeg', '-i', str(input_file), '-ac', str(channels), str(output_file)]
        subprocess.run(command, check=True)
        print(f"Arquivo convertido: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Erro no FFmpeg para {input_file}: {e}")
    except FileNotFoundError:
        print("FFmpeg não encontrado. Instale o FFmpeg.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Downmix de arquivos WAV para estéreo no diretório atual.")
    parser.add_argument('--downmix', type=int, default=2, help="Número de canais (padrão: 2 para estéreo)")

    args = parser.parse_args()

    # Diretório atual
    current_dir = Path.cwd()
    # Lista de arquivos WAV no diretório
    wav_files = list(current_dir.glob("*.wav"))

    if not wav_files:
        print("Nenhum arquivo WAV encontrado no diretório atual.")
        sys.exit(0)

    for wav_file in wav_files:
        # Mantém o nome original, adiciona sufixo antes da extensão
        output_file = wav_file.with_name(f"{wav_file.stem}_stereo{wav_file.suffix}")
        downmix_wav(wav_file, output_file, args.downmix)

if __name__ == "__main__":
    main()