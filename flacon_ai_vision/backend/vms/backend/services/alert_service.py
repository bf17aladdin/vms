# vms/backend/services/alert_service.py - Gestion centralisée des alertes

import asyncio
import inspect
import logging
from datetime import datetime
from threading import RLock
from typing import Any, Callable, Dict, List, Optional
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import func

from vms.backend.services.setup_config_service import DEFAULT_PROFILES, get_setup_config_service
from vms.backend.core.database import get_db
from vms.backend.core.config import settings
from vms.backend.models import Alert as AlertModel
from datetime import timedelta

logger = logging.getLogger(__name__)


class AlertType(str, Enum):
    """Types d'alertes supportées"""
    MOTION = "motion"
    VEHICLE = "vehicle"
    PERSON = "person"
    FACE = "face"
    ALARM = "alarm"
    SYSTEM = "system"


class AlertSeverity(str, Enum):
    """Niveaux de sévérité"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def normalize_alert_type(value: object) -> str:
    return str(value or "").strip().lower()


def get_allowed_alert_types() -> set[str]:
    """Resolve allowed alert types based on current profile configuration."""
    config = get_setup_config_service().get_config()
    usage_type = str(config.get("usage_type") or "maison").strip().lower()
    defaults = DEFAULT_PROFILES.get(usage_type, DEFAULT_PROFILES["maison"])
    raw_types = config.get("alert_types") or defaults.get("alert_types") or []
    allowed = {normalize_alert_type(item) for item in raw_types if normalize_alert_type(item)}
    if "system" not in allowed:
        allowed.add("system")
    return allowed


def filter_alert_payloads(
    alerts: List[Dict],
    *,
    allowed_types: Optional[set[str]] = None,
    requested_type: Optional[str] = None,
    camera_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> List[Dict]:
    """Filter alert payloads by profile limits and optional query filters."""
    normalized_allowed = allowed_types or set()
    requested_norm = normalize_alert_type(requested_type) if requested_type else ""
    camera_filter = int(camera_id) if camera_id is not None else None

    filtered: List[Dict] = []
    for alert in alerts:
        alert_type = normalize_alert_type(alert.get("type"))
        if normalized_allowed and alert_type not in normalized_allowed:
            continue
        if requested_norm and alert_type != requested_norm:
            continue
        if tenant_id is not None:
            try:
                alert_tenant = int(alert.get("tenant_id") or 0)
            except (TypeError, ValueError):
                alert_tenant = 0
            if alert_tenant != int(tenant_id):
                continue
        if camera_filter is not None:
            try:
                alert_camera = int(alert.get("camera_id") or 0)
            except (TypeError, ValueError):
                alert_camera = 0
            if alert_camera != camera_filter:
                continue
        filtered.append(alert)
    return filtered


class Alert:
    """Objet alerte"""
    
    def __init__(
        self,
        camera_id: int,
        camera_name: str,
        alert_type: AlertType,
        message: str,
        severity: AlertSeverity = AlertSeverity.MEDIUM,
        data: Optional[Dict] = None,
        tenant_id: Optional[int] = None
    ):
        self.id = None
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.tenant_id = tenant_id
        self.type = alert_type
        self.message = message
        self.severity = severity
        self.data = data or {}
        self.timestamp = datetime.utcnow()
        self.acknowledged = False
        self.acknowledged_at = None
        self.acknowledged_by = None
    
    def to_dict(self) -> Dict:
        """Convertir en dictionnaire"""
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'camera_id': self.camera_id,
            'camera_name': self.camera_name,
            'type': self.type.value,
            'message': self.message,
            'severity': self.severity.value,
            'timestamp': self.timestamp.isoformat(),
            'acknowledged': self.acknowledged,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'acknowledged_by': self.acknowledged_by,
            'data': self.data
        }


class AlertService:
    """Service centralisé de gestion des alertes"""
    
    def __init__(self):
        """Initialiser le service"""
        self._lock = RLock()
        self.active_alerts: Dict[int, Alert] = {}  # id -> Alert
        self.alert_history: List[Alert] = []
        self.alert_callbacks: Dict[int, tuple[Callable[[Alert], Any], Optional[asyncio.AbstractEventLoop]]] = {}
        self.max_history = 1000
        self._next_callback_id = 0
        self._next_alert_id = 0
    
    def register_callback(
        self,
        callback: Callable[[Alert], Any],
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> int:
        """Enregistrer un callback pour les nouvelles alertes"""
        with self._lock:
            self._next_callback_id += 1
            callback_id = int(self._next_callback_id)
            self.alert_callbacks[callback_id] = (callback, loop)
            return callback_id

    def unregister_callback(self, callback_id: int) -> None:
        """Supprimer un callback enregistré"""
        with self._lock:
            self.alert_callbacks.pop(int(callback_id), None)
    
    def create_alert(
        self,
        camera_id: int,
        camera_name: str,
        alert_type: AlertType,
        message: str,
        severity: AlertSeverity = AlertSeverity.MEDIUM,
        data: Optional[Dict] = None,
        tenant_id: Optional[int] = None
    ) -> Alert:
        """
        Créer une nouvelle alerte.

        Args:
            camera_id: ID de la caméra
            camera_name: Nom de la caméra
            alert_type: Type d'alerte
            message: Message d'alerte
            severity: Niveau de sévérité
            data: Données additionnelles

        Returns:
            Objet Alert
        """
        try:
            alert = Alert(
                camera_id=camera_id,
                camera_name=camera_name,
                alert_type=alert_type,
                message=message,
                severity=severity,
                data=data,
                tenant_id=tenant_id,
            )

            # Save to database
            db = next(get_db())
            try:
                db_alert = AlertModel(
                    tenant_id=tenant_id,
                    camera_id=camera_id,
                    zone_id=None,  # Will be set if available
                    rule_type=alert_type.value,
                    title=f"{alert_type.value.upper()} Alert",
                    message=message,
                    severity=severity.value,
                    timestamp=alert.timestamp,
                    extra_data=data or {}
                )
                db.add(db_alert)
                db.commit()
                db.refresh(db_alert)

                # Set the database ID on the alert object
                alert.id = db_alert.id
            finally:
                db.close()

            with self._lock:
                # Keep in-memory cache for active alerts (non-acknowledged)
                self.active_alerts[alert.id] = alert
                callbacks = list(self.alert_callbacks.items())

            for callback_id, (callback, callback_loop) in callbacks:
                try:
                    self._dispatch_callback(
                        callback_id=callback_id,
                        callback=callback,
                        callback_loop=callback_loop,
                        alert=alert,
                    )
                except Exception as e:
                    logger.error(f"Erreur callback alerte: {e}")

            try:
                from vms.backend.routers.ws import broadcast_api_event_sync

                payload = alert.to_dict()
                payload["server_ts"] = datetime.utcnow().isoformat()
                broadcast_api_event_sync(
                    "alert_created",
                    payload,
                    channel="alerts",
                )
            except Exception:
                logger.debug("Impossible de diffuser l'alerte sur /api/ws", exc_info=True)

            logger.info(f"Alerte créée: {alert.type.value} - {alert.message}")
            return alert

        except Exception as e:
            logger.error(f"Erreur création alerte: {e}")
            raise
    
    def trigger_motion_alert(
        self,
        camera_id: int,
        camera_name: str,
        confidence: float = 0.8,
        roi: Optional[Dict] = None,
        tenant_id: Optional[int] = None
    ) -> Alert:
        """Déclencher une alerte mouvement"""
        return self.create_alert(
            camera_id=camera_id,
            camera_name=camera_name,
            alert_type=AlertType.MOTION,
            message=f"Mouvement détecté (confiance: {confidence:.1%})",
            severity=AlertSeverity.LOW,
            data={'confidence': confidence, 'roi': roi},
            tenant_id=tenant_id
        )
    
    def trigger_vehicle_alert(
        self,
        camera_id: int,
        camera_name: str,
        vehicle_type: str,
        confidence: float = 0.8,
        count: int = 1,
        tenant_id: Optional[int] = None
    ) -> Alert:
        """Déclencher une alerte véhicule"""
        return self.create_alert(
            camera_id=camera_id,
            camera_name=camera_name,
            alert_type=AlertType.VEHICLE,
            message=f"{count} {vehicle_type}(s) détecté(s) (confiance: {confidence:.1%})",
            severity=AlertSeverity.MEDIUM,
            data={
                'vehicle_type': vehicle_type,
                'confidence': confidence,
                'count': count
            },
            tenant_id=tenant_id
        )
    
    def trigger_person_alert(
        self,
        camera_id: int,
        camera_name: str,
        confidence: float = 0.8,
        count: int = 1,
        tenant_id: Optional[int] = None
    ) -> Alert:
        """Déclencher une alerte personne"""
        return self.create_alert(
            camera_id=camera_id,
            camera_name=camera_name,
            alert_type=AlertType.PERSON,
            message=f"{count} personne(s) détectée(s) (confiance: {confidence:.1%})",
            severity=AlertSeverity.MEDIUM,
            data={
                'confidence': confidence,
                'count': count
            },
            tenant_id=tenant_id
        )
    
    def trigger_face_alert(
        self,
        camera_id: int,
        camera_name: str,
        name: Optional[str] = None,
        confidence: float = 0.8,
        tenant_id: Optional[int] = None
    ) -> Alert:
        """Déclencher une alerte reconnaissance faciale"""
        message = f"Visage détecté"
        if name:
            message += f": {name}"
        message += f" (confiance: {confidence:.1%})"
        
        return self.create_alert(
            camera_id=camera_id,
            camera_name=camera_name,
            alert_type=AlertType.FACE,
            message=message,
            severity=AlertSeverity.HIGH,
            data={
                'name': name,
                'confidence': confidence
            },
            tenant_id=tenant_id
        )
    
    def trigger_alarm_alert(
        self,
        camera_id: int,
        camera_name: str,
        reason: str = "Alarme d?clench?e",
        tenant_id: Optional[int] = None,
    ) -> Alert:
        """D?clencher une alerte d'alarme"""
        return self.create_alert(
            camera_id=camera_id,
            camera_name=camera_name,
            alert_type=AlertType.ALARM,
            message=reason,
            severity=AlertSeverity.CRITICAL,
            tenant_id=tenant_id,
        )
    def get_active_alerts(self) -> List[Dict]:
        """Récupérer les alertes actives"""
        with self._lock:
            # If memory cache is empty, load active alerts from database
            if not self.active_alerts:
                db = next(get_db())
                try:
                    db_alerts = db.query(AlertModel).filter(AlertModel.is_acknowledged == False).all()
                    for db_alert in db_alerts:
                        # Create Alert object from DB data with safe enum handling
                        try:
                            alert_type = AlertType(db_alert.rule_type)
                        except ValueError:
                            # Fallback for unknown alert types
                            alert_type = AlertType.SYSTEM

                        try:
                            severity = AlertSeverity(db_alert.severity)
                        except ValueError:
                            # Fallback for unknown severities
                            severity = AlertSeverity.MEDIUM

                        alert = Alert(
                            camera_id=db_alert.camera_id,
                            camera_name='',  # Would need join
                            alert_type=alert_type,
                            message=db_alert.message,
                            severity=severity,
                            data=db_alert.extra_data,
                            tenant_id=db_alert.tenant_id
                        )
                        alert.id = db_alert.id
                        alert.timestamp = db_alert.timestamp
                        alert.acknowledged = db_alert.is_acknowledged
                        alert.acknowledged_at = db_alert.acknowledged_at
                        alert.acknowledged_by = db_alert.acknowledged_by
                        self.active_alerts[alert.id] = alert
                finally:
                    db.close()

            return [alert.to_dict() for alert in self.active_alerts.values()]
    
    def get_alert_history(self, limit: int = 100, camera_id: Optional[int] = None) -> List[Dict]:
        """
        Récupérer l'historique des alertes.

        Args:
            limit: Nombre maximum d'alertes à retourner
            camera_id: Filtrer par ID caméra (optionnel)

        Returns:
            Liste d'alertes
        """
        db = next(get_db())
        try:
            query = db.query(AlertModel).order_by(AlertModel.timestamp.desc())
            if camera_id:
                query = query.filter(AlertModel.camera_id == camera_id)
            if limit:
                query = query.limit(limit)

            db_alerts = query.all()

            # Convert to dict format compatible with existing API
            alerts = []
            for db_alert in db_alerts:
                alert_dict = {
                    'id': db_alert.id,
                    'tenant_id': db_alert.tenant_id,
                    'camera_id': db_alert.camera_id,
                    'camera_name': '',  # Would need to join with Camera table
                    'type': db_alert.rule_type,
                    'message': db_alert.message,
                    'severity': db_alert.severity,
                    'timestamp': db_alert.timestamp.isoformat(),
                    'acknowledged': db_alert.is_acknowledged,
                    'acknowledged_at': db_alert.acknowledged_at.isoformat() if db_alert.acknowledged_at else None,
                    'acknowledged_by': db_alert.acknowledged_by,
                    'data': db_alert.extra_data or {}
                }
                alerts.append(alert_dict)

            return alerts
        finally:
            db.close()
    
    def get_alerts_by_type(self, alert_type: AlertType) -> List[Dict]:
        """Récupérer les alertes d'un type spécifique"""
        db = next(get_db())
        try:
            db_alerts = db.query(AlertModel).filter(AlertModel.rule_type == alert_type.value).order_by(AlertModel.timestamp.desc()).all()

            # Convert to dict format compatible with existing API
            alerts = []
            for db_alert in db_alerts:
                alert_dict = {
                    'id': db_alert.id,
                    'tenant_id': db_alert.tenant_id,
                    'camera_id': db_alert.camera_id,
                    'camera_name': '',  # Would need to join with Camera table
                    'type': db_alert.rule_type,
                    'message': db_alert.message,
                    'severity': db_alert.severity,
                    'timestamp': db_alert.timestamp.isoformat(),
                    'acknowledged': db_alert.is_acknowledged,
                    'acknowledged_at': db_alert.acknowledged_at.isoformat() if db_alert.acknowledged_at else None,
                    'acknowledged_by': db_alert.acknowledged_by,
                    'data': db_alert.extra_data or {}
                }
                alerts.append(alert_dict)

            return alerts
        finally:
            db.close()
    
    def acknowledge_alert(self, alert_id: int, acknowledged_by: Optional[int] = None) -> bool:
        """
        Reconnaître une alerte.

        Args:
            alert_id: ID de l'alerte

        Returns:
            True si succès
        """
        # Update database
        db = next(get_db())
        try:
            db_alert = db.query(AlertModel).filter(AlertModel.id == alert_id).first()
            if db_alert:
                db_alert.is_acknowledged = True
                db_alert.acknowledged_at = datetime.utcnow()
                if acknowledged_by is not None:
                    db_alert.acknowledged_by = acknowledged_by
                db.commit()
            else:
                db.close()
                return False
        finally:
            db.close()

        with self._lock:
            if alert_id in self.active_alerts:
                alert = self.active_alerts[alert_id]
                alert.acknowledged = True
                alert.acknowledged_at = datetime.utcnow()
                if acknowledged_by is not None:
                    alert.acknowledged_by = acknowledged_by
                del self.active_alerts[alert_id]

                logger.info(f"Alerte {alert_id} reconnaissable")
                try:
                    from vms.backend.routers.ws import broadcast_api_event_sync

                    payload = alert.to_dict()
                    payload["server_ts"] = datetime.utcnow().isoformat()
                    broadcast_api_event_sync(
                        "alert_acknowledged",
                        payload,
                        channel="alerts",
                    )
                except Exception:
                    logger.debug("Impossible de diffuser l'acquittement sur /api/ws", exc_info=True)
                return True
            return False
    
    def clear_alerts(self, camera_id: Optional[int] = None) -> int:
        """
        Effacer les alertes.

        Args:
            camera_id: Filtrer par caméra (optionnel)

        Returns:
            Nombre d'alertes effacées
        """
        # Clear from database
        db = next(get_db())
        try:
            query = db.query(AlertModel).filter(AlertModel.is_acknowledged == False)
            if camera_id:
                query = query.filter(AlertModel.camera_id == camera_id)
            deleted_count = query.delete()
            db.commit()
        finally:
            db.close()

        with self._lock:
            if camera_id:
                alerts_to_remove = [aid for aid, a in self.active_alerts.items() if a.camera_id == camera_id]
            else:
                alerts_to_remove = list(self.active_alerts.keys())

            for alert_id in alerts_to_remove:
                del self.active_alerts[alert_id]

        total_cleared = deleted_count + len(alerts_to_remove)
        logger.info(f"{total_cleared} alerte(s) effacées ({deleted_count} DB + {len(alerts_to_remove)} mémoire)")
        return total_cleared

    def cleanup_old_alerts(self, days: Optional[int] = None) -> int:
        """
        Nettoyer les anciennes alertes selon la politique de rétention.

        Args:
            days: Nombre de jours de rétention (défaut: config ALERT_RETENTION_DAYS)

        Returns:
            Nombre d'alertes supprimées
        """
        retention_days = days or settings.ALERT_RETENTION_DAYS
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

        db = next(get_db())
        try:
            # Delete old acknowledged alerts
            deleted_count = db.query(AlertModel).filter(
                AlertModel.timestamp < cutoff_date,
                AlertModel.is_acknowledged == True
            ).delete()
            db.commit()

            logger.info(f"Nettoyage: {deleted_count} alertes anciennes supprimées (rétention: {retention_days} jours)")
            return deleted_count
        finally:
            db.close()
    
    def get_statistics(self) -> Dict:
        """
        Récupérer les statistiques d'alertes.

        Returns:
            Dict avec statistiques
        """
        db = next(get_db())
        try:
            # Get total alerts count
            total_alerts = db.query(AlertModel).count()

            # Get active alerts count (not acknowledged)
            active_count = db.query(AlertModel).filter(AlertModel.is_acknowledged == False).count()

            # Get stats by type
            by_type_result = db.query(AlertModel.rule_type, func.count(AlertModel.id)).group_by(AlertModel.rule_type).all()
            by_type = {row[0]: row[1] for row in by_type_result}

            # Get stats by severity
            by_severity_result = db.query(AlertModel.severity, func.count(AlertModel.id)).group_by(AlertModel.severity).all()
            by_severity = {row[0]: row[1] for row in by_severity_result}

            return {
                'total_alerts': total_alerts,
                'active_alerts': active_count,
                'by_type': by_type,
                'by_severity': by_severity
            }
        finally:
            db.close()

    def _dispatch_callback(
        self,
        *,
        callback_id: int,
        callback: Callable[[Alert], Any],
        callback_loop: Optional[asyncio.AbstractEventLoop],
        alert: Alert,
    ) -> None:
        result = callback(alert)
        if not inspect.isawaitable(result):
            return

        target_loop = callback_loop
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if target_loop is not None and target_loop.is_running():
            if running_loop is target_loop:
                target_loop.create_task(result)
            else:
                asyncio.run_coroutine_threadsafe(result, target_loop)
            return

        if running_loop is not None and running_loop.is_running():
            running_loop.create_task(result)
            return

        if hasattr(result, "close"):
            result.close()
        logger.warning(
            "Async alert callback %s dropped because no running event loop was available",
            callback_id,
        )


# Instance globale du service
_alert_service: Optional[AlertService] = None


def get_alert_service() -> AlertService:
    """Obtenir l'instance du service d'alertes"""
    global _alert_service
    if _alert_service is None:
        _alert_service = AlertService()
    return _alert_service
