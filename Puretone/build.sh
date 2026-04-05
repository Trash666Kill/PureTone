# Dependências de sistema
sudo apt install gcc ccache build-essential \
    python3 python3-dev python3-pip \
    libpython3-dev python3-venv

# venv
python3 -m venv venv
source venv/bin/activate

# Nuitka e zstandard (compressão do onefile) no usuário
pip install nuitka zstandard

python3 -m nuitka \
    --onefile \
    --onefile-tempdir-spec="{CACHE_DIR}/{PRODUCT}/{VERSION}" \
    --include-data-files=bin/sacd_extract=bin/sacd_extract \
    --output-filename=puretone \
    --output-dir=dist \
    --assume-yes-for-downloads \
    --remove-output \
    puretone.py