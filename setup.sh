#!/bin/bash
pip install demucs flask
pip3 install -U --pre yt-dlp
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
apt update
apt install nodejs -y