# vms/backend/schemas.py - Schémas Pydantic pour validation et sérialisation

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

# ============= ENUMS =============


def _validate_normalized_points(value: Optional[List[List[float]]]) -> Optional[List[List[float]]]:
    if value is None:
        return value
    for point in value:
        if len(point) != 2:
            raise ValueError("each point must contain exactly two values [x, y]")
        x, y = float(point[0]), float(point[1])
        if x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0:
            raise ValueError("point coordinates must be normalized between 0.0 and 1.0")
    return value


def _validate_hhmm(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    if len(value) != 5 or value[2] != ":":
        raise ValueError("time must be in HH:MM format")
    hh, mm = value.split(":")
    if not (hh.isdigit() and mm.isdigit()):
        raise ValueError("time must be in HH:MM format")
    if int(hh) < 0 or int(hh) > 23 or int(mm) < 0 or int(mm) > 59:
        raise ValueError("time must be in HH:MM format")
    return value

class EventTypeEnum(str, Enum):
    """Types d'événements"""
    MOTION = "motion"
    OBJECT = "object"
    PERSON = "person"
    VEHICLE = "vehicle"
    ALARM = "alarm"


class SeverityEnum(str, Enum):
    """Niveaux de sévérité"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class LogLevelEnum(str, Enum):
    """Niveaux de log"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class PersonnelCategoryEnum(str, Enum):
    """Legacy personnel categories (kept for compatibility)."""
    OFFICIER = "officier"
    SOUS_OFFICIER = "sous_officier"
    SOLDAT = "soldat"
    SOLDAT_INVITE = "soldat_invite"
    CIVIL = "civil"


class VehicleTypeEnum(str, Enum):
    """Type de véhicule"""
    MILITAIRE = "militaire"
    CIVILE = "civile"
    INCONNU = "inconnu"


class VehicleStateEnum(str, Enum):
    """État du véhicule"""
    ACTIF = "actif"
    HORS_SERVICE = "hors_service"
    MAINTENANCE = "maintenance"


class SecurityRuleTypeEnum(str, Enum):
    ZONE = "zone"
    LINE = "line"


class SecurityDirectionModeEnum(str, Enum):
    BOTH = "both"
    ENTRY_ONLY = "entry_only"
    EXIT_ONLY = "exit_only"


class SecurityScheduleModeEnum(str, Enum):
    ALWAYS = "always"
    NIGHT_ONLY = "night_only"
    CUSTOM_WINDOW = "custom_window"


class SecurityObjectTypeEnum(str, Enum):
    PERSON = "person"
    VEHICLE = "vehicle"
    BOTH = "both"


# ============= USER SCHEMAS =============

class UserRoleEnum(str, Enum):
    """Role applicatif utilisateur."""
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    OPERATOR = "operator"
    VIEWER = "viewer"


class UserBase(BaseModel):
    """Schema de base pour utilisateur"""
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: UserRoleEnum = UserRoleEnum.OPERATOR
    is_active: bool = True


class UserCreate(UserBase):
    """Schema pour creer un utilisateur"""
    password: str = Field(..., min_length=8)
    tenant_id: Optional[int] = None
    is_admin: Optional[bool] = None


class UserUpdate(BaseModel):
    """Schema pour mettre a jour un utilisateur"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[UserRoleEnum] = None
    is_admin: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)
    is_active: Optional[bool] = None


class UserOut(UserBase):
    """Schema pour retourner un utilisateur"""
    id: int
    tenant_id: Optional[int] = None
    is_admin: bool
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    """Schema pour login"""
    username: str
    password: str


# ============= TOKEN SCHEMAS =============

class Token(BaseModel):
    """Schéma de token JWT"""
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TokenData(BaseModel):
    """Données du token"""
    username: Optional[str] = None
    user_id: Optional[int] = None


# ============= SITE SCHEMAS =============

class SiteBase(BaseModel):
    """Schéma de base pour un site."""
    name: str = Field(..., min_length=1, max_length=120)
    code: Optional[str] = Field(None, max_length=40)
    description: Optional[str] = None
    is_active: bool = True


class SiteCreate(SiteBase):
    """Schéma pour créer un site."""
    pass


class SiteUpdate(BaseModel):
    """Schéma pour mettre à jour un site."""
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    code: Optional[str] = Field(None, max_length=40)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SiteOut(SiteBase):
    """Schéma pour retourner un site."""
    id: int
    tenant_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ============= ZONE SCHEMAS =============

class ZoneBase(BaseModel):
    """Schéma de base pour zone"""
    site_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    points: Optional[List[List[float]]] = None  # [[x1,y1], [x2,y2], ...]
    is_active: bool = True
    zone_type: str = "custom"
    is_blocked: bool = False
    block_reason: Optional[str] = None
    motion_detection_enabled: bool = True
    object_detection_enabled: bool = True
    sensitivity: int = Field(50, ge=0, le=100)


class ZoneCreate(ZoneBase):
    """Schéma pour créer une zone"""
    camera_id: int


class ZoneUpdate(BaseModel):
    """Schéma pour mettre à jour une zone"""
    site_id: Optional[int] = None
    camera_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    points: Optional[List[List[float]]] = None
    is_active: Optional[bool] = None
    zone_type: Optional[str] = None
    is_blocked: Optional[bool] = None
    block_reason: Optional[str] = None
    motion_detection_enabled: Optional[bool] = None
    object_detection_enabled: Optional[bool] = None
    sensitivity: Optional[int] = Field(None, ge=0, le=100)


class ZoneOut(ZoneBase):
    """Schéma pour retourner une zone"""
    id: int
    tenant_id: Optional[int] = None
    camera_id: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    model_config = ConfigDict(from_attributes=True)


# ============= SECURITY CONFIG RULE SCHEMAS =============

class SecurityRuleBase(BaseModel):
    """Schéma de base pour une règle de sécurité zone/ligne."""
    site_id: Optional[int] = None
    camera_id: Optional[int] = None
    zone_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None
    rule_type: SecurityRuleTypeEnum = SecurityRuleTypeEnum.ZONE
    points: List[List[float]] = Field(default_factory=list)
    direction_mode: SecurityDirectionModeEnum = SecurityDirectionModeEnum.BOTH
    schedule_mode: SecurityScheduleModeEnum = SecurityScheduleModeEnum.ALWAYS
    active_from: Optional[str] = Field(None, max_length=5)
    active_to: Optional[str] = Field(None, max_length=5)
    sensitivity: int = Field(50, ge=0, le=100)
    object_type_filter: SecurityObjectTypeEnum = SecurityObjectTypeEnum.BOTH
    is_active: bool = True

    @field_validator("points")
    @classmethod
    def validate_points(cls, value: List[List[float]]) -> List[List[float]]:
        return _validate_normalized_points(value) or []

    @field_validator("active_from", "active_to")
    @classmethod
    def validate_time_hhmm(cls, value: Optional[str]) -> Optional[str]:
        return _validate_hhmm(value)

    @model_validator(mode="after")
    def validate_schedule_window(self):
        if self.schedule_mode == SecurityScheduleModeEnum.CUSTOM_WINDOW:
            if not self.active_from or not self.active_to:
                raise ValueError("active_from and active_to are required for custom_window")
        return self


class SecurityRuleCreate(SecurityRuleBase):
    """Schéma pour créer une règle de sécurité."""
    pass


class SecurityRuleUpdate(BaseModel):
    """Schéma pour mettre à jour une règle de sécurité."""
    site_id: Optional[int] = None
    camera_id: Optional[int] = None
    zone_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    rule_type: Optional[SecurityRuleTypeEnum] = None
    points: Optional[List[List[float]]] = None
    direction_mode: Optional[SecurityDirectionModeEnum] = None
    schedule_mode: Optional[SecurityScheduleModeEnum] = None
    active_from: Optional[str] = Field(None, max_length=5)
    active_to: Optional[str] = Field(None, max_length=5)
    sensitivity: Optional[int] = Field(None, ge=0, le=100)
    object_type_filter: Optional[SecurityObjectTypeEnum] = None
    is_active: Optional[bool] = None

    @field_validator("points")
    @classmethod
    def validate_points(cls, value: Optional[List[List[float]]]) -> Optional[List[List[float]]]:
        return _validate_normalized_points(value)

    @field_validator("active_from", "active_to")
    @classmethod
    def validate_time_hhmm(cls, value: Optional[str]) -> Optional[str]:
        return _validate_hhmm(value)


class SecurityRuleOut(SecurityRuleBase):
    """Schéma de sortie règle de sécurité."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class SecurityRuleToggleRequest(BaseModel):
    is_active: bool


# ============= CAMERA SCHEMAS =============

class CameraBase(BaseModel):
    """Schéma de base pour caméra"""
    site_id: Optional[int] = None
    zone_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    rtsp_url: Optional[str] = None
    ip_address: Optional[str] = None
    port: int = 554
    camera_type: str = "mix"
    is_enabled: bool = True
    zone_name: Optional[str] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_active: bool = True
    is_recording: bool = False
    streaming_enabled: bool = True
    motion_detection_enabled: bool = True
    object_detection_enabled: bool = True
    detection_sensitivity: int = Field(50, ge=0, le=100)
    pan_tilt_zoom_capable: bool = False
    ai_model: Optional[str] = None
    ai_enabled: bool = False
    selection_role: Optional[str] = None
    selection_score: Optional[float] = None
    stream_validation_status: Optional[str] = None
    stream_validation_message: Optional[str] = None
    stream_codec: Optional[str] = None
    stream_width: Optional[int] = None
    stream_height: Optional[int] = None
    stream_fps: Optional[float] = None
    analysis_metadata: Optional[Dict[str, Any]] = None
    last_snapshot_path: Optional[str] = None


class CameraCreate(CameraBase):
    """Schéma pour créer une caméra"""
    username: Optional[str] = None
    password: Optional[str] = None


class CameraUpdate(BaseModel):
    """Schéma pour mettre à jour une caméra"""
    site_id: Optional[int] = None
    zone_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    rtsp_url: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    camera_type: Optional[str] = None
    is_enabled: Optional[bool] = None
    zone_name: Optional[str] = None
    location: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_active: Optional[bool] = None
    is_recording: Optional[bool] = None
    streaming_enabled: Optional[bool] = None
    motion_detection_enabled: Optional[bool] = None
    object_detection_enabled: Optional[bool] = None
    detection_sensitivity: Optional[int] = Field(None, ge=0, le=100)
    ai_enabled: Optional[bool] = None
    ai_model: Optional[str] = None
    selection_role: Optional[str] = None
    selection_score: Optional[float] = None
    stream_validation_status: Optional[str] = None
    stream_validation_message: Optional[str] = None
    stream_codec: Optional[str] = None
    stream_width: Optional[int] = None
    stream_height: Optional[int] = None
    stream_fps: Optional[float] = None
    analysis_metadata: Optional[Dict[str, Any]] = None
    last_snapshot_path: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class CameraOut(CameraBase):
    """Schéma pour retourner une caméra"""
    id: int
    tenant_id: Optional[int] = None
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime]
    last_activity: Optional[datetime]
    zones: Optional[List[ZoneOut]] = []
    
    model_config = ConfigDict(from_attributes=True)


class CameraDetail(CameraOut):
    """Schéma détaillé pour une caméra avec zones"""
    zones: List[ZoneOut] = []


class CameraTestConnectionRequest(BaseModel):
    """Schéma pour tester la connexion d'une caméra"""
    rtsp_url: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = 554
    username: Optional[str] = None
    password: Optional[str] = None


class CameraTestConnectionResponse(BaseModel):
    """Schéma pour réponse de test de connexion"""
    status: str  # connected, disconnected, timeout, error
    message: str
    latency_ms: Optional[float] = None
    camera_info: Optional[Dict[str, Any]] = None


class CameraConnectionStatus(BaseModel):
    """Schéma pour statut de connexion d'une caméra"""
    camera_id: int
    connection_status: str  # connected, disconnected, error, unknown
    last_connection_check: Optional[datetime] = None
    connection_error: Optional[str] = None


class CameraDiscoveryRequest(BaseModel):
    """Parametres de scan reseau pour decouverte camera."""
    subnet: Optional[str] = Field(
        default=None,
        description="CIDR subnet to scan, ex: 192.168.1.0/24",
    )
    start_ip: Optional[str] = Field(
        default=None,
        description="Range scan start IPv4, ex: 192.168.1.10",
    )
    end_ip: Optional[str] = Field(
        default=None,
        description="Range scan end IPv4, ex: 192.168.1.100",
    )
    port: int = Field(default=554, ge=1, le=65535)
    ports: Optional[List[int]] = Field(
        default=None,
        description="Optional list of ports to scan (overrides port).",
    )
    timeout_ms: int = Field(default=700, ge=100, le=5000)
    max_hosts: int = Field(default=256, ge=1, le=4096)
    rtsp_paths: Optional[List[str]] = Field(
        default=None,
        description="Optional RTSP path candidates, ex: /Streaming/Channels/101",
    )
    onvif: bool = Field(default=True, description="Attempt ONVIF detection on HTTP ports.")
    onvif_ports: Optional[List[int]] = Field(
        default=None,
        description="Optional ONVIF ports to try (defaults to common HTTP ports).",
    )
    username: Optional[str] = Field(default=None, description="Optional username for ONVIF/RTSP.")
    password: Optional[str] = Field(default=None, description="Optional password for ONVIF/RTSP.")
    probe_rtsp: bool = Field(default=True, description="Test RTSP candidates and return first working URL.")
    max_rtsp_tests: int = Field(default=4, ge=1, le=20, description="Max RTSP candidates to test per camera.")


class DiscoveredCameraConnectItem(BaseModel):
    """Camera candidate returned by discovery and selected for quick connect."""
    ip_address: str = Field(..., min_length=3, max_length=64)
    port: int = Field(default=554, ge=1, le=65535)
    known_camera_id: Optional[int] = None
    known_camera_name: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = None
    zone_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    open_ports: Optional[List[int]] = None
    rtsp_candidates: Optional[List[str]] = None
    rtsp_working_url: Optional[str] = None
    onvif: Optional[Dict[str, Any]] = None
    connection_status: Optional[str] = None
    streaming_enabled: Optional[bool] = None
    ai_enabled: Optional[bool] = None
    motion_detection_enabled: Optional[bool] = None
    object_detection_enabled: Optional[bool] = None
    detection_sensitivity: Optional[int] = Field(default=None, ge=0, le=100)


class CameraDiscoveryConnectRequest(BaseModel):
    """Bulk quick-connect request built from network discovery results."""
    items: List[DiscoveredCameraConnectItem] = Field(default_factory=list, min_length=1)
    default_location: Optional[str] = None
    default_zone_name: Optional[str] = None
    streaming_enabled: bool = True
    ai_enabled: bool = False
    motion_detection_enabled: bool = True
    object_detection_enabled: bool = True
    detection_sensitivity: int = Field(default=50, ge=0, le=100)
    update_existing: bool = True
    auto_test: bool = True


class CameraDiscoveryAnalyzeRequest(BaseModel):
    """Analyze discovered devices to fetch live preview and health metrics."""
    items: List[DiscoveredCameraConnectItem] = Field(default_factory=list, min_length=1)
    include_preview: bool = True
    sample_frames: int = Field(default=4, ge=1, le=12)


# ============= EVENT SCHEMAS =============

class EventBase(BaseModel):
    """Schéma de base pour événement"""
    event_type: EventTypeEnum = Field(..., description="Type d'événement")
    severity: SeverityEnum = SeverityEnum.INFO
    decision: str = "review"
    description: Optional[str] = None
    detected_objects: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_acknowledged: bool = False


class EventCreate(BaseModel):
    """Schéma pour créer un événement"""
    camera_id: int
    zone_id: Optional[int] = None
    site_id: Optional[int] = None
    event_type: EventTypeEnum
    severity: SeverityEnum = SeverityEnum.INFO
    decision: Optional[str] = "review"
    description: Optional[str] = None
    detected_objects: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    detected_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    thumbnail_url: Optional[str] = None
    video_url: Optional[str] = None
    snapshot_path: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


class EventUpdate(BaseModel):
    """Schéma pour mettre à jour un événement"""
    description: Optional[str] = None
    severity: Optional[SeverityEnum] = None
    decision: Optional[str] = None
    is_acknowledged: Optional[bool] = None
    is_archived: Optional[bool] = None


class EventOut(EventBase):
    """Schéma pour retourner un événement"""
    id: int
    tenant_id: Optional[int] = None
    camera_id: int
    zone_id: Optional[int]
    site_id: Optional[int]
    creator_id: int
    detected_at: datetime
    created_at: datetime
    updated_at: Optional[datetime]
    is_archived: bool
    extra_data: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


class EventDetail(EventOut):
    """Schéma détaillé pour un événement"""
    camera: Optional[CameraOut] = None
    zone: Optional[ZoneOut] = None


# ============= ALERT RULE SCHEMAS =============

class AlertRuleBase(BaseModel):
    """Schéma de base pour règle d'alerte"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    event_type: EventTypeEnum
    camera_id: Optional[int] = None
    min_confidence: float = Field(0.5, ge=0.0, le=1.0)
    min_object_count: int = Field(1, ge=1)
    enable_notification: bool = True
    enable_recording: bool = True
    enable_alert_sound: bool = False
    is_active: bool = True


class AlertRuleCreate(AlertRuleBase):
    """Schéma pour créer une règle d'alerte"""
    pass


class AlertRuleUpdate(BaseModel):
    """Schéma pour mettre à jour une règle d'alerte"""
    name: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[EventTypeEnum] = None
    min_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    min_object_count: Optional[int] = Field(None, ge=1)
    enable_notification: Optional[bool] = None
    enable_recording: Optional[bool] = None
    enable_alert_sound: Optional[bool] = None
    is_active: Optional[bool] = None


class AlertRuleOut(AlertRuleBase):
    """Schéma pour retourner une règle d'alerte"""
    id: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    model_config = ConfigDict(from_attributes=True)


# ============= NOTIFICATION SCHEMAS =============

class NotificationBase(BaseModel):
    """Schéma de base pour notification"""
    title: str = Field(..., min_length=1, max_length=200)
    message: Optional[str] = None
    notification_type: str = "info"


class NotificationCreate(NotificationBase):
    """Schéma pour créer une notification"""
    user_id: int
    event_id: Optional[int] = None


class NotificationOut(NotificationBase):
    """Schéma pour retourner une notification"""
    id: int
    user_id: int
    event_id: Optional[int]
    is_read: bool
    is_sent: bool
    created_at: datetime
    read_at: Optional[datetime]
    sent_at: Optional[datetime]
    
    model_config = ConfigDict(from_attributes=True)


# ============= SYSTEM LOG SCHEMAS =============

class SystemLogCreate(BaseModel):
    """Schéma pour créer un log système"""
    level: LogLevelEnum
    module: Optional[str] = None
    message: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


class SystemLogOut(SystemLogCreate):
    """Schéma pour retourner un log système"""
    id: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============= VEHICLE SCHEMAS =============

class VehicleBase(BaseModel):
    """Schéma de base pour véhicule"""
    license_plate: Optional[str] = None
    vehicle_type: Optional[str] = None
    color: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    direction: Optional[str] = None
    speed: Optional[float] = None


class VehicleCreate(VehicleBase):
    """Schéma pour créer un véhicule"""
    event_id: int
    camera_id: int
    detected_at: Optional[datetime] = None
    bounding_box: Optional[Dict[str, Any]] = None


class VehicleOut(VehicleBase):
    """Schéma pour retourner un véhicule"""
    id: int
    event_id: int
    camera_id: int
    detected_at: datetime
    created_at: datetime
    bounding_box: Optional[Dict[str, Any]]
    
    model_config = ConfigDict(from_attributes=True)


# ============= HEALTH CHECK SCHEMAS =============

class HealthCheck(BaseModel):
    """Schéma pour health check"""
    status: str
    timestamp: datetime
    service: str


# ============= STATISTICS SCHEMAS =============

class CameraStats(BaseModel):
    """Statistiques caméra"""
    camera_id: int
    total_events: int = 0
    motion_events: int = 0
    object_events: int = 0
    last_event_at: Optional[datetime] = None
    uptime_percentage: float = 100.0


class SystemStats(BaseModel):
    """Statistiques système"""
    total_cameras: int = 0
    active_cameras: int = 0
    total_events_today: int = 0
    total_users: int = 0
    database_size: Optional[str] = None
    memory_usage: Optional[str] = None
    cpu_usage: Optional[str] = None


# ============= PERSONNEL SCHEMAS =============

PERSONNEL_GRADES_BY_CATEGORY: Dict[str, List[str]] = {
    "soldat": [
        "Soldat de deuxième classe",
        "Soldat de première classe",
        "Caporal",
        "Caporal-chef",
    ],
    "soldat_invite": ["Soldat invité"],
    "sous_officier": [
        "Sergent",
        "Sergent-chef",
        "Adjudant",
        "Adjudant-chef",
        "Adjudant-major",
    ],
    "officier": [
        "Sous-lieutenant",
        "Lieutenant",
        "Capitaine",
        "Commandant",
        "Lieutenant-colonel",
        "Colonel",
        "Colonel-major",
        "Général de brigade",
        "Général de division",
        "Général de corps d'armée",
    ],
    # Civil: grade libre
    "civil": [],
}


def validate_personnel_grade_for_category(
    categorie: Optional[PersonnelCategoryEnum | str],
    grade: Optional[str],
) -> None:
    if categorie is None or grade is None:
        return

    category_value = categorie.value if isinstance(categorie, PersonnelCategoryEnum) else str(categorie).strip().lower()
    grade_value = str(grade).strip()
    if not grade_value:
        raise ValueError("Grade requis")

    allowed = PERSONNEL_GRADES_BY_CATEGORY.get(category_value)
    if allowed is None:
        return
    if not allowed:
        return

    allowed_casefold = {g.casefold() for g in allowed}
    if grade_value.casefold() not in allowed_casefold:
        raise ValueError(
            f"Grade '{grade_value}' incohérent avec la catégorie '{category_value}'. "
            f"Grades autorisés: {', '.join(allowed)}"
        )


class PersonnelBase(BaseModel):
    """Schéma de base pour annuaire des personnes."""
    nom: str = Field(..., min_length=2, max_length=50)
    prenom: str = Field(..., min_length=2, max_length=50)
    cin: Optional[str] = Field(default=None, max_length=20)
    num_recrutement: Optional[str] = Field(default=None, max_length=20)
    categorie: Optional[PersonnelCategoryEnum] = None
    grade: Optional[str] = Field(default=None, max_length=50)
    unite: Optional[str] = None
    gender: Optional[str] = None
    email: Optional[EmailStr] = None
    telephone: Optional[str] = None
    is_active: bool = True
    custom_fields: Optional[Dict[str, Any]] = None


class PersonnelCreate(PersonnelBase):
    """Schéma pour créer personnel"""
    photo_path: Optional[str] = None
    allowed_camera_ids: Optional[List[str]] = None
    authorized_hours_start: str = "06:00"
    authorized_hours_end: str = "22:00"
    notes: Optional[str] = None

    @field_validator('cin')
    @classmethod
    def cin_format(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if not v:
            return None
        if len(v) < 5:
            raise ValueError('Identifiant invalide (min 5 caracteres)')
        return v

    @field_validator('num_recrutement')
    @classmethod
    def recrutement_format(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if not v:
            return None
        if len(v) < 5:
            raise ValueError('Reference invalide (min 5 caracteres)')
        return v

    @model_validator(mode="after")
    def grade_category_consistency(self):
        validate_personnel_grade_for_category(self.categorie, self.grade)
        return self


class PersonnelUpdate(BaseModel):
    """Schéma pour mettre à jour personnel"""
    nom: Optional[str] = None
    prenom: Optional[str] = None
    cin: Optional[str] = None
    num_recrutement: Optional[str] = None
    grade: Optional[str] = None
    unite: Optional[str] = None
    email: Optional[EmailStr] = None
    telephone: Optional[str] = None
    categorie: Optional[PersonnelCategoryEnum] = None
    is_active: Optional[bool] = None
    is_blacklisted: Optional[bool] = None
    blacklist_reason: Optional[str] = None
    authorized_hours_start: Optional[str] = None
    authorized_hours_end: Optional[str] = None
    notes: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None

    @field_validator('cin')
    @classmethod
    def cin_format(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if not v:
            return None
        if len(v) < 5:
            raise ValueError('Identifiant invalide (min 5 caracteres)')
        return v

    @field_validator('num_recrutement')
    @classmethod
    def recrutement_format(cls, v):
        if v is None:
            return v
        v = str(v).strip()
        if not v:
            return None
        if len(v) < 5:
            raise ValueError('Reference invalide (min 5 caracteres)')
        return v

    @model_validator(mode="after")
    def grade_category_consistency(self):
        categorie = self.categorie
        grade = self.grade
        if categorie is not None and grade is not None:
            validate_personnel_grade_for_category(categorie, grade)
        return self


class PersonnelBulkDeactivateRequest(BaseModel):
    """Schéma pour désactiver plusieurs personnels en une seule requête."""
    personnel_ids: List[int] = Field(..., min_length=1)


class PersonnelBulkDeactivateResult(BaseModel):
    """Résultat d'une désactivation groupée."""
    requested_count: int
    updated_count: int
    already_inactive_count: int
    missing_ids: List[int] = Field(default_factory=list)
    updated_ids: List[int] = Field(default_factory=list)


class PersonnelOut(PersonnelBase):
    """Schéma pour retourner personnel"""
    id: int
    full_name: str
    photo_path: Optional[str] = None
    face_embedding: Optional[bytes] = Field(default=None, exclude=True)
    face_encodings: Optional[List[float]] = None
    is_blacklisted: bool
    last_entry: Optional[datetime] = None
    last_exit: Optional[datetime] = None
    total_entries_today: int
    date_enregistrement: datetime
    date_modification: Optional[datetime] = None
    custom_fields: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(from_attributes=True)


class PersonnelEventOut(BaseModel):
    """Schéma pour événement personnel"""
    id: int
    personnel_id: int
    personnel: Optional[PersonnelOut] = None
    camera_id: int
    direction: str
    confidence: float
    method: str
    detected_at: datetime
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ============= VEHICLE REGISTRY SCHEMAS =============

class VehicleRegistryBase(BaseModel):
    """Schéma de base pour registre de véhicule - Harmonisé avec Personnel"""
    matricule: str = Field(..., min_length=3, max_length=20)  # Plaque immatriculation
    marque: str = Field(..., min_length=2, max_length=50)
    modele: str = Field(..., min_length=2, max_length=50)
    couleur: Optional[str] = None
    categorie: str = Field(..., pattern="^(civil|militaire)$")  # "civil" ou "militaire"
    unite: Optional[str] = None  # Unité militaire (si categorie="militaire")
    sous_categorie_militaire: Optional[str] = Field(None, pattern="^(operationnel|personnel)$")
    statut: str = Field(default="actif", pattern="^(actif|hors_service|maintenance)$")
    photo_path: Optional[str] = None


class VehicleRegistryCreate(VehicleRegistryBase):
    """Schéma pour créer véhicule enregistré"""
    # Champs legacy pour compatibilite descendante (anciens tests/UI)
    type_vehicule: Optional[str] = None
    marque_modele: Optional[str] = None
    immatriculation: Optional[str] = None
    etat: Optional[str] = None
    proprietaire: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def map_legacy_payload(cls, values):
        if not isinstance(values, dict):
            return values

        if not values.get("matricule") and values.get("immatriculation"):
            values["matricule"] = values.get("immatriculation")

        if (not values.get("marque") or not values.get("modele")) and values.get("marque_modele"):
            combined = str(values.get("marque_modele")).strip()
            if combined:
                parts = combined.split(None, 1)
                values.setdefault("marque", parts[0])
                values.setdefault("modele", parts[1] if len(parts) > 1 else parts[0])

        if not values.get("categorie") and values.get("type_vehicule"):
            vehicle_type = str(values.get("type_vehicule")).strip().lower()
            values["categorie"] = "militaire" if vehicle_type.startswith("mil") else "civil"

        if not values.get("statut") and values.get("etat"):
            values["statut"] = values.get("etat")

        if not values.get("unite") and values.get("proprietaire"):
            values["unite"] = values.get("proprietaire")

        if not values.get("sous_categorie_militaire") and values.get("military_category"):
            values["sous_categorie_militaire"] = values.get("military_category")

        return values

    @field_validator('matricule')
    @classmethod
    def matricule_format(cls, v):
        if not v or len(v) < 3:
            raise ValueError('Matricule invalide')
        return v.upper()

    @model_validator(mode="after")
    def normalize_military_subcategory(self):
        categorie = str(self.categorie or "").strip().lower()
        if categorie != "militaire":
            self.sous_categorie_militaire = None
        return self

    model_config = ConfigDict(extra="ignore")


class VehicleRegistryUpdate(BaseModel):
    """Schéma pour mettre à jour véhicule enregistré"""
    marque: Optional[str] = None
    modele: Optional[str] = None
    couleur: Optional[str] = None
    categorie: Optional[str] = Field(None, pattern="^(civil|militaire)$")
    unite: Optional[str] = None
    sous_categorie_militaire: Optional[str] = Field(None, pattern="^(operationnel|personnel)$")
    statut: Optional[str] = Field(None, pattern="^(actif|hors_service|maintenance)$")
    photo_path: Optional[str] = None


class VehicleRegistryOut(VehicleRegistryBase):
    """Schéma pour retourner véhicule enregistré"""
    id: int
    is_whitelisted: bool = False
    is_blacklisted: bool = False
    blacklist_reason: Optional[str] = None
    date_enregistrement: datetime
    date_modification: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


# ============= VEHICLE ENTRY SCHEMAS =============

class VehicleEntryBase(BaseModel):
    """Schéma de base pour entrée véhicule"""
    license_plate: str
    vehicle_type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None


class VehicleEntryCreate(VehicleEntryBase):
    """Schéma pour créer entrée véhicule"""
    entry_camera_id: int
    entry_time: datetime
    entry_confidence: float = Field(..., ge=0.0, le=1.0)


class VehicleEntryUpdate(BaseModel):
    """Schéma pour mettre à jour entrée véhicule"""
    exit_camera_id: Optional[int] = None
    exit_time: Optional[datetime] = None
    exit_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    status: Optional[str] = None


class VehicleEntryOut(VehicleEntryBase):
    """Schéma pour retourner entrée véhicule"""
    id: int
    entry_camera_id: int
    exit_camera_id: Optional[int] = None
    entry_time: datetime
    exit_time: Optional[datetime] = None
    entry_confidence: float
    exit_confidence: Optional[float] = None
    duration_minutes: Optional[int] = None
    status: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
