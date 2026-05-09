#!/bin/bash

# ===================================================
# Google Maps Installation Helper - Falcon AI Vision
# ===================================================

echo "🚀 Falcon AI Vision - Google Maps Installation"
echo "==========================================="
echo ""

# Vérifier si on est dans le bon répertoire
if [ ! -d "falcon-ai-vision-platform/frontend" ]; then
    echo "❌ Erreur: Exécute ce script depuis la racine du projet"
    echo "   cd falcon-ai-vision-platform && bash install_maps.sh"
    exit 1
fi

# Aller au dossier frontend
cd falcon-ai-vision-platform/frontend

echo "📦 Installation des packages Google Maps..."
echo ""

# Installer les packages
npm install @react-google-maps/api @types/google.maps

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Packages installés avec succès!"
    echo ""
    echo "📋 Prochaines étapes:"
    echo "   1. Crée .env.local avec ta clé API"
    echo "   2. Ajoute: VITE_GOOGLE_MAPS_API_KEY=AIzaSy..."
    echo "   3. Lance: npm run dev"
    echo ""
else
    echo ""
    echo "❌ Erreur lors de l'installation"
    echo "   Vérifiez que Node.js et npm sont installés"
    exit 1
fi
