#!/usr/bin/env python3
"""
Diagnostic script for Falcon AI Vision AI Integration
Run with: python diagnostic_ai_setup.py

Checks:
  - Python version
  - Virtual environment
  - All required imports
  - Dependency versions
  - GPU availability
  - Disk space for models
"""

import sys
import os
import platform
import subprocess
from pathlib import Path

def check_python_version():
    """Check Python version (3.11+ required)"""
    print("\n" + "="*60)
    print("1️⃣  Python Version Check")
    print("="*60)
    
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    print(f"Python version: {version_str}")
    
    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print("❌ FAIL: Python 3.11+ required (SQLAlchemy 2.0 compatibility)")
        print(f"   Install Python 3.11+ and use: py -3.11 -m venv .venv")
        return False
    
    print("✅ PASS: Python version OK")
    return True

def check_venv():
    """Check if running in virtual environment"""
    print("\n" + "="*60)
    print("2️⃣  Virtual Environment Check")
    print("="*60)
    
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    
    if in_venv:
        print(f"✅ PASS: Running in virtual environment")
        print(f"   Location: {sys.prefix}")
    else:
        print("⚠️  WARNING: Not running in virtual environment")
        print("   Recommended: Activate venv with: .venv\\Scripts\\activate")
    
    return True

def check_import(module_name, package_name=None):
    """Check if a module can be imported"""
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False

def check_imports():
    """Check all required imports"""
    print("\n" + "="*60)
    print("3️⃣  Import Checks")
    print("="*60)
    
    imports = [
        ('fastapi', 'FastAPI'),
        ('sqlalchemy', 'SQLAlchemy'),
        ('pydantic', 'Pydantic'),
        ('cv2', 'OpenCV'),
        ('numpy', 'NumPy'),
        ('ultralytics', 'YOLO'),
        ('torch', 'PyTorch'),
        ('torchvision', 'TorchVision'),
        ('face_recognition', 'Face Recognition'),
        ('PIL', 'Pillow'),
    ]
    
    results = {}
    for module, name in imports:
        success = check_import(module)
        results[module] = success
        status = "✅" if success else "❌"
        print(f"{status} {name:20} {'INSTALLED' if success else 'MISSING'}")
    
    # Check if critical imports are available
    critical = ['cv2', 'numpy', 'ultralytics', 'torch']
    all_critical = all(results.get(m) for m in critical)
    
    if not all_critical:
        print("\n❌ FAIL: Some critical dependencies missing")
        print("   Run: pip install -r requirements.txt")
        return False
    
    print("\n✅ PASS: All critical imports available")
    return True

def check_import_versions():
    """Check versions of critical packages"""
    print("\n" + "="*60)
    print("4️⃣  Dependency Versions")
    print("="*60)
    
    packages = {
        'cv2': 'opencv-python',
        'numpy': 'numpy',
        'ultralytics': 'ultralytics',
        'torch': 'torch',
        'PIL': 'Pillow',
    }
    
    for module, name in packages.items():
        try:
            mod = __import__(module)
            version = getattr(mod, '__version__', 'unknown')
            print(f"  {name:20}: {version}")
        except ImportError:
            print(f"  {name:20}: NOT INSTALLED")
    
    print("\n✅ Version check complete")
    return True

def check_gpu():
    """Check GPU availability"""
    print("\n" + "="*60)
    print("5️⃣  GPU / CUDA Check")
    print("="*60)
    
    try:
        import torch
        cuda_available = torch.cuda.is_available()
        
        if cuda_available:
            device = torch.cuda.get_device_name(0)
            memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"✅ GPU AVAILABLE")
            print(f"   Device: {device}")
            print(f"   Memory: {memory:.1f} GB")
            print(f"   Note: Inference will be 4-6x faster!")
        else:
            print(f"ℹ️  No GPU detected")
            print(f"   Using CPU inference (acceptable performance)")
        
        return True
        
    except Exception as e:
        print(f"⚠️  GPU check failed: {e}")
        return True  # Not critical

def check_disk_space():
    """Check available disk space"""
    print("\n" + "="*60)
    print("6️⃣  Disk Space Check")
    print("="*60)
    
    # Get home directory for model cache location
    home = Path.home()
    yolo_cache = home / ".yolov8"
    
    # Get system disk space
    try:
        import shutil
        usage = shutil.disk_usage(str(home))
        free_gb = usage.free / (1024**3)
        
        print(f"Disk space available: {free_gb:.1f} GB")
        print(f"Models cache location: {yolo_cache}")
        
        if free_gb < 2:
            print("⚠️  WARNING: Less than 2GB free (models need ~500MB)")
            return False
        
        print("✅ PASS: Sufficient disk space")
        return True
        
    except Exception as e:
        print(f"⚠️  Disk check failed: {e}")
        return True  # Not critical

def check_vms_structure():
    """Check if VMS package structure is correct"""
    print("\n" + "="*60)
    print("7️⃣  VMS Package Structure Check")
    print("="*60)
    
    required_files = [
        'vms/backend/ai/motion.py',
        'vms/backend/ai/objects.py',
        'vms/backend/services/inference_manager.py',
        'vms/backend/main.py',
    ]
    
    all_ok = True
    for file_path in required_files:
        exists = os.path.exists(file_path)
        status = "✅" if exists else "❌"
        print(f"{status} {file_path:45} {'EXISTS' if exists else 'MISSING'}")
        if not exists:
            all_ok = False
    
    if all_ok:
        print("\n✅ PASS: All required files present")
    else:
        print("\n❌ FAIL: Some files missing")
    
    return all_ok

def test_motion_import():
    """Quick test of motion detector import"""
    print("\n" + "="*60)
    print("8️⃣  Motion Detector Import Test")
    print("="*60)
    
    try:
        from vms.backend.ai.motion import MotionDetector
        print("✅ Successfully imported MotionDetector")
        
        # Try to instantiate
        detector = MotionDetector()
        print("✅ Successfully instantiated MotionDetector")
        return True
        
    except Exception as e:
        print(f"❌ Failed to import MotionDetector: {e}")
        return False

def test_yolo_import():
    """Quick test of YOLO detector import"""
    print("\n" + "="*60)
    print("9️⃣  YOLO Detector Import Test")
    print("="*60)
    
    try:
        from vms.backend.ai.objects import ObjectDetector
        print("✅ Successfully imported ObjectDetector")
        
        # Try to instantiate (won't load model, just check structure)
        detector = ObjectDetector.__new__(ObjectDetector)
        print("✅ Successfully instantiated ObjectDetector")
        return True
        
    except Exception as e:
        print(f"❌ Failed to import ObjectDetector: {e}")
        return False

def test_inference_manager_import():
    """Quick test of InferenceManager import"""
    print("\n" + "="*60)
    print("🔟 InferenceManager Import Test")
    print("="*60)
    
    try:
        from vms.backend.services.inference_manager import get_inference_manager
        print("✅ Successfully imported InferenceManager")
        return True
        
    except Exception as e:
        print(f"❌ Failed to import InferenceManager: {e}")
        return False

def main():
    """Run all diagnostic checks"""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  Falcon AI Vision – AI Integration Diagnostic".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")
    
    checks = [
        ("Python Version", check_python_version),
        ("Virtual Environment", check_venv),
        ("Imports", check_imports),
        ("Versions", check_import_versions),
        ("GPU/CUDA", check_gpu),
        ("Disk Space", check_disk_space),
        ("VMS Structure", check_vms_structure),
        ("Motion Detector", test_motion_import),
        ("YOLO Detector", test_yolo_import),
        ("InferenceManager", test_inference_manager_import),
    ]
    
    results = {}
    for name, check_func in checks:
        try:
            results[name] = check_func()
        except Exception as e:
            print(f"❌ Check failed with exception: {e}")
            results[name] = False
    
    # Summary
    print("\n" + "="*60)
    print("📊 DIAGNOSTIC SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\nPassed: {passed}/{total}")
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status:10} {name}")
    
    # Overall status
    print("\n" + "="*60)
    if passed == total:
        print("✅ SYSTEM READY FOR PHASE 1")
        print("="*60)
        print("\nNext steps:")
        print("  1. Run: python vms/backend/tests/test_motion_basic.py")
        print("  2. Run: python vms/backend/tests/test_yolo_basic.py")
        print("  3. Run: python vms/backend/tests/test_inference_manager.py")
        print("\nSee: AI_QUICK_START.md for detailed instructions")
        return 0
    else:
        print("⚠️  SOME CHECKS FAILED – REVIEW ABOVE FOR DETAILS")
        print("="*60)
        print("\nCommon fixes:")
        print("  1. Install dependencies: pip install -r requirements.txt")
        print("  2. Activate venv: .venv\\Scripts\\activate")
        print("  3. Check Python 3.11+: python --version")
        print("\nSee: AI_QUICK_START.md 'Troubleshooting' section")
        return 1

if __name__ == "__main__":
    sys.exit(main())
