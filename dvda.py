import argparse
import subprocess
import sys
from pathlib import Path

def convert_mlp_to_wav(input_file, output_file):
    """Converte arquivo MLP para WAV com codec pcm_s24le."""
    try:
        command = ['ffmpeg', '-y', '-i', str(input_file), '-c:a', 'pcm_s24le', str(output_file)]
        subprocess.run(command, check=True)
        print(f"Arquivo MLP convertido para WAV: {output_file}")
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"Erro ao converter MLP {input_file}: {e}")
        return None
    except FileNotFoundError:
        print("FFmpeg não encontrado. Instale o FFmpeg.")
        sys.exit(1)

def downmix_wav(input_file, output_file, channels=2):
    """Faz downmix de arquivo WAV para o número de canais especificado, mantendo pcm_s24le."""
    try:
        command = ['ffmpeg', '-y', '-i', str(input_file), '-c:a', 'pcm_s24le', '-ac', str(channels), str(output_file)]
        subprocess.run(command, check=True)
        print(f"Arquivo WAV downmixed: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"Erro ao fazer downmix de {input_file}: {e}")
    except FileNotFoundError:
        print("FFmpeg não encontrado. Instale o FFmpeg.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Converte MLP para WAV e faz downmix de WAV para estéreo no diretório atual.")
    parser.add_argument('--downmix', type=int, default=2, help="Número de canais para downmix (padrão: 2 para estéreo)")
    parser.add_argument('--convert-mlp', action='store_true', help="Converte arquivos MLP para WAV (pcm_s24le)")

    args = parser.parse_args()

    # Diretório atual
    current_dir = Path.cwd()

    # Processa arquivos MLP se --convert-mlp for especificado
    if args.convert_mlp:
        mlp_files = [f for f in current_dir.glob("*.mlp") if "_pcm" not in f.stem and "_stereo" not in f.stem]
        if not mlp_files:
            print("Nenhum arquivo MLP original encontrado no diretório atual.")
        for mlp_file in mlp_files:
            # Cria novo arquivo com sufixo _pcm antes da extensão
            output_wav = mlp_file.with_name(f"{mlp_file.stem}_pcm.wav")
            converted_file = convert_mlp_to_wav(mlp_file, output_wav)
            if converted_file and args.downmix:
                # Faz downmix do arquivo WAV convertido, criando outro arquivo
                output_stereo = mlp_file.with_name(f"{mlp_file.stem}_stereo.wav")
                downmix_wav(converted_file, output_stereo, args.downmix)

    # Processa arquivos WAV para downmix
    wav_files = [f for f in current_dir.glob("*.wav") if "_pcm" not in f.stem and "_stereo" not in f.stem]
    if not wav_files:
        print("Nenhum arquivo WAV original encontrado no diretório atual.")
    for wav_file in wav_files:
        output_file = wav_file.with_name(f"{wav_file.stem}_stereo.wav")
        downmix_wav(wav_file, output_file, args.downmix)

if __name__ == "__main__":
    main()