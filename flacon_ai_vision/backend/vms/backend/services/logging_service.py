"""
Logging persistant et gestion des erreurs
Priorité 4: Logs persistants, gestion erreurs, robustesse
"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
import traceback
import sys

logger = logging.getLogger("falcon_ai_vision")


class SystemLogger:
    """Service de logging persistant en BD + fichier"""
    
    # Levels
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    
    def __init__(self, db: Session):
        self.db = db
    
    def log(self, level: str, message: str, module: str = "system", details: Optional[str] = None):
        """Enregistrer un log en BD + fichier"""
        from vms.backend.models import SystemLog
        
        try:
            log_entry = SystemLog(
                level=level,
                module=module,
                message=message,
                extra_data={"details": details} if details else None,
            )
            self.db.add(log_entry)
            self.db.commit()
            
            # Aussi log dans le logger standard
            log_func = getattr(logger, level.lower(), logger.info)
            log_func(f"[{module}] {message}" + (f" | {details}" if details else ""))
            
        except Exception as e:
            # Failsafe si la BD échoue
            logger.error(f"Failed to log to DB: {e}")
            logger.error(f"Original: [{module}] {message}")
    
    def log_error(self, module: str, exception: Exception, action: str = "Operation failed"):
        """Enregistrer une erreur avec stack trace"""
        tb_str = traceback.format_exc()
        details = f"{action}\n{tb_str}"
        self.log(self.ERROR, str(exception), module=module, details=details)
    
    def log_info(self, module: str, message: str):
        """Enregistrer une info"""
        self.log(self.INFO, message, module=module)
    
    def log_warning(self, module: str, message: str):
        """Enregistrer un warning"""
        self.log(self.WARNING, message, module=module)
    
    def get_logs(self, level: Optional[str] = None, module: Optional[str] = None, limit: int = 100) -> list:
        """Récupérer les logs"""
        from vms.backend.models import SystemLog
        
        try:
            query = self.db.query(SystemLog)
            
            if level:
                query = query.filter(SystemLog.level == level)
            if module:
                query = query.filter(SystemLog.module == module)
            
            logs = query.order_by(SystemLog.created_at.desc()).limit(limit).all()
            
            return [
                {
                    "timestamp": log.created_at.isoformat() if log.created_at else None,
                    "level": log.level,
                    "module": log.module,
                    "message": log.message,
                    "details": (log.extra_data or {}).get("details") if isinstance(log.extra_data, dict) else log.extra_data,
                }
                for log in logs
            ]
            
        except Exception as e:
            logger.error(f"Error retrieving logs: {e}")
            return []


class ErrorHandler:
    """Gestionnaire centralisé des erreurs"""
    
    def __init__(self, db: Session):
        self.db = db
        self.logger = SystemLogger(db)
    
    def handle_facial_exception(self, exc: Exception, context: dict = None) -> dict:
        """Gérer une erreur de reconnaissance faciale"""
        details = context or {}
        
        self.logger.log_error(
            module="facial",
            exception=exc,
            action=f"Facial recognition failed: {details}"
        )
        
        return {
            "success": False,
            "error": "Facial recognition service unavailable",
            "code": "FACIAL_ERROR",
            "details": str(exc)
        }
    
    def handle_vehicle_exception(self, exc: Exception, context: dict = None) -> dict:
        """Gérer une erreur de détection véhicule"""
        details = context or {}
        
        self.logger.log_error(
            module="vehicles",
            exception=exc,
            action=f"Vehicle detection failed: {details}"
        )
        
        return {
            "success": False,
            "error": "Vehicle detection service unavailable",
            "code": "VEHICLE_ERROR",
            "details": str(exc)
        }
    
    def handle_zone_exception(self, exc: Exception, context: dict = None) -> dict:
        """Gérer une erreur de zone"""
        details = context or {}
        
        self.logger.log_error(
            module="zones",
            exception=exc,
            action=f"Zone operation failed: {details}"
        )
        
        return {
            "success": False,
            "error": "Zone service unavailable",
            "code": "ZONE_ERROR",
            "details": str(exc)
        }
    
    def handle_database_exception(self, exc: Exception) -> dict:
        """Gérer une erreur de base de données"""
        self.logger.log_error(
            module="database",
            exception=exc,
            action="Database operation failed"
        )
        
        return {
            "success": False,
            "error": "Database error",
            "code": "DB_ERROR",
            "details": str(exc)
        }


# Configuration de logging multi-niveau
def setup_logging(log_file: str = "logs/vms.log"):
    """Configurer le logging fichier + console"""
    import os
    from pathlib import Path
    
    # Créer le dossier logs si nécessaire
    Path("logs").mkdir(exist_ok=True)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler fichier
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    
    # Handler console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    
    # Ajouter aux loggers
    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.setLevel(logging.DEBUG)
