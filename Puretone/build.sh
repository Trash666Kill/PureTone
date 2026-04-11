# Dependências de sistema
sudo apt install gcc ccache build-essential patchelf \
    python3 python3-dev python3-pip \
    libpython3-dev python3-venv

# venv
python3 -m venv .venv
source venv/bin/activate

# Nuitka e zstandard (compressão do onefile) no usuário
pip install nuitka zstandard

python3 -m nuitka \
    --onefile \
    --product-name=puretone \
    --product-version=1.0.0 \
    --onefile-tempdir-spec="{CACHE_DIR}/{PRODUCT}/{VERSION}" \
    --include-data-files=bin/sacd_extract=bin/sacd_extract \
    --output-filename=puretone \
    --output-dir=dist \
    --assume-yes-for-downloads \
    --remove-output \
    puretone.py


# Usage
./dist/puretone --format flac --compression-level 12 --sample-rate 88200 --parallel 6 --volume auto --volume-increase 2dB --spectrogram --log log.txt --keep-dsf /mnt/Services/Puretone/Download/0/ --output-dir /mnt/Services/Puretone/Music/0/Analyzing/

./puretone --format flac --compression-level 12 --sample-rate 88200 --parallel 6 --volume auto --volume-increase 2dB --spectrogram waveform --log log.txt --keep-dsf Michael\ Jackson\ -\ Off\ The\ Wall.iso



puretone --format flac --compression-level 12 --sample-rate 88200 --parallel 6 --volume auto --volume-increase 2dB --spectrogram --log log.txt --keep-dsf /mnt/Services/Puretone/Download/0/ --output-dir /mnt/Services/Puretone/Music/0/Analyzing/

puretone --format flac --compression-level 12 --sample-rate 88200 --parallel 6 --volume auto --volume-increase 2dB --spectrogram waveform --log log.txt --keep-dsf Michael\ Jackson\ -\ Off\ The\ Wall.iso