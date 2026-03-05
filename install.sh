#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] python3 is required"
  exit 1
fi

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "${ROOT_DIR}/requirements.txt"
python -m pip install -e "${ROOT_DIR}"

echo "[+] Installation complete"
echo "[*] Activate with: source ${VENV_DIR}/bin/activate"
echo "[*] Test with: mythic-operator --help"
