# vms/backend/services/vehicle_entry_service.py - Service Entrées/Sorties Véhicules

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date, timezone
from sqlalchemy.orm import Session, aliased
from sqlalchemy import desc, func, or_
import logging
import numpy as np

from ..models import VehicleEntry, Camera, Zone, VehicleDetection, ZoneOccupancy
from ..schemas import VehicleEntryCreate, VehicleEntryUpdate

logger = logging.getLogger(__name__)

class VehicleEntryService:
    """Service pour gestion des entrées/sorties véhicules"""
    
    @staticmethod
    def create_entry(db: Session, vehicle_data: VehicleEntryCreate) -> VehicleEntry:
        """
        Créer nouvelle entrée véhicule
        
        Les véhicules doivent avoir:
        - license_plate: plaque d'immatriculation (normalisée MAJUSCULES)
        - entry_camera_id: caméra d'entrée
        - entry_time: datetime d'entrée
        - entry_confidence: score de détection YOLO (0-1)
        """
        entry = VehicleEntry(
            license_plate=vehicle_data.license_plate.upper(),
            vehicle_type=vehicle_data.vehicle_type,
            brand=vehicle_data.brand,
            model=vehicle_data.model,
            color=vehicle_data.color,
            entry_camera_id=vehicle_data.entry_camera_id,
            entry_time=vehicle_data.entry_time,
            entry_confidence=vehicle_data.entry_confidence,
            status="active",
        )
        
        db.add(entry)
        db.commit()
        db.refresh(entry)
        logger.info(f"✓ Entrée véhicule: {entry.license_plate} (caméra: {entry.entry_camera_id})")
        return entry
    
    @staticmethod
    def log_exit(db: Session, entry_id: int,
                exit_camera_id: int, exit_confidence: float) -> Optional[VehicleEntry]:
        """
        Enregistrer sortie d'un véhicule
        
        Calcule automatiquement:
        - exit_time: datetime actuel
        - duration_minutes: temps de séjour
        - status: passe à "exited"
        """
        entry = db.query(VehicleEntry).filter_by(id=entry_id).first()
        
        if entry:
            entry.exit_camera_id = exit_camera_id
            # Keep timezone consistency with entry_time if it is timezone-aware.
            if entry.entry_time is not None and entry.entry_time.tzinfo is not None:
                entry.exit_time = datetime.now(timezone.utc)
            else:
                entry.exit_time = datetime.utcnow()
            entry.exit_confidence = exit_confidence
            entry.status = "exited"
            
            # Calculer durée de séjour
            if entry.exit_time and entry.entry_time:
                delta = entry.exit_time - entry.entry_time
                entry.duration_minutes = int(delta.total_seconds() / 60)
            
            db.commit()
            db.refresh(entry)
            logger.info(f"✓ Sortie véhicule: {entry.license_plate} (durée: {entry.duration_minutes}min)")
        
        return entry
    
    @staticmethod
    def get_entry(db: Session, entry_id: int) -> Optional[VehicleEntry]:
        """Récupérer une entrée par ID"""
        return db.query(VehicleEntry).filter_by(id=entry_id).first()

    @staticmethod
    def delete_entry(db: Session, entry_id: int) -> bool:
        """Supprimer une entrée véhicule en détachant les références liées."""
        entry = db.query(VehicleEntry).filter_by(id=entry_id).first()
        if not entry:
            return False

        # Keep detection/occupancy history but remove FK pointers to this entry.
        db.query(VehicleDetection).filter(
            VehicleDetection.vehicle_entry_id == entry_id
        ).update(
            {VehicleDetection.vehicle_entry_id: None},
            synchronize_session=False,
        )
        db.query(ZoneOccupancy).filter(
            ZoneOccupancy.vehicle_entry_id == entry_id
        ).update(
            {ZoneOccupancy.vehicle_entry_id: None},
            synchronize_session=False,
        )

        db.delete(entry)
        db.commit()
        return True
    
    @staticmethod
    def get_active_vehicles(db: Session, camera_id: Optional[int] = None) -> List[VehicleEntry]:
        """Lister véhicules actuellement présents (status=active)"""
        query = db.query(VehicleEntry).filter_by(status="active")
        
        if camera_id:
            query = query.filter_by(entry_camera_id=camera_id)
        
        return query.order_by(desc(VehicleEntry.entry_time)).all()

    @staticmethod
    def get_history(
        db: Session,
        plate: Optional[str] = None,
        camera_id: Optional[int] = None,
        zone_id: Optional[int] = None,
        status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Filtered history for vehicle entry/exit dashboard."""
        entry_camera = aliased(Camera)
        exit_camera = aliased(Camera)
        entry_zone = aliased(Zone)
        exit_zone = aliased(Zone)

        query = (
            db.query(VehicleEntry, entry_camera, exit_camera, entry_zone, exit_zone)
            .outerjoin(entry_camera, VehicleEntry.entry_camera_id == entry_camera.id)
            .outerjoin(exit_camera, VehicleEntry.exit_camera_id == exit_camera.id)
            .outerjoin(entry_zone, entry_camera.zone_id == entry_zone.id)
            .outerjoin(exit_zone, exit_camera.zone_id == exit_zone.id)
        )

        plate_norm = str(plate or "").strip().upper()
        if plate_norm:
            query = query.filter(VehicleEntry.license_plate.ilike(f"%{plate_norm}%"))

        if camera_id is not None:
            query = query.filter(
                or_(
                    VehicleEntry.entry_camera_id == camera_id,
                    VehicleEntry.exit_camera_id == camera_id,
                )
            )

        if zone_id is not None:
            query = query.filter(
                or_(
                    entry_camera.zone_id == zone_id,
                    exit_camera.zone_id == zone_id,
                )
            )

        if status:
            query = query.filter(VehicleEntry.status == status)

        if date_from is not None:
            query = query.filter(VehicleEntry.entry_time >= date_from)
        if date_to is not None:
            query = query.filter(VehicleEntry.entry_time <= date_to)

        total = int(query.count())
        rows = (
            query.order_by(desc(VehicleEntry.entry_time))
            .offset(max(0, int(skip)))
            .limit(max(1, int(limit)))
            .all()
        )

        items: List[Dict[str, Any]] = []
        for entry, e_cam, x_cam, e_zone, x_zone in rows:
            items.append(
                {
                    "id": entry.id,
                    "license_plate": entry.license_plate,
                    "vehicle_type": entry.vehicle_type,
                    "brand": entry.brand,
                    "model": entry.model,
                    "color": entry.color,
                    "entry_camera_id": entry.entry_camera_id,
                    "entry_camera_name": getattr(e_cam, "name", None),
                    "entry_zone_id": getattr(e_cam, "zone_id", None),
                    "entry_zone_name": getattr(e_zone, "name", None),
                    "exit_camera_id": entry.exit_camera_id,
                    "exit_camera_name": getattr(x_cam, "name", None),
                    "exit_zone_id": getattr(x_cam, "zone_id", None),
                    "exit_zone_name": getattr(x_zone, "name", None),
                    "entry_time": entry.entry_time.isoformat() if entry.entry_time else None,
                    "exit_time": entry.exit_time.isoformat() if entry.exit_time else None,
                    "duration_minutes": entry.duration_minutes,
                    "entry_confidence": float(entry.entry_confidence or 0.0),
                    "exit_confidence": float(entry.exit_confidence or 0.0)
                    if entry.exit_confidence is not None
                    else None,
                    "status": entry.status,
                    "notes": entry.notes,
                }
            )

        return {"total": total, "items": items}

    @staticmethod
    def get_day_summary(
        db: Session,
        target_date: Optional[date] = None,
        camera_id: Optional[int] = None,
        zone_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        day = target_date or date.today()
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)

        payload = VehicleEntryService.get_history(
            db=db,
            camera_id=camera_id,
            zone_id=zone_id,
            date_from=start,
            date_to=end,
            skip=0,
            limit=10000,
        )
        rows = payload["items"]
        entries = len(rows)
        exits = sum(1 for row in rows if row.get("status") == "exited")
        active = sum(1 for row in rows if row.get("status") == "active")
        unique_plates = len(
            {str(row.get("license_plate") or "").upper() for row in rows if row.get("license_plate")}
        )

        durations = [
            int(row["duration_minutes"])
            for row in rows
            if row.get("duration_minutes") is not None
        ]
        avg_stay = float(np.mean(durations)) if durations else None

        return {
            "date": day.isoformat(),
            "total_entries": entries,
            "total_exits": exits,
            "currently_active": active,
            "unique_plates": unique_plates,
            "avg_stay_minutes": avg_stay,
        }

    @staticmethod
    def get_vehicle_history(db: Session, license_plate: str,
                           days: int = 30) -> List[VehicleEntry]:
        """
        Historique complet d'une plaque (entries + exits)
        
        Retourne tous les passages dans les derniers N jours
        """
        threshold_date = datetime.utcnow() - timedelta(days=days)
        
        return (db.query(VehicleEntry)
                .filter_by(license_plate=license_plate.upper())
                .filter(VehicleEntry.entry_time >= threshold_date)
                .order_by(desc(VehicleEntry.entry_time))
                .all())
    
    @staticmethod
    def find_or_create_entry(db: Session, license_plate: str,
                            camera_id: int) -> Optional[VehicleEntry]:
        """
        Chercher entrée active pour plaque, créer si pas existante
        
        Utilisé pour matching YOLO tracker ↔ VehicleEntry
        """
        # Chercher entrée active
        entry = (db.query(VehicleEntry)
                .filter_by(license_plate=license_plate.upper(), status="active")
                .order_by(desc(VehicleEntry.entry_time))
                .first())
        
        return entry
    
    # ========== STATISTIQUES ==========
    
    @staticmethod
    def get_daily_summary(db: Session, camera_id: Optional[int] = None) -> Dict:
        """Résumé quotidien des véhicules"""
        today = date.today()
        
        query = db.query(VehicleEntry).filter(
            func.date(VehicleEntry.entry_time) == today
        )
        
        if camera_id:
            query = query.filter_by(entry_camera_id=camera_id)
        
        entries = query.all()
        
        # Comptes
        total_entries = len(entries)
        total_exits = sum(1 for e in entries if e.status == "exited")
        currently_active = sum(1 for e in entries if e.status == "active")
        
        # Par type de véhicule
        by_type = {}
        for e in entries:
            vtype = e.vehicle_type or "unknown"
            by_type[vtype] = by_type.get(vtype, 0) + 1
        
        # Durée moyenne
        exited = [e for e in entries if e.duration_minutes]
        avg_stay = None
        if exited:
            avg_stay = np.mean([e.duration_minutes for e in exited])
        
        return {
            "date": today.isoformat(),
            "total_entries": total_entries,
            "total_exits": total_exits,
            "currently_active": currently_active,
            "unique_plates": len(set(e.license_plate for e in entries)),
            "by_type": by_type,
            "avg_stay_minutes": avg_stay,
        }
    
    @staticmethod
    def get_plate_statistics(db: Session, days: int = 30, limit: int = 20) -> List[Dict]:
        """
        Top N plaques les plus fréquentes
        
        Retourne: [{plate, count, last_seen, avg_confidence}, ...]
        """
        threshold_date = datetime.utcnow() - timedelta(days=days)
        
        results = (db.query(
                VehicleEntry.license_plate,
                func.count(VehicleEntry.id).label("count"),
                func.max(VehicleEntry.entry_time).label("last_seen"),
                func.avg(VehicleEntry.entry_confidence).label("avg_confidence"),
            )
            .filter(VehicleEntry.entry_time >= threshold_date)
            .group_by(VehicleEntry.license_plate)
            .order_by(desc(func.count(VehicleEntry.id)))
            .limit(limit)
            .all())
        
        return [
            {
                "license_plate": row[0],
                "count": row[1],
                "last_seen": row[2].isoformat() if row[2] else None,
                "avg_confidence": float(row[3]) if row[3] else 0.0,
            }
            for row in results
        ]
    
    @staticmethod
    def get_vehicle_type_statistics(db: Session, days: int = 30) -> Dict[str, int]:
        """Statistiques par type de véhicule"""
        threshold_date = datetime.utcnow() - timedelta(days=days)
        
        results = (db.query(
                VehicleEntry.vehicle_type,
                func.count(VehicleEntry.id).label("count")
            )
            .filter(VehicleEntry.entry_time >= threshold_date)
            .group_by(VehicleEntry.vehicle_type)
            .all())
        
        return {
            (row[0] or "unknown"): row[1]
            for row in results
        }
    
    @staticmethod
    def get_peak_hours(db: Session, days: int = 30) -> Dict[int, int]:
        """Heure de pointe (heure → nombre d'entrées)"""
        threshold_date = datetime.utcnow() - timedelta(days=days)
        
        results = (db.query(
                func.extract('hour', VehicleEntry.entry_time).label("hour"),
                func.count(VehicleEntry.id).label("count")
            )
            .filter(VehicleEntry.entry_time >= threshold_date)
            .group_by(func.extract('hour', VehicleEntry.entry_time))
            .all())
        
        return {
            int(row[0]): row[1]
            for row in results
        }
    
    @staticmethod
    def get_average_stay_analysis(db: Session, days: int = 30) -> Dict:
        """Analyse du temps moyen de séjour"""
        threshold_date = datetime.utcnow() - timedelta(days=days)
        
        exited = (db.query(VehicleEntry.duration_minutes)
                 .filter(VehicleEntry.exit_time.isnot(None))
                 .filter(VehicleEntry.entry_time >= threshold_date)
                 .all())
        
        if not exited:
            return {
                "min": None,
                "avg": None,
                "max": None,
                "median": None,
            }
        
        durations = [row[0] for row in exited if row[0] is not None]
        
        return {
            "min": min(durations),
            "avg": float(np.mean(durations)),
            "max": max(durations),
            "median": float(np.median(durations)),
            "sample_size": len(durations),
        }
    
    @staticmethod
    def export_vehicle_log(db: Session, start_date: datetime, end_date: datetime,
                          format: str = "json") -> List[Dict]:
        """
        Exporter logs véhicules pour période donnée
        
        Args:
            format: "json" ou "csv"
        
        Retourne list of dicts prêt pour serialize
        """
        entries = (db.query(VehicleEntry)
                  .filter(VehicleEntry.entry_time >= start_date)
                  .filter(VehicleEntry.entry_time <= end_date)
                  .order_by(VehicleEntry.entry_time)
                  .all())
        
        result = []
        for e in entries:
            result.append({
                "id": e.id,
                "license_plate": e.license_plate,
                "vehicle_type": e.vehicle_type,
                "brand": e.brand,
                "model": e.model,
                "color": e.color,
                "entry_time": e.entry_time.isoformat(),
                "exit_time": e.exit_time.isoformat() if e.exit_time else None,
                "duration_minutes": e.duration_minutes,
                "entry_confidence": e.entry_confidence,
                "exit_confidence": e.exit_confidence,
                "status": e.status,
            })
        
        return result
