# vms/backend/services/camera_manager.py - Gestionnaire caméras

from sqlalchemy.orm import Session
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from models import Camera
import socket
import time

class CameraManager:
    """Gestionnaire centralisé pour les caméras"""
    
    # Cache des états de connexion
    _connection_cache = {}
    
    @staticmethod
    def test_all_cameras(db: Session, timeout: int = 5) -> Dict:
        """Tester la connexion de toutes les caméras"""
        try:
            cameras = db.query(Camera).all()
            results = {
                "total": len(cameras),
                "online": 0,
                "offline": 0,
                "unknown": 0,
                "cameras": []
            }
            
            for camera in cameras:
                status = CameraManager.test_camera_connection(db, camera.id, timeout)
                results["cameras"].append(status)
                
                if status["status"] == "connected":
                    results["online"] += 1
                elif status["status"] == "disconnected":
                    results["offline"] += 1
                else:
                    results["unknown"] += 1
            
            return results
        except Exception as e:
            raise Exception(f"Failed to test cameras: {str(e)}")
    
    @staticmethod
    def test_camera_connection(db: Session, camera_id: int, timeout: int = 5) -> Dict:
        """Tester la connexion d'une caméra"""
        try:
            camera = db.query(Camera).filter(Camera.id == camera_id).first()
            if not camera:
                return {"error": "Camera not found"}
            
            start_time = time.time()
            try:
                # Tester la connexion TCP
                socket.create_connection(
                    (camera.ip_address, camera.port or 554),
                    timeout=timeout
                ).close()
                latency = int((time.time() - start_time) * 1000)
                
                camera.connection_status = "connected"
                camera.last_connection_check = datetime.utcnow()
                camera.connection_error = None
                db.commit()
                
                return {
                    "camera_id": camera_id,
                    "status": "connected",
                    "latency_ms": latency
                }
            except socket.timeout:
                camera.connection_status = "timeout"
                camera.last_connection_check = datetime.utcnow()
                camera.connection_error = "Connection timeout"
                db.commit()
                
                return {
                    "camera_id": camera_id,
                    "status": "timeout",
                    "error": "Connection timeout"
                }
            except Exception as e:
                camera.connection_status = "disconnected"
                camera.last_connection_check = datetime.utcnow()
                camera.connection_error = str(e)
                db.commit()
                
                return {
                    "camera_id": camera_id,
                    "status": "disconnected",
                    "error": str(e)
                }
        except Exception as e:
            raise Exception(f"Failed to test camera: {str(e)}")
    
    @staticmethod
    def get_camera_status(db: Session, camera_id: int) -> Dict:
        """Obtenir l'état détaillé d'une caméra"""
        try:
            camera = db.query(Camera).filter(Camera.id == camera_id).first()
            if not camera:
                raise Exception("Camera not found")
            
            return {
                "camera_id": camera.id,
                "name": camera.name,
                "status": camera.connection_status,
                "last_check": camera.last_connection_check.isoformat() if camera.last_connection_check else None,
                "error": camera.connection_error,
                "ip_address": camera.ip_address,
                "port": camera.port
            }
        except Exception as e:
            raise Exception(f"Failed to get camera status: {str(e)}")
    
    @staticmethod
    def get_offline_cameras(db: Session) -> List[Dict]:
        """Récupérer les caméras hors ligne"""
        try:
            cameras = db.query(Camera).filter(
                Camera.connection_status == "disconnected"
            ).all()
            
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "error": c.connection_error,
                    "last_check": c.last_connection_check.isoformat() if c.last_connection_check else None
                }
                for c in cameras
            ]
        except Exception as e:
            raise Exception(f"Failed to get offline cameras: {str(e)}")
    
    @staticmethod
    def get_health_report(db: Session) -> Dict:
        """Obtenir un rapport de santé de toutes les caméras"""
        try:
            cameras = db.query(Camera).all()
            
            total = len(cameras)
            online = len([c for c in cameras if c.connection_status == "connected"])
            offline = len([c for c in cameras if c.connection_status == "disconnected"])
            unknown = total - online - offline
            
            health_percentage = (online / total * 100) if total > 0 else 0
            
            return {
                "total_cameras": total,
                "online": online,
                "offline": offline,
                "unknown": unknown,
                "health_percentage": round(health_percentage, 2),
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            raise Exception(f"Failed to get health report: {str(e)}")
