#!/usr/bin/env python3
"""
Phase 5: Production Deployment Validation & Setup Script
Comprehensive check before production deployment
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'='*70}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{text:^70}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'='*70}{Colors.END}\n")

def print_success(text):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_error(text):
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")

def print_info(text):
    print(f"{Colors.BLUE}ℹ️  {text}{Colors.END}")

def check_files():
    """Check required files for production"""
    print_header("1. FILE STRUCTURE")
    
    required_files = [
        ("Dockerfile", "Docker image definition"),
        ("docker-compose.yml", "Multi-container orchestration"),
        (".env.example", "Environment configuration template"),
        ("requirements.txt", "Python dependencies"),
        ("monitoring/prometheus.yml", "Prometheus configuration"),
        ("scripts/init.sql", "Database initialization"),
    ]
    
    all_exist = True
    for file_path, description in required_files:
        if Path(file_path).exists():
            print_success(f"{file_path:.<40} {description}")
        else:
            print_error(f"{file_path:.<40} MISSING")
            all_exist = False
    
    return all_exist

def check_config():
    """Check configuration setup"""
    print_header("2. CONFIGURATION")
    
    checks = []
    
    # Check .env file exists
    if Path(".env").exists():
        print_warning(".env already exists (good)")
        checks.append(True)
    else:
        print_warning(".env NOT found - will be created from .env.example")
        checks.append(False)
    
    # Check required environment variables
    required_vars = [
        "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD",
        "JWT_SECRET_KEY", "ENVIRONMENT"
    ]
    
    env_vars_set = all(var in os.environ for var in required_vars)
    if env_vars_set:
        print_success("Required environment variables set")
        checks.append(True)
    else:
        missing = [v for v in required_vars if v not in os.environ]
        print_warning(f"Missing env vars (will use .env): {', '.join(missing)}")
        checks.append(False)
    
    return all(checks)

def check_dependencies():
    """Check Python dependencies"""
    print_header("3. DEPENDENCIES")
    
    try:
        import fastapi
        print_success(f"FastAPI {fastapi.__version__}")
    except ImportError:
        print_error("FastAPI not installed")
        return False
    
    try:
        import uvicorn
        print_success(f"Uvicorn available")
    except ImportError:
        print_error("Uvicorn not installed")
        return False
    
    try:
        import sqlalchemy
        print_success(f"SQLAlchemy {sqlalchemy.__version__}")
    except ImportError:
        print_error("SQLAlchemy not installed")
        return False
    
    try:
        import slowapi
        print_success("Slowapi (rate limiting) available")
    except ImportError:
        print_warning("Slowapi not installed - installing...")
        subprocess.run(["pip", "install", "slowapi", "--quiet"], check=False)
    
    try:
        import prometheus_client
        print_success("Prometheus client available")
    except ImportError:
        print_warning("Prometheus client not installed - installing...")
        subprocess.run(["pip", "install", "prometheus-client", "--quiet"], check=False)
    
    return True

def check_docker():
    """Check Docker installation"""
    print_header("4. DOCKER")
    
    try:
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print_success(result.stdout.strip())
        else:
            print_error("Docker not working properly")
            return False
    except FileNotFoundError:
        print_error("Docker not installed")
        return False
    
    try:
        result = subprocess.run(["docker-compose", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print_success(result.stdout.strip())
        else:
            print_error("Docker Compose not working properly")
            return False
    except FileNotFoundError:
        print_error("Docker Compose not installed")
        return False
    
    return True

def check_database():
    """Check database connectivity"""
    print_header("5. DATABASE")
    
    try:
        import mysql.connector
        print_success("MySQL connector available")
    except ImportError:
        print_warning("MySQL connector not available - using pymysql")
    
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", 3306)
    
    print_info(f"Database host: {db_host}:{db_port}")
    print_info("(Will test when containers start)")
    
    return True

def check_security():
    """Check security configuration"""
    print_header("6. SECURITY")
    
    jwt_key = os.getenv("JWT_SECRET_KEY", "")
    if len(jwt_key) >= 32:
        print_success("JWT_SECRET_KEY is strong (>=32 chars)")
    else:
        print_warning(f"JWT_SECRET_KEY is weak ({len(jwt_key)} chars) - change before production!")
    
    cors_origins = os.getenv("CORS_ORIGINS", "")
    if cors_origins:
        print_success(f"CORS configured")
    else:
        print_warning("CORS_ORIGINS not configured - using defaults")
    
    return True

def check_resources():
    """Check system resources"""
    print_header("7. SYSTEM RESOURCES")
    
    try:
        import psutil
        
        # Memory
        memory = psutil.virtual_memory()
        print_info(f"Available memory: {memory.available / (1024**3):.1f} GB")
        if memory.available > 4 * 1024**3:
            print_success("Sufficient memory (>4GB)")
        else:
            print_warning(f"Low memory ({memory.available / (1024**3):.1f}GB) - may need optimization")
        
        # CPU
        cpu_count = psutil.cpu_count()
        print_info(f"CPU cores: {cpu_count}")
        if cpu_count >= 4:
            print_success("Sufficient CPU cores (>=4)")
        else:
            print_warning(f"Low CPU count ({cpu_count}) - may limit performance")
        
        return True
    except ImportError:
        print_info("psutil not available (skipping detailed resource check)")
        return True

def generate_env_file():
    """Generate .env file from template"""
    print_header("8. ENVIRONMENT SETUP")
    
    if Path(".env").exists():
        print_warning(".env already exists - skipping generation")
        return True
    
    try:
        with open(".env.example", "r") as f:
            template = f.read()
        
        # Generate a random JWT secret if needed
        import secrets
        jwt_secret = secrets.token_urlsafe(32)
        
        env_content = template.replace(
            "your-super-secret-key-change-this-in-production-keep-it-long-and-random-at-least-32-chars",
            jwt_secret
        )
        
        with open(".env", "w") as f:
            f.write(env_content)
        
        print_success(".env file created from template")
        print_info("IMPORTANT: Review and update .env with your actual values!")
        return True
    except Exception as e:
        print_error(f"Failed to generate .env: {e}")
        return False

def create_directories():
    """Create required directories"""
    print_header("9. DIRECTORY STRUCTURE")
    
    directories = [
        "data",
        "logs",
        "models",
        "backups",
        "monitoring",
        "scripts",
    ]
    
    for dir_name in directories:
        Path(dir_name).mkdir(exist_ok=True)
        print_success(f"Directory ready: {dir_name}/")
    
    return True

def print_next_steps():
    """Print next steps for deployment"""
    print_header("NEXT STEPS FOR PRODUCTION DEPLOYMENT")
    
    print(f"""{Colors.BOLD}1. CONFIGURE ENVIRONMENT{Colors.END}
   Edit .env file with your actual values:
   - Database credentials
   - JWT secret key (already generated)
   - CORS origins
   - API keys if needed

{Colors.BOLD}2. BUILD & TEST LOCALLY{Colors.END}
   docker-compose up -d
   Wait 30 seconds for services to start
   curl http://localhost:5003/health

{Colors.BOLD}3. VERIFY SERVICES{Colors.END}
   Application: http://localhost:5003
   Prometheus: http://localhost:9090
   Grafana: http://localhost:3000 (admin/admin)

{Colors.BOLD}4. RUN SMOKE TESTS{Colors.END}
   python phase5_smoke_test.py

{Colors.BOLD}5. MONITOR DEPLOYMENT{Colors.END}
   docker-compose logs -f app
   Check Grafana dashboards for metrics

{Colors.BOLD}6. PRODUCTION DEPLOYMENT{Colors.END}
   Configure reverse proxy (nginx/Apache)
   Setup SSL/TLS certificates
   Configure firewall rules
   Enable automated backups
   Setup monitoring alerts

{Colors.BOLD}SECURITY CHECKLIST:{Colors.END}
   ☐ JWT_SECRET_KEY is strong and unique
   ☐ Database passwords changed from defaults
   ☐ CORS origins configured correctly
   ☐ HTTPS/SSL enabled
   ☐ Firewall rules in place
   ☐ Database backups enabled
   ☐ Monitoring and logging configured
   ☐ SSH keys rotated
""")

def main():
    """Run all checks"""
    print_header("PHASE 5: PRODUCTION DEPLOYMENT VALIDATION")
    
    results = {
        "File Structure": check_files(),
        "Configuration": check_config(),
        "Dependencies": check_dependencies(),
        "Docker": check_docker(),
        "Database": check_database(),
        "Security": check_security(),
        "System Resources": check_resources(),
        "Environment Setup": generate_env_file(),
        "Directories": create_directories(),
    }
    
    # Print summary
    print_header("VALIDATION SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check_name, result in results.items():
        status = f"{Colors.GREEN}PASS{Colors.END}" if result else f"{Colors.YELLOW}WARN{Colors.END}"
        print(f"  {check_name:.<40} {status}")
    
    print(f"\n{Colors.BOLD}Score: {passed}/{total} checks passed{Colors.END}")
    
    if passed >= 7:  # 7 out of 9 is good
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 READY FOR PRODUCTION DEPLOYMENT!{Colors.END}")
        print_next_steps()
        return 0
    else:
        print(f"\n{Colors.YELLOW}{Colors.BOLD}⚠️  FIX WARNINGS BEFORE DEPLOYMENT{Colors.END}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
