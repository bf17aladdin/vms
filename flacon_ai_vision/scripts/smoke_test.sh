#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_CANDIDATES=(
  "${REPO_ROOT}/venv_ai/Scripts/python.exe"
  "${REPO_ROOT}/.venv/Scripts/python.exe"
  "${REPO_ROOT}/venv/Scripts/python.exe"
  "${REPO_ROOT}/.venv/bin/python"
  "${REPO_ROOT}/venv/bin/python"
  "python3"
  "python"
)

PYTHON_EXE=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
  if [[ "${candidate}" == "python3" || "${candidate}" == "python" ]]; then
    if command -v "${candidate}" >/dev/null 2>&1; then
      PYTHON_EXE="${candidate}"
      break
    fi
  elif [[ -f "${candidate}" ]]; then
    PYTHON_EXE="${candidate}"
    break
  fi
done

if [[ -z "${PYTHON_EXE}" ]]; then
  echo "Python executable not found." >&2
  exit 1
fi

exec "${PYTHON_EXE}" "${REPO_ROOT}/scripts/smoke_test.py" "$@"
