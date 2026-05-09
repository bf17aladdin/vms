#!/bin/bash
# Démarrage automatisé du projet Falcon AI Vision (macOS/Linux)

echo "🚀 Démarrage Falcon AI Vision..."
echo ""

# Déterminer le répertoire
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Terminal 1 : Backend
echo "[1/2] Lancement Backend (uvicorn port 8000)..."
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Attendre un peu
sleep 3

# Terminal 2 : Frontend
echo "[2/2] Lancement Frontend (http.server port 8080)..."
cd frontend
python -m http.server 8080 &
FRONTEND_PID=$!

echo ""
echo "✅ Serveurs lancés !"
echo ""
echo "🌐 Frontend : http://localhost:8080"
echo "🔧 Backend  : http://localhost:8000"
echo ""
echo "PID Backend : $BACKEND_PID"
echo "PID Frontend: $FRONTEND_PID"
echo ""
echo "Pour arrêter : kill $BACKEND_PID $FRONTEND_PID"
echo ""

# Attendre que Ctrl+C arrête tout
trap "kill $BACKEND_PID $FRONTEND_PID" EXIT
wait
