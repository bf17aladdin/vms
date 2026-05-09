# vms/backend/services/entry_exit_scenarios.py - Real entry/exit detection (Sprint 4)

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)

class EntryExitScenario(str, Enum):
    """Types de scénarios d'entrée/sortie"""
    NORMAL_ENTRY = "normal_entry"
    NORMAL_EXIT = "normal_exit"
    TAILGATE_ENTRY = "tailgate_entry"  # Entrée en groupe suspecte
    FORCED_ENTRY = "forced_entry"       # Tentative d'effraction
    LONG_STAY = "long_stay"             # Séjour anormalement long
    UNAUTHORIZED_HOURS = "unauthorized_hours"  # Accès en dehors des heures

class EntryExitScenarioManager:
    """
    Détecte et rapporte les scénarios d'entrée/sortie anormaux.
    Intégration avec détection véhicules et personnel.
    
    **Sprint 4 Deliverable**: Real Entry/Exit Scenarios
    """
    
    # Thresholds configurables
    TAILGATE_WINDOW_SECONDS = 5  # Si 2+ personnes en 5 sec
    LONG_STAY_MINUTES = 480  # 8 heures
    AUTHORIZED_HOURS = ("06:00", "22:00")  # Par défaut
    
    def __init__(self):
        self.recent_entries: Dict[int, List[dict]] = {}  # camera_id -> events
        self.active_personnel: Dict[int, dict] = {}  # personnel_id -> entry_data
        self.active_vehicles: Dict[str, dict] = {}  # plate -> entry_data
    
    def detect_personnel_entry(
        self,
        personnel_id: int,
        camera_id: int,
        confidence: float,
        authorized_hours: tuple = None
    ) -> Dict:
        """
        Détecter entrée personnel avec validation scénarios
        
        Returns:
            {
                'scenario': EntryExitScenario,
                'confidence': float,
                'alerts': [...]
            }
        """
        if authorized_hours is None:
            authorized_hours = self.AUTHORIZED_HOURS
        
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        
        # Vérifier horaire autorisé
        start_h, end_h = authorized_hours
        if not (start_h <= current_time <= end_h):
            logger.warning(f"⚠️ Personnel {personnel_id} entry outside authorized hours")
            return {
                'scenario': EntryExitScenario.UNAUTHORIZED_HOURS,
                'confidence': confidence,
                'alerts': ['Entry outside authorized hours'],
                'timestamp': now.isoformat()
            }
        
        # Enregistrer entrée
        if camera_id not in self.recent_entries:
            self.recent_entries[camera_id] = []
        
        self.recent_entries[camera_id].append({
            'personnel_id': personnel_id,
            'timestamp': now,
            'confidence': confidence
        })
        
        # Pruner old entries (> 10 sec)
        cutoff = now - timedelta(seconds=10)
        self.recent_entries[camera_id] = [
            e for e in self.recent_entries[camera_id]
            if e['timestamp'] > cutoff
        ]
        
        # Vérifier tailgate (2+ personnes proches temporellement)
        if len(self.recent_entries[camera_id]) >= 2:
            first_entry = self.recent_entries[camera_id][0]
            time_diff = (now - first_entry['timestamp']).total_seconds()
            if time_diff <= self.TAILGATE_WINDOW_SECONDS:
                logger.info(f"🚨 Tailgate detected: {len(self.recent_entries[camera_id])} people in {time_diff}s")
                return {
                    'scenario': EntryExitScenario.TAILGATE_ENTRY,
                    'confidence': confidence,
                    'alerts': [f'Tailgate: {len(self.recent_entries[camera_id])} people in {time_diff}s'],
                    'timestamp': now.isoformat()
                }
        
        # Enregistrer comme entrée normale
        self.active_personnel[personnel_id] = {
            'entry_time': now,
            'camera_id': camera_id,
            'confidence': confidence
        }
        
        logger.info(f"✓ Personnel {personnel_id} normal entry (confidence: {confidence})")
        return {
            'scenario': EntryExitScenario.NORMAL_ENTRY,
            'confidence': confidence,
            'alerts': [],
            'timestamp': now.isoformat()
        }
    
    def detect_personnel_exit(self, personnel_id: int, camera_id: int) -> Dict:
        """Détecter sortie personnel"""
        now = datetime.now()
        
        if personnel_id not in self.active_personnel:
            logger.warning(f"❓ Exit detected for personnel {personnel_id} (no matching entry)")
            return {
                'scenario': EntryExitScenario.NORMAL_EXIT,
                'alerts': ['Exit without entry record'],
                'timestamp': now.isoformat()
            }
        
        entry_data = self.active_personnel[personnel_id]
        stay_duration = (now - entry_data['entry_time']).total_seconds() / 60
        
        # Vérifier long stay
        if stay_duration > self.LONG_STAY_MINUTES:
            logger.warning(f"⚠️ Personnel {personnel_id} long stay: {stay_duration:.0f} min")
            del self.active_personnel[personnel_id]
            return {
                'scenario': EntryExitScenario.LONG_STAY,
                'stay_duration_minutes': round(stay_duration, 1),
                'alerts': [f'Long stay: {stay_duration:.0f} minutes'],
                'timestamp': now.isoformat()
            }
        
        del self.active_personnel[personnel_id]
        logger.info(f"✓ Personnel {personnel_id} normal exit (stay: {stay_duration:.0f} min)")
        return {
            'scenario': EntryExitScenario.NORMAL_EXIT,
            'stay_duration_minutes': round(stay_duration, 1),
            'alerts': [],
            'timestamp': now.isoformat()
        }
    
    def detect_vehicle_entry(self, plate: str, camera_id: int, confidence: float) -> Dict:
        """Détecter entrée véhicule"""
        now = datetime.now()
        
        # Vérifier si véhicule déjà présent (accès répété?)
        if plate in self.active_vehicles:
            logger.warning(f"⚠️ Vehicle {plate} reentry detected (already inside)")
            # Pourrait indiquer une tentative d'effraction
        
        self.active_vehicles[plate] = {
            'entry_time': now,
            'camera_id': camera_id,
            'confidence': confidence
        }
        
        logger.info(f"✓ Vehicle {plate} entry (confidence: {confidence})")
        return {
            'scenario': EntryExitScenario.NORMAL_ENTRY,
            'confidence': confidence,
            'alerts': [],
            'timestamp': now.isoformat()
        }
    
    def detect_vehicle_exit(self, plate: str, camera_id: int) -> Dict:
        """Détecter sortie véhicule"""
        now = datetime.now()
        
        if plate not in self.active_vehicles:
            logger.warning(f"❓ Vehicle {plate} exit without entry")
            return {
                'scenario': EntryExitScenario.NORMAL_EXIT,
                'alerts': ['Exit without entry record'],
                'timestamp': now.isoformat()
            }
        
        entry_data = self.active_vehicles[plate]
        stay_duration = (now - entry_data['entry_time']).total_seconds() / 60
        
        del self.active_vehicles[plate]
        logger.info(f"✓ Vehicle {plate} exit (stay: {stay_duration:.0f} min)")
        return {
            'scenario': EntryExitScenario.NORMAL_EXIT,
            'stay_duration_minutes': round(stay_duration, 2),
            'alerts': [],
            'timestamp': now.isoformat()
        }
    
    def get_active_status(self) -> Dict:
        """Retourner état actuel des entrées"""
        return {
            'active_personnel': len(self.active_personnel),
            'active_vehicles': len(self.active_vehicles),
            'personnel': list(self.active_personnel.keys()),
            'vehicles': list(self.active_vehicles.keys())
        }

# Instance globale
_scenario_manager: Optional[EntryExitScenarioManager] = None

def get_scenario_manager() -> EntryExitScenarioManager:
    """Get or create global scenario manager"""
    global _scenario_manager
    if _scenario_manager is None:
        _scenario_manager = EntryExitScenarioManager()
    return _scenario_manager
