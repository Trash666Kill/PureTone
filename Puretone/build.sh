# Dependências de sistema
sudo apt install \
    gcc ccache patchelf \
    python3 python3-dev python3-pip \
    python3-requests python3-watchdog

# venv
python3 -m venv venv
source venv/bin/activate

# Nuitka e zstandard (compressão do onefile) no usuário
pip install nuitka zstandard --break-system-packages