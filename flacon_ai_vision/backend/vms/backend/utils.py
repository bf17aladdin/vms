# vms/backend/utils.py - Fonctions utilitaires

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import json
import logging
from functools import wraps
import time

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============= UTILITAIRES DIVERS =============

def get_timestamp() -> str:
    """Obtenir le timestamp courant au format ISO"""
    return datetime.utcnow().isoformat()

def get_timestamp_human() -> str:
    """Obtenir un timestamp lisible"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def time_ago(dt: datetime) -> str:
    """Convertir une datetime en texte "il y a X..."
    
    Args:
        dt: datetime à convertir
        
    Returns:
        Chaîne formatée (ex: "il y a 5 minutes")
    """
    if not dt:
        return "Jamais"
    
    diff = datetime.utcnow() - dt
    
    if diff.days > 365:
        return f"il y a {diff.days // 365} ans"
    elif diff.days > 30:
        return f"il y a {diff.days // 30} mois"
    elif diff.days > 0:
        return f"il y a {diff.days} jours"
    elif diff.seconds > 3600:
        return f"il y a {diff.seconds // 3600} heures"
    elif diff.seconds > 60:
        return f"il y a {diff.seconds // 60} minutes"
    else:
        return "à l'instant"

def measure_execution_time(func):
    """Décorateur pour mesurer le temps d'exécution"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = (time.time() - start) * 1000
        logger.info(f"{func.__name__} took {duration:.2f}ms")
        return result
    return wrapper

# ============= UTILITAIRES VALIDATION =============

def validate_ip_address(ip: str) -> bool:
    """Valider une adresse IP"""
    import re
    pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
    if not re.match(pattern, ip):
        return False
    
    parts = ip.split('.')
    return all(0 <= int(p) <= 255 for p in parts)

def validate_port(port: int) -> bool:
    """Valider un numéro de port"""
    return 1 <= port <= 65535

def validate_email(email: str) -> bool:
    """Valider une adresse email"""
    import re
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None

def validate_username(username: str) -> bool:
    """Valider un nom d'utilisateur"""
    return 3 <= len(username) <= 50 and username.isalnum()

# ============= UTILITAIRES CONVERSION =============

def bytes_to_human_readable(bytes: int) -> str:
    """Convertir des octets en format lisible"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024.0:
            return f"{bytes:.2f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.2f} PB"

def seconds_to_human_readable(seconds: int) -> str:
    """Convertir des secondes en format lisible"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"

def dict_to_json(data: Dict) -> str:
    """Convertir un dictionnaire en JSON"""
    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error converting dict to JSON: {str(e)}")
        return "{}"

def json_to_dict(json_str: str) -> Dict:
    """Convertir une chaîne JSON en dictionnaire"""
    try:
        return json.loads(json_str)
    except Exception as e:
        logger.error(f"Error converting JSON to dict: {str(e)}")
        return {}

# ============= UTILITAIRES DONNÉES =============

def safe_dict_get(d: Dict, key: str, default: Any = None) -> Any:
    """Accès sécurisé à un dictionnaire"""
    return d.get(key, default) if isinstance(d, dict) else default

def flatten_dict(d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
    """Aplatir un dictionnaire imbriqué"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)

def filter_dict(d: Dict, keys: list) -> Dict:
    """Filtrer un dictionnaire pour ne garder que certaines clés"""
    return {k: v for k, v in d.items() if k in keys}

def merge_dicts(*dicts) -> Dict:
    """Fusionner plusieurs dictionnaires"""
    result = {}
    for d in dicts:
        if isinstance(d, dict):
            result.update(d)
    return result

# ============= UTILITAIRES PAGINATION =============

def paginate(items: list, skip: int = 0, limit: int = 100) -> tuple:
    """Paginer une liste"""
    total = len(items)
    paginated = items[skip:skip+limit]
    return paginated, total

def get_pagination_info(total: int, skip: int, limit: int) -> Dict:
    """Obtenir les infos de pagination"""
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "page": (skip // limit) + 1,
        "pages": (total + limit - 1) // limit
    }

# ============= UTILITAIRES LOGGING =============

def log_action(user_id: int, action: str, details: str = "") -> None:
    """Logger une action utilisateur"""
    logger.info(f"User {user_id} - Action: {action} - Details: {details}")

def log_error(error: Exception, context: str = "") -> None:
    """Logger une erreur"""
    logger.error(f"Error in {context}: {str(error)}", exc_info=True)

def log_info(message: str) -> None:
    """Logger une information"""
    logger.info(message)
