# Dependências de sistema
sudo apt install gcc ccache build-essential \
    python3 python3-dev python3-pip \
    libpython3-dev python3-venv

# venv
python3 -m venv venv
source venv/bin/activate

# Nuitka e zstandard (compressão do onefile) no usuário
pip install nuitka zstandard --break-system-packages



build-essential libpython3-dev python3-venv