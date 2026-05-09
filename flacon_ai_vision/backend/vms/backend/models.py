# vms/backend/models.py - Modèles SQLAlchemy

import os

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Text, ARRAY, JSON, LargeBinary, Enum as SQLEnum, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .core.database import Base
from .core.config import settings
from datetime import datetime
from enum import Enum

try:
    from pgvector.sqlalchemy import Vector as PGVector
except Exception:
    PGVector = None


def _face_embedding_column_type():
    if os.getenv("FACE_PGVECTOR_ENABLED", "true").lower() != "true":
        return JSON
    if not str(getattr(settings, "DATABASE_URL", "") or "").lower().startswith("postgresql"):
        return JSON
    if PGVector is not None:
        try:
            return PGVector(512)
        except Exception:
            pass
    return JSON

# ============= ÉNUMÉRATIONS =============

class PersonnelCategoryEnum(str, Enum):
    """Legacy personnel categories (kept for compatibility)."""
    OFFICIER = "officier"
    SOUS_OFFICIER = "sous_officier"
    SOLDAT = "soldat"
    SOLDAT_INVITE = "soldat_invite"
    CIVIL = "civil"


class ProjectTypeEnum(str, Enum):
    """Project type for tenant-level UI and vocabulary presets."""
    HOME = "home"
    BUSINESS = "business"
    SOC = "soc"


class VehicleTypeEnum(str, Enum):
    """Legacy vehicle category."""
    MILITAIRE = "militaire"
    CIVILE = "civile"
    INCONNU = "inconnu"


class VehicleStateEnum(str, Enum):
    """État du véhicule"""
    ACTIF = "actif"
    HORS_SERVICE = "hors_service"
    MAINTENANCE = "maintenance"

# ============= MODÈLES =============


class Tenant(Base):
    """Tenant / Company for multi-tenant SaaS."""
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, index=True)
    slug = Column(String(120), nullable=True, unique=True, index=True)
    plan = Column(String(30), default="starter", nullable=False, index=True)
    project_type = Column(
        String(20),
        default=ProjectTypeEnum.BUSINESS.value,
        nullable=False,
        index=True,
    )
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    users = relationship("User", back_populates="tenant")
    subscriptions = relationship("Subscription", back_populates="tenant")
    sites = relationship("Site", back_populates="tenant")
    cameras = relationship("Camera", back_populates="tenant")
    zones = relationship("Zone", back_populates="tenant")
    events = relationship("Event", back_populates="tenant")
    alert_rules = relationship("AlertRule", back_populates="tenant")
    notifications = relationship("Notification", back_populates="tenant")
    security_alerts = relationship("SecurityAlert", back_populates="tenant")

    def __repr__(self):
        return f"<Tenant(id={self.id}, name={self.name}, plan={self.plan})>"

class User(Base):
    """Modèle utilisateur"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    role = Column(String(20), default="operator", nullable=False, index=True)  # admin | operator | viewer
    is_active = Column(Boolean, default=True, index=True)
    is_admin = Column(Boolean, default=False)
    last_login = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Setup and mode configuration
    setup_completed = Column(Boolean, default=False, index=True)
    application_mode = Column(String(20), nullable=True, index=True)  # "home" | "company"
    country_code = Column(String(3), nullable=True, index=True)  # ISO 3166-1 alpha-3
    timezone = Column(String(50), nullable=True)

    # Relations
    tenant = relationship("Tenant", back_populates="users")
    cameras = relationship("Camera", back_populates="owner", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="creator", cascade="all, delete-orphan")
    family_members = relationship("FamilyMember", back_populates="user", cascade="all, delete-orphan")
    employees = relationship("Employee", back_populates="user", cascade="all, delete-orphan")
    vehicles = relationship("UserVehicle", back_populates="owner", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, mode={self.application_mode})>"


class RefreshToken(Base):
    """Refresh token store (rotation + revoke support)."""
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    is_revoked = Column(Boolean, default=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by_token_hash = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_by_ip = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)

    user = relationship("User")

    def __repr__(self):
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, revoked={self.is_revoked})>"


class Subscription(Base):
    """Subscription state per user (commercial entitlements)."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    tier = Column(String(30), default="free", index=True)
    is_active = Column(Boolean, default=False, index=True)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    auto_renew = Column(Boolean, default=False, index=True)
    next_renewal_at = Column(DateTime(timezone=True), nullable=True, index=True)
    renewal_period_days = Column(Integer, default=30)

    provider = Column(String(30), nullable=True)  # stripe | paypal | manual
    external_id = Column(String(120), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")

    tenant = relationship("Tenant", back_populates="subscriptions")
    def __repr__(self):
        return f"<Subscription(id={self.id}, user_id={self.user_id}, tier={self.tier}, active={self.is_active})>"


class SubscriptionHistory(Base):
    """Audit trail for subscription changes."""
    __tablename__ = "subscription_history"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(40), nullable=False, index=True)  # created | updated | renewed | cancelled | deactivated

    previous_tier = Column(String(30), nullable=True)
    new_tier = Column(String(30), nullable=True)
    previous_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=True)
    note = Column(String(255), nullable=True)
    payload = Column(JSON, nullable=True)

    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subscription = relationship("Subscription")
    user = relationship("User", foreign_keys=[user_id])
    actor = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<SubscriptionHistory(id={self.id}, user_id={self.user_id}, action={self.action})>"


class SubscriptionPayment(Base):
    """Payment log for subscription billing (Stripe/PayPal/manual)."""
    __tablename__ = "subscription_payments"

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(30), nullable=True)  # stripe | paypal | manual
    amount = Column(Float, nullable=True)
    currency = Column(String(10), default="USD")
    status = Column(String(30), default="paid", index=True)  # paid | pending | failed | refunded
    paid_at = Column(DateTime(timezone=True), nullable=True, index=True)
    reference_id = Column(String(120), nullable=True, index=True)
    note = Column(String(255), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subscription = relationship("Subscription")
    user = relationship("User")

    def __repr__(self):
        return f"<SubscriptionPayment(id={self.id}, user_id={self.user_id}, status={self.status})>"


class AuditLog(Base):
    """Audit trail for security-sensitive API actions."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username = Column(String(50), nullable=True, index=True)
    event_type = Column(String(60), nullable=False, index=True)
    action = Column(String(80), nullable=False, index=True)
    method = Column(String(10), nullable=False)
    path = Column(String(255), nullable=False, index=True)
    status_code = Column(Integer, nullable=False, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    request_id = Column(String(64), nullable=True, index=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User")

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, status={self.status_code})>"


class Site(Base):
    """Site physique regroupant zones, caméras et événements."""
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    code = Column(String(40), nullable=True, unique=True, index=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="sites")
    zones = relationship("Zone", back_populates="site")
    cameras = relationship("Camera", back_populates="site")
    events = relationship("Event", back_populates="site")
    vehicle_events = relationship("VehicleEvent", back_populates="site")
    vehicle_access_logs = relationship("VehicleAccessLog", back_populates="site")
    security_alerts = relationship("SecurityAlert", back_populates="site")
    security_rules = relationship("SecurityRule", back_populates="site")

    def __repr__(self):
        return f"<Site(id={self.id}, name={self.name})>"


class Camera(Base):
    """Modèle caméra"""
    __tablename__ = "cameras"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    rtsp_url = Column(String(255), nullable=True)
    ip_address = Column(String(15), nullable=True)
    port = Column(Integer, default=554, nullable=True)
    username = Column(String(50), nullable=True)
    password = Column(String(100), nullable=True)
    
    # Localisation et orientation
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    zone_name = Column(String(100), nullable=True, index=True)
    location = Column(String(200), nullable=True)
    pan_tilt_zoom_capable = Column(Boolean, default=False)
    
    # État et configuration
    is_active = Column(Boolean, default=True, index=True)
    is_recording = Column(Boolean, default=False)
    streaming_enabled = Column(Boolean, default=True)
    
    # Statut de connexion
    connection_status = Column(String(20), default="unknown", nullable=False)  # connected, disconnected, error, unknown
    last_connection_check = Column(DateTime(timezone=True), nullable=True)
    connection_error = Column(String(500), nullable=True)
    
    # Détection et monitoring
    motion_detection_enabled = Column(Boolean, default=True)
    object_detection_enabled = Column(Boolean, default=True)
    detection_sensitivity = Column(Integer, default=50)  # 0-100
    
    # AI models
    ai_model = Column(String(50), nullable=True)  # ex: "yolov8", "yolov9"
    ai_enabled = Column(Boolean, default=False)
    selection_role = Column(String(40), nullable=True, index=True)
    selection_score = Column(Float, nullable=True)
    stream_validation_status = Column(String(20), nullable=True, index=True)
    stream_validation_message = Column(String(255), nullable=True)
    stream_codec = Column(String(32), nullable=True)
    stream_width = Column(Integer, nullable=True)
    stream_height = Column(Integer, nullable=True)
    stream_fps = Column(Float, nullable=True)
    analysis_metadata = Column(JSON, nullable=True)
    last_snapshot_path = Column(String(255), nullable=True)

    # Topologie
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True, index=True)
    camera_type = Column(String(20), nullable=False, default="mix", index=True)  # face | vehicle | mix
    is_enabled = Column(Boolean, default=True, index=True)
    
    # Propriétaire
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Métadonnées
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_activity = Column(DateTime(timezone=True), nullable=True)
    
    # Relations
    tenant = relationship("Tenant", back_populates="cameras")
    owner = relationship("User", back_populates="cameras")
    site = relationship("Site", back_populates="cameras")
    primary_zone = relationship("Zone", foreign_keys=[zone_id], back_populates="cameras")
    events = relationship("Event", back_populates="camera", cascade="all, delete-orphan")
    zones = relationship(
        "Zone",
        back_populates="camera",
        cascade="all, delete-orphan",
        foreign_keys="Zone.camera_id",
    )
    security_rules = relationship("SecurityRule", back_populates="camera")
    
    def __repr__(self):
        return f"<Camera(id={self.id}, name={self.name}, location={self.location})>"


class Zone(Base):
    """Modèle zone de détection"""
    __tablename__ = "zones"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    
    # Géométrie (polygon points)
    points = Column(JSON, nullable=True)  # [[x1,y1], [x2,y2], ...]
    
    # Configuration
    is_active = Column(Boolean, default=True)
    zone_type = Column(String(30), nullable=False, default="custom", index=True)
    is_blocked = Column(Boolean, default=False, index=True)
    block_reason = Column(String(255), nullable=True)
    motion_detection_enabled = Column(Boolean, default=True)
    object_detection_enabled = Column(Boolean, default=True)
    
    # Sensibilité
    sensitivity = Column(Integer, default=50)  # 0-100
    
    # Métadonnées
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    tenant = relationship("Tenant", back_populates="zones")
    site = relationship("Site", back_populates="zones")
    camera = relationship("Camera", back_populates="zones", foreign_keys=[camera_id])
    cameras = relationship("Camera", back_populates="primary_zone", foreign_keys="Camera.zone_id")
    events = relationship("Event", back_populates="zone", cascade="all, delete-orphan")
    security_rules = relationship("SecurityRule", back_populates="zone")
    
    def __repr__(self):
        return f"<Zone(id={self.id}, name={self.name}, camera_id={self.camera_id})>"


class SecurityRule(Base):
    """Règles de sécurité pour lignes/zones virtuelles (module IA Zone)."""
    __tablename__ = "security_rules"

    id = Column(Integer, primary_key=True, index=True)

    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True, index=True)

    name = Column(String(120), nullable=False, index=True)
    description = Column(Text, nullable=True)

    rule_type = Column(String(20), nullable=False, default="zone", index=True)  # zone | line
    points = Column(JSON, nullable=True)  # [[x,y], [x,y], ...] normalized 0..1

    direction_mode = Column(String(20), nullable=False, default="both", index=True)  # both | entry_only | exit_only
    schedule_mode = Column(String(20), nullable=False, default="always", index=True)  # always | night_only | custom_window
    active_from = Column(String(5), nullable=True)  # HH:MM
    active_to = Column(String(5), nullable=True)  # HH:MM
    sensitivity = Column(Integer, default=50)  # 0-100
    object_type_filter = Column(String(20), nullable=False, default="both", index=True)  # person | vehicle | both

    is_active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    site = relationship("Site", back_populates="security_rules")
    camera = relationship("Camera", back_populates="security_rules")
    zone = relationship("Zone", back_populates="security_rules")

    def __repr__(self):
        return f"<SecurityRule(id={self.id}, type={self.rule_type}, site_id={self.site_id}, camera_id={self.camera_id})>"


class Event(Base):
    """Modèle événement de détection"""
    __tablename__ = "events"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    
    # Références
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Type d'événement
    event_type = Column(String(50), nullable=False, index=True)  # "motion", "object", "person", "vehicle", "alarm"
    severity = Column(String(20), default="info", index=True)  # "info", "warning", "critical"
    decision = Column(String(30), default="review", index=True)  # allowed | denied | review | review_required | manual_override
    
    # Détails de détection
    description = Column(Text, nullable=True)
    detected_objects = Column(JSON, nullable=True)  # {"person": 2, "car": 1, "dog": 1}
    confidence = Column(Float, nullable=True)  # 0.0-1.0
    
    # Médias
    thumbnail_url = Column(String(255), nullable=True)
    video_url = Column(String(255), nullable=True)
    snapshot_path = Column(String(255), nullable=True)
    
    # Géolocalisation du moment
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    # Timing
    detected_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # État
    is_acknowledged = Column(Boolean, default=False, index=True)
    is_archived = Column(Boolean, default=False, index=True)
    
    # Métadonnées supplémentaires
    extra_data = Column(JSON, nullable=True)  # Données flexibles
    
    # Relations
    tenant = relationship("Tenant", back_populates="events")
    camera = relationship("Camera", back_populates="events")
    zone = relationship("Zone", back_populates="events")
    site = relationship("Site", back_populates="events")
    creator = relationship("User", back_populates="events")
    
    def __repr__(self):
        return f"<Event(id={self.id}, type={self.event_type}, camera_id={self.camera_id})>"


class AlertRule(Base):
    """Modèle règle d'alerte"""
    __tablename__ = "alert_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    # Rule engine identifiers
    rule_key = Column(String(120), nullable=True, index=True)
    rule_type = Column(String(120), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    
    # Déclenchement
    event_type = Column(String(50), nullable=False)  # "motion", "object", "person", etc.
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)  # NULL = toutes caméras
    
    # Conditions
    min_confidence = Column(Float, default=0.5)
    min_object_count = Column(Integer, default=1)
    
    # Actions
    enable_notification = Column(Boolean, default=True)
    enable_recording = Column(Boolean, default=True)
    enable_alert_sound = Column(Boolean, default=False)
    # Rule engine action payload (severity/message)
    action = Column(JSON, nullable=True)
    
    # Configuration
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    tenant = relationship("Tenant", back_populates="alert_rules")
    conditions = relationship(
        "AlertRuleCondition",
        back_populates="rule",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_alert_rules_tenant_rule_key", "tenant_id", "rule_key", unique=True),
    )

    def __repr__(self):
        return f"<AlertRule(id={self.id}, name={self.name})>"


class AlertRuleCondition(Base):
    """Conditions de règle d'alerte (clé/valeur JSON)."""
    __tablename__ = "alert_rule_conditions"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(120), nullable=False, index=True)
    value = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    rule = relationship("AlertRule", back_populates="conditions")

    __table_args__ = (
        Index("ix_alert_rule_conditions_rule_key", "rule_id", "key", unique=True),
    )

    def __repr__(self):
        return f"<AlertRuleCondition(id={self.id}, rule_id={self.rule_id}, key={self.key})>"


class Notification(Base):
    """Modèle notification"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    
    # Références
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Contenu
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    notification_type = Column(String(50), nullable=False)  # "event", "alert", "info"
    
    # État
    is_read = Column(Boolean, default=False, index=True)
    is_sent = Column(Boolean, default=False)
    
    # Timing
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    read_at = Column(DateTime(timezone=True), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    
    tenant = relationship("Tenant", back_populates="notifications")

    def __repr__(self):
        return f"<Notification(id={self.id}, user_id={self.user_id})>"


class SystemLog(Base):
    """Modèle log système"""
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Contenu
    level = Column(String(20), nullable=False, index=True)  # "DEBUG", "INFO", "WARNING", "ERROR"
    module = Column(String(100), nullable=True)
    message = Column(Text, nullable=True)
    
    # Détails
    extra_data = Column(JSON, nullable=True)
    
    # Timing
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    def __repr__(self):
        return f"<SystemLog(id={self.id}, level={self.level})>"


class Vehicle(Base):
    """Modèle véhicule détecté"""
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Références
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    
    # Identification
    license_plate = Column(String(50), nullable=True, index=True)
    vehicle_type = Column(String(50), nullable=True)  # "car", "truck", "bus", "motorcycle"
    color = Column(String(50), nullable=True)
    brand = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    
    # Détection
    confidence = Column(Float, default=0.0)
    bounding_box = Column(JSON, nullable=True)  # {"x": 0, "y": 0, "width": 100, "height": 100}
    
    # Détails
    direction = Column(String(50), nullable=True)  # "north", "south", "east", "west"
    speed = Column(Float, nullable=True)  # km/h
    
    # Timing
    detected_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<Vehicle(id={self.id}, license_plate={self.license_plate})>"


class Personnel(Base):
    """Modèle pour les personnes enregistrées (champs legacy)."""
    __tablename__ = "personnel"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Identité et État Civil
    nom = Column(String(50), nullable=False, index=True)
    prenom = Column(String(50), nullable=False, index=True)
    full_name = Column(String(100), nullable=False, index=True)  # Conservé pour rétro-compatibilité
    
    # Documents d'Identité
    cin = Column(String(20), unique=True, nullable=False, index=True)  # N° Carte Identité Nationale
    cin_expiry = Column(DateTime(timezone=True), nullable=True)  # Date d'expiration carte identité
    
    # Militaire
    num_recrutement = Column(String(20), unique=True, nullable=False, index=True)  # Numéro de recrutement
    categorie = Column(
        SQLEnum(PersonnelCategoryEnum), 
        default=PersonnelCategoryEnum.SOLDAT, 
        nullable=False,
        index=True
    )  # officier, sous_officier, soldat, soldat_invite
    grade = Column(String(50), nullable=False, index=True)  # Role / rank label
    unite = Column(String(100), nullable=True)  # Unité militaire
    
    # Informations Personnelles
    gender = Column(String(20), nullable=True)  # "male", "female"
    email = Column(String(100), nullable=True, unique=True)
    telephone = Column(String(20), nullable=True)
    
    # Photo et Biométrie
    photo_path = Column(String(255), nullable=True)
    face_embedding = Column(LargeBinary, nullable=True)
    face_encodings = Column(JSON, nullable=True)  # List[float]
    
    # Caméras autorisées
    allowed_camera_ids = Column(JSON, nullable=True)  # ["MAT2", "MAT3"]
    
    # Horaires d'Accès
    authorized_hours_start = Column(String(5), default="06:00")  # HH:MM
    authorized_hours_end = Column(String(5), default="22:00")
    
    # Contraintes d'Accès
    is_active = Column(Boolean, default=True, index=True)
    is_blacklisted = Column(Boolean, default=False, index=True)
    blacklist_reason = Column(String(255), nullable=True)
    
    # Tracking d'Activité
    last_entry = Column(DateTime(timezone=True), nullable=True)
    last_exit = Column(DateTime(timezone=True), nullable=True)
    total_entries_today = Column(Integer, default=0)
    
    # Métadonnées
    date_enregistrement = Column(DateTime(timezone=True), server_default=func.now())
    date_modification = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    notes = Column(Text, nullable=True)
    custom_fields = Column(JSON, nullable=True)  # Flexible attributes per project

    # Relations
    events = relationship("PersonnelEvent", back_populates="personnel", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Personnel(id={self.id}, nom={self.nom}, prenom={self.prenom}, grade={self.grade}, num_recrutement={self.num_recrutement})>"


class VehicleRegistry(Base):
    """Registre des véhicules (champs legacy harmonisés)."""
    __tablename__ = "vehicle_registry"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Identification du Véhicule (colonnes harmonisées en français)
    matricule = Column(String(20), unique=True, nullable=False, index=True)  # Immatriculation/Plaque
    marque = Column(String(50), nullable=False)  # Ex: Toyota
    modele = Column(String(50), nullable=False)  # Ex: Land Cruiser
    couleur = Column(String(30), nullable=True)  # Couleur du véhicule
    
    # Classification (harmonisée avec Personnel)
    categorie = Column(
        String(50),  # "civil" ou "militaire"
        default="civil",
        nullable=False,
        index=True
    )
    
    # Attributs spécifiques militaires (optionnels)
    unite = Column(String(100), nullable=True)  # Unit / department label
    sous_categorie_militaire = Column(
        String(30),  # "operationnel" | "personnel"
        nullable=True,
        index=True,
    )
    
    # Statut (harmonisé avec Personnel)
    statut = Column(
        String(50),  # "actif", "hors_service", "maintenance"
        default="actif",
        nullable=False,
        index=True
    )
    photo_path = Column(String(255), nullable=True)

    # Signalement optionnel
    is_whitelisted = Column(Boolean, default=False, index=True)
    is_blacklisted = Column(Boolean, default=False, index=True)
    blacklist_reason = Column(String(255), nullable=True)
    is_flagged = Column(Boolean, default=False, index=True)
    flag_reason = Column(String(255), nullable=True)
    
    # Métadonnées (harmonisées)
    date_enregistrement = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    date_modification = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    entries = relationship("VehicleEntry", back_populates="vehicle_registry", cascade="all, delete-orphan", foreign_keys="VehicleEntry.vehicle_registry_id")
    images = relationship("VehicleRegistryImage", back_populates="vehicle_registry", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<VehicleRegistry(id={self.id}, matricule={self.matricule}, categorie={self.categorie}, statut={self.statut})>"


class PersonnelEvent(Base):
    """Modèle pour les événements entrée/sortie personnel"""
    __tablename__ = "personnel_events"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Références
    personnel_id = Column(Integer, ForeignKey("personnel.id"), nullable=False, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=True)
    
    # Détection
    direction = Column(String(20), nullable=False)  # "entrée", "sortie"
    confidence = Column(Float, default=0.0)  # Reconnaissance faciale
    method = Column(String(30), default="lbph")  # "lbph", "face_recognition"
    
    # Timestamp
    detected_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Localisation
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    # Méta
    notes = Column(Text, nullable=True)
    
    # Relations
    personnel = relationship("Personnel", back_populates="events")
    camera = relationship("Camera")
    event = relationship("Event")

    def __repr__(self):
        return f"<PersonnelEvent(id={self.id}, personnel_id={self.personnel_id}, direction={self.direction})>"


class VehicleEntry(Base):
    """Modèle pour les événements entrée/sortie véhicules"""
    __tablename__ = "vehicle_entries"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Lien optionnel vers registre de véhicule (si enregistré)
    vehicle_registry_id = Column(Integer, ForeignKey("vehicle_registry.id"), nullable=True, index=True)
    
    # Identification véhicule (pour véhicules non enregistrés ou détection)
    license_plate = Column(String(50), nullable=False, index=True)
    vehicle_type = Column(String(50), nullable=True)  # "car", "truck", "bus"
    brand = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    color = Column(String(50), nullable=True)
    
    # Entrée/Sortie
    entry_camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    exit_camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    
    entry_time = Column(DateTime(timezone=True), nullable=False, index=True)
    exit_time = Column(DateTime(timezone=True), nullable=True, index=True)
    
    entry_confidence = Column(Float, default=0.0)
    exit_confidence = Column(Float, nullable=True)
    
    # Durée du séjour
    duration_minutes = Column(Integer, nullable=True)
    
    # Statut
    status = Column(String(20), default="active")  # "active", "exited"
    
    # Métadonnées
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    vehicle_registry = relationship("VehicleRegistry", back_populates="entries")

    def __repr__(self):
        return f"<VehicleEntry(id={self.id}, plate={self.license_plate}, status={self.status})>"


class FaceImage(Base):
    """Multi-image dataset row for one personnel face sample."""
    __tablename__ = "face_images"

    id = Column(Integer, primary_key=True, index=True)
    personnel_id = Column(Integer, ForeignKey("personnel.id"), nullable=False, index=True)
    image_path = Column(String(255), nullable=False)

    pose_label = Column(String(20), default="front", index=True)
    yaw = Column(Float, nullable=True)
    pitch = Column(Float, nullable=True)
    roll = Column(Float, nullable=True)

    quality_score = Column(Float, nullable=True)
    detector_score = Column(Float, nullable=True)
    is_reference = Column(Boolean, default=False, index=True)
    source = Column(String(30), default="manual")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    personnel = relationship("Personnel")

    def __repr__(self):
        return f"<FaceImage(id={self.id}, personnel_id={self.personnel_id}, pose={self.pose_label})>"


class VehicleRegistryImage(Base):
    """Multi-image dataset row for one vehicle registry sample."""
    __tablename__ = "vehicle_registry_images"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_registry_id = Column(Integer, ForeignKey("vehicle_registry.id"), nullable=False, index=True)
    image_path = Column(String(255), nullable=False)

    view_label = Column(String(20), default="front", index=True)
    quality_score = Column(Float, nullable=True)
    is_reference = Column(Boolean, default=False, index=True)
    source = Column(String(30), default="manual")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    vehicle_registry = relationship("VehicleRegistry", back_populates="images")

    def __repr__(self):
        return f"<VehicleRegistryImage(id={self.id}, vehicle_registry_id={self.vehicle_registry_id}, view={self.view_label})>"


class FaceEncoding(Base):
    """Modèle pour stocker les embeddings faciaux"""
    __tablename__ = "face_encodings"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Référence personnel
    personnel_id = Column(Integer, ForeignKey("personnel.id"), nullable=False, index=True)
    face_image_id = Column(Integer, ForeignKey("face_images.id"), nullable=True, index=True)
    
    # Encodage facial (vecteur de features)
    encoding_vector = Column(JSON, nullable=False)  # List[float]
    embedding_vector = Column(_face_embedding_column_type(), nullable=True)
    embedding_dim = Column(Integer, default=512)
    model_name = Column(String(50), default="arcface")
    
    # Métadonnées
    photo_hash = Column(String(64), unique=True, nullable=True, index=True)
    is_primary = Column(Boolean, default=True, index=True)  # Photo principale
    is_active = Column(Boolean, default=True, index=True)
    detector_score = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)  # Qualité de détection (0-1)
    
    # Timing
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    personnel = relationship("Personnel")
    face_image = relationship("FaceImage")

    def __repr__(self):
        return f"<FaceEncoding(id={self.id}, personnel_id={self.personnel_id}, model={self.model_name})>"


class FaceDetection(Base):
    """Modèle pour historiser les détections faciales"""
    __tablename__ = "face_detections"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Références
    personnel_id = Column(Integer, ForeignKey("personnel.id"), nullable=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True, index=True)
    track_id = Column(Integer, nullable=True, index=True)
    
    # Reconnaissance
    face_encoding = Column(JSON, nullable=False)  # Vecteur détecté
    confidence = Column(Float, default=0.0)  # Distance euclidienne / similarité (0-1)
    match_quality = Column(String(20), nullable=True)  # "high", "medium", "low"
    
    # Image
    image_path = Column(String(255), nullable=True)
    thumbnail_path = Column(String(255), nullable=True)
    face_bbox = Column(JSON, nullable=True)  # {"x": int, "y": int, "w": int, "h": int}
    person_bbox = Column(JSON, nullable=True)  # {"x": int, "y": int, "w": int, "h": int}
    appearance_top_color = Column(String(32), nullable=True, index=True)
    appearance_bottom_color = Column(String(32), nullable=True, index=True)
    has_backpack = Column(Boolean, nullable=True, index=True)
    has_hat = Column(Boolean, nullable=True, index=True)
    appearance_embedding = Column(JSON, nullable=True)
    
    # Timing
    detected_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Status
    is_authorized = Column(Boolean, nullable=True)  # None si inconnu, True/False si identifié
    is_blacklisted = Column(Boolean, default=False)
    
    # Localisation
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Relations
    personnel = relationship("Personnel")
    camera = relationship("Camera")
    zone = relationship("Zone")

    def __repr__(self):
        return (
            f"<FaceDetection(id={self.id}, personnel_id={self.personnel_id}, "
            f"track_id={self.track_id}, confidence={self.confidence})>"
        )


class UnknownDetection(Base):
    """Unknown detections waiting for human identity resolution."""
    __tablename__ = "unknown_detections"

    id = Column(Integer, primary_key=True, index=True)

    detection_type = Column(String(20), nullable=False, index=True)  # face | vehicle
    image_path = Column(String(255), nullable=False)
    image_hash = Column(String(64), nullable=True, index=True)

    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True, index=True)
    source_table = Column(String(50), nullable=True, index=True)
    source_detection_id = Column(Integer, nullable=True, index=True)

    confidence = Column(Float, default=0.0, nullable=False)
    bbox = Column(JSON, nullable=True)

    is_resolved = Column(Boolean, default=False, nullable=False, index=True)
    is_ignored = Column(Boolean, default=False, nullable=False, index=True)
    resolved_label = Column(String(120), nullable=True)
    resolved_entity_type = Column(String(30), nullable=True)  # personnel | vehicle_registry
    resolved_entity_id = Column(Integer, nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True, index=True)

    notes = Column(Text, nullable=True)
    extra_data = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    camera = relationship("Camera")
    zone = relationship("Zone")
    resolved_by = relationship("User")

    def __repr__(self):
        return (
            f"<UnknownDetection(id={self.id}, type={self.detection_type}, "
            f"camera_id={self.camera_id}, resolved={self.is_resolved}, ignored={self.is_ignored})>"
        )


class VehicleDetection(Base):
    """Modèle pour historiser les détections de véhicules/plaques"""
    __tablename__ = "vehicle_detections"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Plaque / Véhicule
    license_plate = Column(String(50), nullable=True, index=True)
    plate_confidence = Column(Float, default=0.0)
    vehicle_type = Column(String(50), nullable=True)  # "car", "truck", "bus"
    color = Column(String(50), nullable=True)
    
    # Références
    vehicle_entry_id = Column(Integer, ForeignKey("vehicle_entries.id"), nullable=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True, index=True)
    
    # Image
    image_path = Column(String(255), nullable=True)
    thumbnail_path = Column(String(255), nullable=True)
    vehicle_bbox = Column(JSON, nullable=True)  # {"x", "y", "w", "h"}
    plate_bbox = Column(JSON, nullable=True)
    
    # Timing
    detected_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Localisation
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Relations
    vehicle_entry = relationship("VehicleEntry")
    camera = relationship("Camera")
    zone = relationship("Zone")

    def __repr__(self):
        return f"<VehicleDetection(id={self.id}, plate={self.license_plate}, confidence={self.plate_confidence})>"


class VehicleEvent(Base):
    """Historique temps-reel de reconnaissance plaque et type civil/military."""
    __tablename__ = "vehicle_events"

    id = Column(Integer, primary_key=True, index=True)

    plate_number = Column(String(50), nullable=True, index=True)
    plate_type = Column(String(20), nullable=False, default="unknown", index=True)  # civil | military | unknown
    confidence = Column(Float, default=0.0)

    vehicle_detected = Column(Boolean, default=True, index=True)
    vehicle_type = Column(String(50), nullable=True)
    body_style = Column(String(50), nullable=True, index=True)
    dominant_color = Column(String(30), nullable=True, index=True)
    brand = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=True, index=True)
    vehicle_confidence = Column(Float, default=0.0)
    vehicle_bbox = Column(JSON, nullable=True)

    plate_confidence = Column(Float, default=0.0)
    plate_bbox = Column(JSON, nullable=True)
    raw_plate_text = Column(String(120), nullable=True)
    normalized_plate = Column(String(80), nullable=True, index=True)

    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    snapshot_path = Column(String(255), nullable=True)

    severity = Column(String(20), default="info", index=True)
    is_priority = Column(Boolean, default=False, index=True)
    security_tag = Column(String(50), nullable=True, index=True)
    reason = Column(String(120), nullable=True)
    matched_registry = Column(Boolean, default=False, index=True)
    consistency_score = Column(Float, default=0.0, index=True)
    consistency_level = Column(String(20), default="low", index=True)
    consistency_flags = Column(JSON, nullable=True)
    anomaly_detected = Column(Boolean, default=False, index=True)
    anomaly_level = Column(String(20), default="none", index=True)
    anomaly_reason = Column(String(160), nullable=True)
    anomaly_flags = Column(JSON, nullable=True)

    pipeline_meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    camera = relationship("Camera")
    zone = relationship("Zone")
    site = relationship("Site", back_populates="vehicle_events")

    def __repr__(self):
        return f"<VehicleEvent(id={self.id}, plate={self.plate_number}, type={self.plate_type})>"


class VehicleAccessLog(Base):
    """Decision log for security-gate access control."""
    __tablename__ = "vehicle_access_logs"

    id = Column(Integer, primary_key=True, index=True)

    event_id = Column(Integer, ForeignKey("vehicle_events.id"), nullable=True, index=True)
    plate_number = Column(String(50), nullable=True, index=True)
    normalized_plate = Column(String(80), nullable=True, index=True)
    plate_type = Column(String(20), nullable=False, default="unknown", index=True)

    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    gate_id = Column(String(60), nullable=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    direction = Column(String(12), nullable=False, default="UNKNOWN", index=True)  # IN | OUT | UNKNOWN

    decision = Column(String(30), nullable=False, default="denied", index=True)  # allowed | denied | review_required | manual_override
    confidence_score = Column(Float, default=0.0)
    vehicle_detected = Column(Boolean, default=True)
    vehicle_type = Column(String(50), nullable=True)
    plate_confidence = Column(Float, default=0.0)

    security_tag = Column(String(50), nullable=True, index=True)
    reason = Column(String(160), nullable=True)
    snapshot_path = Column(String(255), nullable=True)

    registry_vehicle_id = Column(Integer, ForeignKey("vehicle_registry.id"), nullable=True, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    operator_note = Column(Text, nullable=True)

    dominant_color = Column(String(30), nullable=True)
    visual_consistency = Column(Float, nullable=True)
    audit_meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    event = relationship("VehicleEvent")
    camera = relationship("Camera")
    site = relationship("Site", back_populates="vehicle_access_logs")
    registry_vehicle = relationship("VehicleRegistry")
    operator = relationship("User")

    def __repr__(self):
        return f"<VehicleAccessLog(id={self.id}, decision={self.decision}, plate={self.plate_number})>"


class SecurityAlert(Base):
    """Security alert generated by access-control pipeline."""
    __tablename__ = "security_alerts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)

    type = Column(String(40), nullable=False, index=True)  # blacklist | mismatch | low_confidence | unknown_plate | spoof_suspected
    plate_number = Column(String(50), nullable=True, index=True)
    normalized_plate = Column(String(80), nullable=True, index=True)

    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    gate_id = Column(String(60), nullable=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    severity_level = Column(String(20), nullable=False, default="high", index=True)  # low | medium | high | critical
    resolution_status = Column(String(20), nullable=False, default="open", index=True)  # open | in_review | resolved

    message = Column(String(255), nullable=True)
    event_id = Column(Integer, ForeignKey("vehicle_events.id"), nullable=True, index=True)
    access_log_id = Column(Integer, ForeignKey("vehicle_access_logs.id"), nullable=True, index=True)
    handled_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    handled_at = Column(DateTime(timezone=True), nullable=True)
    snapshot_path = Column(String(255), nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    tenant = relationship("Tenant", back_populates="security_alerts")
    camera = relationship("Camera")
    site = relationship("Site", back_populates="security_alerts")
    event = relationship("VehicleEvent")
    access_log = relationship("VehicleAccessLog")
    handler = relationship("User")

    def __repr__(self):
        return f"<SecurityAlert(id={self.id}, type={self.type}, severity={self.severity_level})>"


class VehicleEventFrame(Base):
    """Forensic frame history linked to vehicle recognition events."""
    __tablename__ = "vehicle_event_frames"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("vehicle_events.id"), nullable=False, index=True)
    frame_path = Column(String(255), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    stage = Column(String(30), nullable=False, default="full_frame", index=True)  # full_frame | plate_crop | tamper
    ocr_text = Column(String(120), nullable=True)
    decision = Column(String(30), nullable=True)
    frame_meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    event = relationship("VehicleEvent")

    def __repr__(self):
        return f"<VehicleEventFrame(id={self.id}, event_id={self.event_id}, stage={self.stage})>"


class SystemHealthLog(Base):
    """Periodic system health checks (production monitoring/audit)."""
    __tablename__ = "system_health_logs"

    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String(80), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="unknown", index=True)  # healthy | degraded | down
    last_check = Column(DateTime(timezone=True), nullable=False, index=True)
    latency_ms = Column(Float, nullable=True)
    error_count = Column(Integer, default=0)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self):
        return f"<SystemHealthLog(id={self.id}, service={self.service_name}, status={self.status})>"


class ZoneOccupancy(Base):
    """Modèle pour tracker l'occupant d'une zone"""
    __tablename__ = "zone_occupancy"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Zone
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=False, index=True)
    
    # Occupant
    personnel_id = Column(Integer, ForeignKey("personnel.id"), nullable=True, index=True)
    vehicle_entry_id = Column(Integer, ForeignKey("vehicle_entries.id"), nullable=True, index=True)
    
    # Temps
    entry_time = Column(DateTime(timezone=True), nullable=False)
    exit_time = Column(DateTime(timezone=True), nullable=True)
    
    # Statut
    is_active = Column(Boolean, default=True, index=True)
    
    # Relations
    zone = relationship("Zone")
    personnel = relationship("Personnel")
    vehicle_entry = relationship("VehicleEntry")

    def __repr__(self):
        return f"<ZoneOccupancy(id={self.id}, zone_id={self.zone_id})>"


class Alert(Base):
    """Modèle pour les alertes persistées en base de données."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)

    # Références
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True, index=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True, index=True)
    rule_type = Column(String(50), nullable=False, index=True)  # "motion", "face", "vehicle", etc.

    # Contenu de l'alerte
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    severity = Column(String(20), default="info", index=True)  # "info", "warning", "critical"

    # Métadonnées temporelles
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # État
    is_acknowledged = Column(Boolean, default=False, index=True)
    is_resolved = Column(Boolean, default=False, index=True)

    # Données supplémentaires
    extra_data = Column(JSON, nullable=True)

    # Relations
    tenant = relationship("Tenant")
    camera = relationship("Camera")
    zone = relationship("Zone")
    acknowledger = relationship("User")

    # Index composite pour les requêtes de stats
    __table_args__ = (
        Index('ix_alerts_timestamp_severity', 'timestamp', 'severity'),
        Index('ix_alerts_camera_timestamp', 'camera_id', 'timestamp'),
        Index('ix_alerts_tenant_timestamp', 'tenant_id', 'timestamp'),
    )

    def __repr__(self):
        return f"<Alert(id={self.id}, severity={self.severity}, timestamp={self.timestamp})>"


class FamilyMember(Base):
    """Modèle pour les membres de la famille (mode maison)"""
    __tablename__ = "family_members"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Informations personnelles
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    full_name = Column(String(100), nullable=False, index=True)
    family_relationship = Column(String(30), nullable=True)  # "spouse", "child", "parent", "sibling", etc.
    date_of_birth = Column(DateTime(timezone=True), nullable=True)
    gender = Column(String(20), nullable=True)  # "male", "female", "other"

    # Contact
    email = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)

    # Statut
    is_active = Column(Boolean, default=True, index=True)
    is_authorized = Column(Boolean, default=True, index=True)

    # Métadonnées
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relations
    user = relationship("User", back_populates="family_members")

    def __repr__(self):
        return f"<FamilyMember(id={self.id}, name={self.full_name}, relationship={self.family_relationship})>"


class Employee(Base):
    """Modèle pour les employés (mode société)"""
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Informations personnelles
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    full_name = Column(String(100), nullable=False, index=True)
    employee_id = Column(String(20), unique=True, nullable=True, index=True)
    department = Column(String(50), nullable=True, index=True)
    position = Column(String(50), nullable=True)

    # Contact
    email = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)

    # Statut
    is_active = Column(Boolean, default=True, index=True)
    is_authorized = Column(Boolean, default=True, index=True)
    hire_date = Column(DateTime(timezone=True), nullable=True)
    termination_date = Column(DateTime(timezone=True), nullable=True)

    # Métadonnées
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relations
    user = relationship("User", back_populates="employees")

    def __repr__(self):
        return f"<Employee(id={self.id}, name={self.full_name}, dept={self.department})>"


class UserVehicle(Base):
    """Modèle unifié pour les véhicules avec propriété et catégories"""
    __tablename__ = "user_vehicles"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Identification
    license_plate = Column(String(20), nullable=False, index=True, unique=True)
    make = Column(String(50), nullable=True)  # Toyota, BMW, etc.
    model = Column(String(50), nullable=True)  # Camry, X5, etc.
    year = Column(Integer, nullable=True)
    color = Column(String(30), nullable=True)

    # Catégorisation par mode
    vehicle_type = Column(String(30), nullable=True, index=True)  # "personal", "company", "employee", "visitor"
    category = Column(String(30), nullable=True, index=True)  # "car", "truck", "motorcycle", "van"

    # Statut et autorisation
    is_active = Column(Boolean, default=True, index=True)
    is_authorized = Column(Boolean, default=True, index=True)
    is_blacklisted = Column(Boolean, default=False, index=True)
    blacklist_reason = Column(Text, nullable=True)

    # Métadonnées
    registration_date = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relations
    owner = relationship("User", back_populates="vehicles")

    def __repr__(self):
        return f"<Vehicle(id={self.id}, plate={self.license_plate}, type={self.vehicle_type})>"


class SetupConfig(Base):
    """Configuration de setup pour la détection automatique des plaques"""
    __tablename__ = "setup_config"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, unique=True)

    # Localisation pour détection automatique des formats de plaque
    country_code = Column(String(3), nullable=True, index=True)  # ISO 3166-1 alpha-3
    region_code = Column(String(10), nullable=True)  # State/province code
    city = Column(String(100), nullable=True)

    # Coordonnées GPS (optionnel pour validation)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Configuration des formats de plaque par pays
    license_plate_config = Column(JSON, nullable=True)  # Format patterns, validation rules

    # Métadonnées
    detected_at = Column(DateTime(timezone=True), nullable=True)  # When auto-detection ran
    manually_set = Column(Boolean, default=False)  # True if user manually configured
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relations
    user = relationship("User", uselist=False)  # One-to-one relationship

    def __repr__(self):
        return f"<SetupConfig(user_id={self.user_id}, country={self.country_code})>"
