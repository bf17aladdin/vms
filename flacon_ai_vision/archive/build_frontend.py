#!/usr/bin/env python
"""
Script de rebuild du frontend Falcon AI Vision
Recompile automatiquement le frontend React/Vite
"""

import subprocess
import os
import sys
from pathlib import Path

def run_command(cmd, cwd=None):
    """Exécute une commande et retourne le statut"""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=False, text=True, shell=True)
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False

def main():
    print("\n" + "="*70)
    print("  🔨 Falcon AI Vision - Frontend Build Script")
    print("="*70 + "\n")
    
    # Chemins
    frontend_dir = Path(__file__).parent / "vms" / "frontend"
    dist_dir = frontend_dir / "dist"
    
    print(f"📁 Frontend directory: {frontend_dir}")
    
    # Vérifier Node.js/npm
    print("\n1️⃣  Checking prerequisites...")
    print("-" * 70)
    
    result = subprocess.run("npm --version", capture_output=True, text=True, shell=True)
    if result.returncode == 0:
        npm_version = result.stdout.strip()
        print(f"✅ npm found: {npm_version}")
    else:
        print("❌ npm not found! Please install Node.js")
        return 1
    
    # Nettoyer le build précédent (optionnel)
    print("\n2️⃣  Cleaning previous build...")
    print("-" * 70)
    
    if dist_dir.exists():
        import shutil
        shutil.rmtree(dist_dir)
        print(f"✅ Cleaned: {dist_dir}")
    else:
        print("ℹ️  No previous build found")
    
    # Installer les dépendances (optionnel, en cas de mise à jour)
    if "--full" in sys.argv:
        print("\n3️⃣  Installing dependencies...")
        print("-" * 70)
        if run_command("npm install", cwd=str(frontend_dir)):
            print("✅ Dependencies installed")
        else:
            print("❌ Failed to install dependencies")
            return 1
    
    # Build
    print("\n3️⃣  Building frontend...")
    print("-" * 70)
    
    if run_command("npm run build", cwd=str(frontend_dir)):
        print("✅ Build completed successfully!")
        
        # Vérifier le build
        if dist_dir.exists():
            assets_dir = dist_dir / "assets"
            css_files = list(assets_dir.glob("*.css")) if assets_dir.exists() else []
            js_files = list(assets_dir.glob("*.js")) if assets_dir.exists() else []
            
            print(f"\n📊 Build Summary:")
            print(f"   • HTML files: {len(list(dist_dir.glob('*.html')))}")
            print(f"   • CSS files: {len(css_files)}")
            print(f"   • JS files: {len(js_files)}")
            print(f"   • Total size: {sum(f.stat().st_size for f in dist_dir.rglob('*') if f.is_file()) / 1024:.1f} KB")
        
        print("\n✨ Frontend is ready!")
        print("🚀 Start the backend server:")
        print("   python -m uvicorn vms.backend.main:app --reload")
        print("\n📱 Open: http://localhost:5003/")
        
        return 0
    else:
        print("❌ Build failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
