# vms/backend/crud.py - Opérations CRUD (Create, Read, Update, Delete)

from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
import re
from typing import List, Optional
from .core.security import hash_password, verify_password
from . import models, schemas

# ============= USER CRUD =============

VALID_USER_ROLES = {"admin", "supervisor", "operator", "viewer"}
VALID_EVENT_DECISIONS = {"allowed", "denied", "review", "review_required", "manual_override"}

def _slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text or "tenant"

def get_tenant_by_id(db: Session, tenant_id: int) -> Optional[models.Tenant]:
    return db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()

def get_tenant_by_slug(db: Session, slug: str) -> Optional[models.Tenant]:
    return db.query(models.Tenant).filter(models.Tenant.slug == slug).first()

def create_tenant(
    db: Session,
    name: str,
    *,
    slug: Optional[str] = None,
    plan: str = "starter",
    project_type: Optional[str] = None,
) -> models.Tenant:
    if not name:
        raise ValueError("Tenant name is required")
    base_slug = _slugify(slug or name)
    candidate = base_slug
    counter = 1
    while db.query(models.Tenant).filter(models.Tenant.slug == candidate).first():
        counter += 1
        candidate = f"{base_slug}-{counter}"
    tenant = models.Tenant(
        name=name,
        slug=candidate,
        plan=str(plan or "starter").lower(),
        project_type=str(project_type or "soc").lower(),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant

def ensure_default_tenant(db: Session) -> models.Tenant:
    default_slug = "default"
    tenant = db.query(models.Tenant).filter(models.Tenant.slug == default_slug).first()
    if tenant:
        return tenant
    tenant = models.Tenant(
        name="Default Tenant",
        slug=default_slug,
        plan="starter",
        is_active=True,
        project_type="soc",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant

def ensure_user_tenant(db: Session, user: models.User) -> models.User:
    if user.tenant_id:
        return user
    tenant = ensure_default_tenant(db)
    user.tenant_id = int(tenant.id)
    db.commit()
    db.refresh(user)
    return user



def _normalize_user_role(role: Optional[str]) -> str:
    raw_value = getattr(role, "value", role)
    normalized = str(raw_value or "operator").strip().lower()
    if normalized not in VALID_USER_ROLES:
        return "operator"
    return normalized


def _normalize_event_decision(decision: Optional[str]) -> str:
    raw_value = getattr(decision, "value", decision)
    normalized = str(raw_value or "review").strip().lower()
    if normalized not in VALID_EVENT_DECISIONS:
        return "review"
    return normalized

def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    """Obtenir un utilisateur par nom"""
    return db.query(models.User).filter(models.User.username == username).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[models.User]:
    """Obtenir un utilisateur par ID"""
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    """Obtenir un utilisateur par email"""
    return db.query(models.User).filter(models.User.email == email).first()


def get_all_users(db: Session, skip: int = 0, limit: int = 100, tenant_id: Optional[int] = None) -> List[models.User]:
    """Obtenir tous les utilisateurs"""
    query = db.query(models.User)
    if tenant_id is not None:
        query = query.filter(models.User.tenant_id == tenant_id)
    return query.offset(skip).limit(limit).all()

def create_user(db: Session, user: schemas.UserCreate) -> models.User:
    """Cr?er un nouvel utilisateur"""
    existing = get_user_by_username(db, user.username)
    if existing:
        raise ValueError(f"Username '{user.username}' already exists")

    role = _normalize_user_role(getattr(user, "role", "operator"))
    requested_admin = getattr(user, "is_admin", None)
    is_admin = bool(requested_admin) if requested_admin is not None else role == "admin"
    if is_admin:
        role = "admin"

    tenant_id = getattr(user, "tenant_id", None)
    resolved_tenant_id: Optional[int]
    if tenant_id is not None:
        tenant = get_tenant_by_id(db, int(tenant_id))
        if not tenant:
            raise ValueError("Tenant not found")
        resolved_tenant_id = int(tenant.id)
    else:
        resolved_tenant_id = int(ensure_default_tenant(db).id)

    db_user = models.User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=role,
        hashed_password=hash_password(user.password),
        is_active=user.is_active,
        is_admin=is_admin,
        tenant_id=resolved_tenant_id,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user(db: Session, username: str, password: str) -> Optional[models.User]:
    """Authentifier un utilisateur"""
    user = get_user_by_username(db, username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def update_user(db: Session, user_id: int, user_update: schemas.UserUpdate) -> Optional[models.User]:
    """Mettre à jour un utilisateur"""
    db_user = get_user_by_id(db, user_id)
    if not db_user:
        return None
    
    if user_update.email:
        db_user.email = user_update.email
    if user_update.full_name:
        db_user.full_name = user_update.full_name
    if user_update.role is not None:
        db_user.role = _normalize_user_role(getattr(user_update.role, "value", user_update.role))
        db_user.is_admin = db_user.role == "admin"
    if user_update.is_admin is not None:
        db_user.is_admin = bool(user_update.is_admin)
        if db_user.is_admin:
            db_user.role = "admin"
        elif db_user.role == "admin":
            db_user.role = "operator"
    if user_update.password:
        db_user.hashed_password = hash_password(user_update.password)
    if user_update.is_active is not None:
        db_user.is_active = user_update.is_active
    
    db.commit()
    db.refresh(db_user)
    return db_user


def delete_user(db: Session, user_id: int) -> bool:
    """Supprimer un utilisateur"""
    db_user = get_user_by_id(db, user_id)
    if not db_user:
        return False

    blocking_references = []
    camera_count = db.query(models.Camera).filter(models.Camera.owner_id == user_id).count()
    if camera_count:
        blocking_references.append(f"{camera_count} caméra(s)")

    event_count = db.query(models.Event).filter(models.Event.creator_id == user_id).count()
    if event_count:
        blocking_references.append(f"{event_count} événement(s)")

    if blocking_references:
        raise ValueError(
            "Impossible de supprimer cet utilisateur: "
            + ", ".join(blocking_references)
            + " lui sont encore rattaché(s). Réaffectez ces données avant suppression."
        )

    try:
        db.query(models.RefreshToken).filter(models.RefreshToken.user_id == user_id).delete(synchronize_session=False)
        db.query(models.Notification).filter(models.Notification.user_id == user_id).delete(synchronize_session=False)

        db.query(models.AuditLog).filter(models.AuditLog.user_id == user_id).update(
            {models.AuditLog.user_id: None},
            synchronize_session=False,
        )
        db.query(models.UnknownDetection).filter(
            models.UnknownDetection.resolved_by_user_id == user_id
        ).update(
            {models.UnknownDetection.resolved_by_user_id: None},
            synchronize_session=False,
        )
        db.query(models.VehicleAccessLog).filter(models.VehicleAccessLog.operator_id == user_id).update(
            {models.VehicleAccessLog.operator_id: None},
            synchronize_session=False,
        )
        db.query(models.SecurityAlert).filter(models.SecurityAlert.handled_by == user_id).update(
            {models.SecurityAlert.handled_by: None},
            synchronize_session=False,
        )

        db.delete(db_user)
        db.commit()
        return True
    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "Impossible de supprimer cet utilisateur: il est référencé par des données métiers. "
            "Désactivez le compte ou réaffectez les références avant suppression."
        ) from exc


# ============= SITE CRUD =============

def get_site_by_id(db: Session, site_id: int, tenant_id: Optional[int] = None) -> Optional[models.Site]:
    """Obtenir un site par ID."""
    query = db.query(models.Site).filter(models.Site.id == site_id)
    if tenant_id is not None:
        query = query.filter(models.Site.tenant_id == tenant_id)
    return query.first()

def get_all_sites(db: Session, skip: int = 0, limit: int = 100, tenant_id: Optional[int] = None) -> List[models.Site]:
    """Obtenir tous les sites."""
    query = db.query(models.Site)
    if tenant_id is not None:
        query = query.filter(models.Site.tenant_id == tenant_id)
    return query.order_by(models.Site.id.asc()).offset(skip).limit(limit).all()

def create_site(db: Session, site: schemas.SiteCreate, tenant_id: Optional[int] = None) -> models.Site:
    """Cr?er un nouveau site."""
    data = site.model_dump()
    if tenant_id is not None:
        data["tenant_id"] = tenant_id
    db_site = models.Site(**data)
    db.add(db_site)
    db.commit()
    db.refresh(db_site)
    return db_site

def update_site(db: Session, site_id: int, site_update: schemas.SiteUpdate) -> Optional[models.Site]:
    """Mettre à jour un site."""
    db_site = get_site_by_id(db, site_id)
    if not db_site:
        return None

    update_data = site_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_site, key, value)

    db.commit()
    db.refresh(db_site)
    return db_site


def delete_site(db: Session, site_id: int) -> bool:
    """Supprimer un site."""
    db_site = get_site_by_id(db, site_id)
    if not db_site:
        return False

    db.delete(db_site)
    db.commit()
    return True


# ============= CAMERA CRUD =============

def get_camera_by_id(db: Session, camera_id: int, tenant_id: Optional[int] = None) -> Optional[models.Camera]:
    """Obtenir une cam?ra par ID"""
    query = db.query(models.Camera).filter(models.Camera.id == camera_id)
    if tenant_id is not None:
        query = query.filter(models.Camera.tenant_id == tenant_id)
    return query.first()

def get_all_cameras(db: Session, skip: int = 0, limit: int = 100, owner_id: Optional[int] = None, tenant_id: Optional[int] = None) -> List[models.Camera]:
    """Obtenir toutes les cam?ras"""
    query = db.query(models.Camera)
    if tenant_id is not None:
        query = query.filter(models.Camera.tenant_id == tenant_id)
    if owner_id:
        query = query.filter(models.Camera.owner_id == owner_id)
    return query.offset(skip).limit(limit).all()

def get_cameras_by_site(db: Session, site_id: int, active_only: bool = False, tenant_id: Optional[int] = None) -> List[models.Camera]:
    """Obtenir les cam?ras d'un site."""
    query = db.query(models.Camera).filter(models.Camera.site_id == site_id)
    if tenant_id is not None:
        query = query.filter(models.Camera.tenant_id == tenant_id)
    if active_only:
        query = query.filter(models.Camera.is_active == True)
    return query.order_by(models.Camera.id.asc()).all()

def get_active_cameras(db: Session, tenant_id: Optional[int] = None) -> List[models.Camera]:
    """Obtenir les cam?ras actives"""
    query = db.query(models.Camera).filter(models.Camera.is_active == True)
    if tenant_id is not None:
        query = query.filter(models.Camera.tenant_id == tenant_id)
    return query.all()

def get_cameras_by_zone(db: Session, zone_name: str, tenant_id: Optional[int] = None) -> List[models.Camera]:
    """Obtenir les cam?ras d'une zone"""
    query = db.query(models.Camera).filter(models.Camera.zone_name == zone_name)
    if tenant_id is not None:
        query = query.filter(models.Camera.tenant_id == tenant_id)
    return query.all()

def create_camera(db: Session, camera: schemas.CameraCreate, owner_id: int, tenant_id: Optional[int] = None) -> models.Camera:
    """Cr?er une nouvelle cam?ra"""
    data = camera.model_dump()

    if tenant_id is not None:
        data["tenant_id"] = tenant_id

    zone_id = data.get("zone_id")
    site_id = data.get("site_id")
    if zone_id is not None:
        db_zone = get_zone_by_id(db, zone_id, tenant_id=tenant_id) if tenant_id is not None else get_zone_by_id(db, zone_id)
        if not db_zone:
            raise ValueError("Zone not found")
        if tenant_id is None and getattr(db_zone, "tenant_id", None):
            tenant_id = int(db_zone.tenant_id)
            data["tenant_id"] = tenant_id
        if tenant_id is not None and getattr(db_zone, "tenant_id", None) not in (None, tenant_id):
            raise ValueError("Zone belongs to another tenant")
        if site_id is None:
            site_id = db_zone.site_id
        if not data.get("zone_name"):
            data["zone_name"] = db_zone.name

    if site_id is not None:
        db_site = get_site_by_id(db, site_id, tenant_id=tenant_id) if tenant_id is not None else get_site_by_id(db, site_id)
        if not db_site:
            raise ValueError("Site not found")
        if tenant_id is None and getattr(db_site, "tenant_id", None):
            tenant_id = int(db_site.tenant_id)
            data["tenant_id"] = tenant_id
        if tenant_id is not None and getattr(db_site, "tenant_id", None) not in (None, tenant_id):
            raise ValueError("Site belongs to another tenant")
    data["site_id"] = site_id

    db_camera = models.Camera(
        **data,
        owner_id=owner_id
    )
    db.add(db_camera)
    db.commit()
    db.refresh(db_camera)
    return db_camera

def update_camera(db: Session, camera_id: int, camera_update: schemas.CameraUpdate) -> Optional[models.Camera]:
    """Mettre à jour une caméra"""
    db_camera = get_camera_by_id(db, camera_id)
    if not db_camera:
        return None
    
    update_data = camera_update.model_dump(exclude_unset=True)
    zone_id = update_data.get("zone_id")
    site_id = update_data.get("site_id", db_camera.site_id)

    if zone_id is not None:
        db_zone = get_zone_by_id(db, zone_id)
        if not db_zone:
            raise ValueError("Zone not found")
        if "site_id" not in update_data:
            site_id = db_zone.site_id
            update_data["site_id"] = site_id
        if "zone_name" not in update_data:
            update_data["zone_name"] = db_zone.name

    if site_id is not None and not get_site_by_id(db, site_id):
        raise ValueError("Site not found")

    for key, value in update_data.items():
        setattr(db_camera, key, value)
    
    db_camera.updated_at = datetime.now()
    db.commit()
    db.refresh(db_camera)
    return db_camera


def delete_camera(db: Session, camera_id: int) -> bool:
    """Supprimer une caméra"""
    db_camera = get_camera_by_id(db, camera_id)
    if not db_camera:
        return False
    
    db.delete(db_camera)
    db.commit()
    return True


def update_camera_activity(db: Session, camera_id: int) -> Optional[models.Camera]:
    """Mettre à jour l'activité dernière d'une caméra"""
    db_camera = get_camera_by_id(db, camera_id)
    if db_camera:
        db_camera.last_activity = datetime.now()
        db.commit()
        db.refresh(db_camera)
    return db_camera


# ============= ZONE CRUD =============

def get_zone_by_id(db: Session, zone_id: int, tenant_id: Optional[int] = None) -> Optional[models.Zone]:
    """Obtenir une zone par ID"""
    query = db.query(models.Zone).filter(models.Zone.id == zone_id)
    if tenant_id is not None:
        query = query.filter(models.Zone.tenant_id == tenant_id)
    return query.first()

def get_zones_by_camera(db: Session, camera_id: int) -> List[models.Zone]:
    """Obtenir les zones d'une caméra"""
    return db.query(models.Zone).filter(models.Zone.camera_id == camera_id).all()


def get_zones_by_site(db: Session, site_id: int, active_only: bool = False) -> List[models.Zone]:
    """Obtenir les zones d'un site."""
    query = db.query(models.Zone).filter(models.Zone.site_id == site_id)
    if active_only:
        query = query.filter(models.Zone.is_active == True)
    return query.order_by(models.Zone.id.asc()).all()


def create_zone(db: Session, zone: schemas.ZoneCreate, tenant_id: Optional[int] = None) -> models.Zone:
    """Cr?er une nouvelle zone"""
    data = zone.model_dump()
    camera_id = data.get("camera_id")
    db_camera = get_camera_by_id(db, camera_id, tenant_id=tenant_id) if tenant_id is not None else get_camera_by_id(db, camera_id)
    if not db_camera:
        raise ValueError("Camera not found")

    if tenant_id is None and getattr(db_camera, "tenant_id", None):
        tenant_id = int(db_camera.tenant_id)
    if tenant_id is not None:
        data["tenant_id"] = tenant_id

    if data.get("site_id") is None:
        data["site_id"] = db_camera.site_id
    site_id = data.get("site_id")
    if site_id is not None and not get_site_by_id(db, site_id, tenant_id=tenant_id):
        raise ValueError("Site not found")

    db_zone = models.Zone(**data)
    db.add(db_zone)
    db.commit()
    db.refresh(db_zone)
    if db_camera.zone_id is None:
        db_camera.zone_id = db_zone.id
        if db_camera.site_id is None:
            db_camera.site_id = db_zone.site_id
        db.commit()
    return db_zone

def update_zone(db: Session, zone_id: int, zone_update: schemas.ZoneUpdate) -> Optional[models.Zone]:
    """Mettre à jour une zone"""
    db_zone = get_zone_by_id(db, zone_id)
    if not db_zone:
        return None
    
    update_data = zone_update.model_dump(exclude_unset=True)
    if "camera_id" in update_data:
        db_camera = get_camera_by_id(db, update_data["camera_id"])
        if not db_camera:
            raise ValueError("Camera not found")
        if "site_id" not in update_data and db_camera.site_id is not None:
            update_data["site_id"] = db_camera.site_id

    if "site_id" in update_data and update_data["site_id"] is not None:
        if not get_site_by_id(db, update_data["site_id"]):
            raise ValueError("Site not found")

    for key, value in update_data.items():
        setattr(db_zone, key, value)
    
    db_zone.updated_at = datetime.now()
    db.commit()
    db.refresh(db_zone)
    return db_zone


def delete_zone(db: Session, zone_id: int) -> bool:
    """Supprimer une zone"""
    db_zone = get_zone_by_id(db, zone_id)
    if not db_zone:
        return False
    
    db.delete(db_zone)
    db.commit()
    return True


# ============= EVENT CRUD =============

def get_event_by_id(db: Session, event_id: int, tenant_id: Optional[int] = None) -> Optional[models.Event]:
    """Obtenir un ?v?nement par ID"""
    query = db.query(models.Event).filter(models.Event.id == event_id)
    if tenant_id is not None:
        query = query.filter(models.Event.tenant_id == tenant_id)
    return query.first()

def get_all_events(db: Session, skip: int = 0, limit: int = 100, tenant_id: Optional[int] = None) -> List[models.Event]:
    """Obtenir tous les ?v?nements"""
    query = db.query(models.Event)
    if tenant_id is not None:
        query = query.filter(models.Event.tenant_id == tenant_id)
    return query.order_by(desc(models.Event.detected_at)).offset(skip).limit(limit).all()

def get_events_by_site(
    db: Session,
    site_id: int,
    skip: int = 0,
    limit: int = 100,
    days: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> List[models.Event]:
    """Obtenir les ?v?nements d'un site."""
    query = db.query(models.Event).filter(models.Event.site_id == site_id)
    if tenant_id is not None:
        query = query.filter(models.Event.tenant_id == tenant_id)
    if days is not None:
        since = datetime.now() - timedelta(days=days)
        query = query.filter(models.Event.detected_at >= since)
    return query.order_by(desc(models.Event.detected_at)).offset(skip).limit(limit).all()

def get_events_by_camera(
    db: Session,
    camera_id: int,
    skip: int = 0,
    limit: int = 100,
    days: Optional[int] = None,
    tenant_id: Optional[int] = None,
) -> List[models.Event]:
    """Obtenir les ?v?nements d'une cam?ra, avec pagination optionnelle et filtre temporel."""
    query = db.query(models.Event).filter(models.Event.camera_id == camera_id)
    if tenant_id is not None:
        query = query.filter(models.Event.tenant_id == tenant_id)
    if days is not None:
        since = datetime.now() - timedelta(days=days)
        query = query.filter(models.Event.detected_at >= since)
    return query.order_by(desc(models.Event.detected_at)).offset(skip).limit(limit).all()

def get_events_by_type(db: Session, event_type: str, limit: int = 100) -> List[models.Event]:
    """Obtenir les événements d'un type"""
    return db.query(models.Event).filter(
        models.Event.event_type == event_type
    ).order_by(desc(models.Event.detected_at)).limit(limit).all()


def get_unacknowledged_events(db: Session, tenant_id: Optional[int] = None) -> List[models.Event]:
    """Obtenir les ?v?nements non confirm?s"""
    query = db.query(models.Event).filter(models.Event.is_acknowledged == False)
    if tenant_id is not None:
        query = query.filter(models.Event.tenant_id == tenant_id)
    return query.order_by(desc(models.Event.detected_at)).all()

def get_recent_events(db: Session, hours: int = 24, limit: int = 100, tenant_id: Optional[int] = None) -> List[models.Event]:
    """Obtenir les ?v?nements r?cents"""
    since = datetime.now() - timedelta(hours=hours)
    query = db.query(models.Event).filter(models.Event.detected_at >= since)
    if tenant_id is not None:
        query = query.filter(models.Event.tenant_id == tenant_id)
    return query.order_by(desc(models.Event.detected_at)).limit(limit).all()

def create_event(db: Session, event: schemas.EventCreate, creator_id: int, tenant_id: Optional[int] = None) -> models.Event:
    """Cr?er un nouvel ?v?nement"""
    detected_at = event.detected_at or datetime.now()

    db_camera = get_camera_by_id(db, event.camera_id, tenant_id=tenant_id) if tenant_id is not None else get_camera_by_id(db, event.camera_id)
    if not db_camera:
        raise ValueError("Camera not found")

    if tenant_id is None and getattr(db_camera, "tenant_id", None):
        tenant_id = int(db_camera.tenant_id)
    if tenant_id is not None and getattr(db_camera, "tenant_id", None) not in (None, tenant_id):
        raise ValueError("Camera belongs to another tenant")

    db_zone = None
    if event.zone_id is not None:
        db_zone = get_zone_by_id(db, event.zone_id, tenant_id=tenant_id) if tenant_id is not None else get_zone_by_id(db, event.zone_id)
        if not db_zone:
            raise ValueError("Zone not found")

    site_id = event.site_id
    if site_id is None and db_zone is not None:
        site_id = db_zone.site_id
    if site_id is None:
        site_id = db_camera.site_id
    if site_id is not None and not get_site_by_id(db, site_id, tenant_id=tenant_id):
        raise ValueError("Site not found")

    db_event = models.Event(
        tenant_id=tenant_id,
        camera_id=event.camera_id,
        zone_id=event.zone_id,
        site_id=site_id,
        creator_id=creator_id,
        event_type=event.event_type.value,
        severity=event.severity.value if event.severity else "info",
        decision=_normalize_event_decision(getattr(event, "decision", None)),
        description=event.description,
        detected_objects=event.detected_objects,
        confidence=event.confidence,
        latitude=event.latitude,
        longitude=event.longitude,
        thumbnail_url=event.thumbnail_url,
        video_url=event.video_url,
        snapshot_path=event.snapshot_path,
        extra_data=event.extra_data,
        detected_at=detected_at,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

def update_event(db: Session, event_id: int, event_update: schemas.EventUpdate) -> Optional[models.Event]:
    """Mettre à jour un événement"""
    db_event = get_event_by_id(db, event_id)
    if not db_event:
        return None
    
    if event_update.description is not None:
        db_event.description = event_update.description
    if event_update.severity is not None:
        db_event.severity = event_update.severity.value
    if event_update.decision is not None:
        db_event.decision = _normalize_event_decision(event_update.decision)
    if event_update.is_acknowledged is not None:
        db_event.is_acknowledged = event_update.is_acknowledged
    if event_update.is_archived is not None:
        db_event.is_archived = event_update.is_archived
    
    db_event.updated_at = datetime.now()
    db.commit()
    db.refresh(db_event)
    return db_event


def delete_event(db: Session, event_id: int) -> bool:
    """Supprimer un événement"""
    db_event = get_event_by_id(db, event_id)
    if not db_event:
        return False
    
    db.delete(db_event)
    db.commit()
    return True


def acknowledge_event(db: Session, event_id: int, user_id: Optional[int] = None) -> Optional[models.Event]:
    """Confirmer un événement. `user_id` est accepté pour compatibilité API."""
    return update_event(db, event_id, schemas.EventUpdate(is_acknowledged=True))


def mark_event_as_read(db: Session, event_id: int) -> Optional[models.Event]:
    """Marquer un événement comme lu (alias de acknowledge pour compatibilité)."""
    return acknowledge_event(db, event_id)


def archive_event(db: Session, event_id: int) -> Optional[models.Event]:
    """Archiver un événement"""
    return update_event(db, event_id, schemas.EventUpdate(is_archived=True))



def add_event_comment(
    db: Session,
    event_id: int,
    comment: str,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
) -> Optional[models.Event]:
    """Ajouter un commentaire horodate dans extra_data.comments."""
    db_event = get_event_by_id(db, event_id)
    if not db_event:
        return None

    clean_comment = (comment or "").strip()
    if not clean_comment:
        return db_event

    existing_extra = db_event.extra_data if isinstance(db_event.extra_data, dict) else {}
    comments = existing_extra.get("comments")
    if not isinstance(comments, list):
        comments = []
    comments.append(
        {
            "comment": clean_comment,
            "user_id": user_id,
            "username": username,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    existing_extra["comments"] = comments[-200:]
    db_event.extra_data = existing_extra
    db_event.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(db_event)
    return db_event
# ============= ALERT RULE CRUD =============

def get_alert_rule_by_id(db: Session, rule_id: int) -> Optional[models.AlertRule]:
    """Obtenir une règle d'alerte par ID"""
    return db.query(models.AlertRule).filter(models.AlertRule.id == rule_id).first()


def get_all_alert_rules(db: Session, active_only: bool = False) -> List[models.AlertRule]:
    """Obtenir toutes les règles d'alerte"""
    query = db.query(models.AlertRule)
    if active_only:
        query = query.filter(models.AlertRule.is_active == True)
    return query.all()


def create_alert_rule(db: Session, rule: schemas.AlertRuleCreate) -> models.AlertRule:
    """Créer une nouvelle règle d'alerte"""
    db_rule = models.AlertRule(**rule.model_dump())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule


def update_alert_rule(db: Session, rule_id: int, rule_update: schemas.AlertRuleUpdate) -> Optional[models.AlertRule]:
    """Mettre à jour une règle d'alerte"""
    db_rule = get_alert_rule_by_id(db, rule_id)
    if not db_rule:
        return None
    
    update_data = rule_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_rule, key, value)
    
    db_rule.updated_at = datetime.now()
    db.commit()
    db.refresh(db_rule)
    return db_rule


def delete_alert_rule(db: Session, rule_id: int) -> bool:
    """Supprimer une règle d'alerte"""
    db_rule = get_alert_rule_by_id(db, rule_id)
    if not db_rule:
        return False
    
    db.delete(db_rule)
    db.commit()
    return True


# ============= NOTIFICATION CRUD =============

def get_notification_by_id(db: Session, notif_id: int) -> Optional[models.Notification]:
    """Obtenir une notification par ID"""
    return db.query(models.Notification).filter(models.Notification.id == notif_id).first()


def get_user_notifications(db: Session, user_id: int, unread_only: bool = False) -> List[models.Notification]:
    """Obtenir les notifications d'un utilisateur"""
    query = db.query(models.Notification).filter(models.Notification.user_id == user_id)
    if unread_only:
        query = query.filter(models.Notification.is_read == False)
    return query.order_by(desc(models.Notification.created_at)).all()


def create_notification(db: Session, notif: schemas.NotificationCreate) -> models.Notification:
    """Créer une nouvelle notification"""
    db_notif = models.Notification(**notif.model_dump())
    db.add(db_notif)
    db.commit()
    db.refresh(db_notif)
    return db_notif


def mark_notification_as_read(db: Session, notif_id: int) -> Optional[models.Notification]:
    """Marquer une notification comme lue"""
    db_notif = get_notification_by_id(db, notif_id)
    if db_notif:
        db_notif.is_read = True
        db_notif.read_at = datetime.now()
        db.commit()
        db.refresh(db_notif)
    return db_notif


def delete_notification(db: Session, notif_id: int) -> bool:
    """Supprimer une notification"""
    db_notif = get_notification_by_id(db, notif_id)
    if not db_notif:
        return False
    
    db.delete(db_notif)
    db.commit()
    return True


# ============= SYSTEM LOG CRUD =============

def create_system_log(db: Session, log: schemas.SystemLogCreate) -> models.SystemLog:
    """Créer un log système"""
    db_log = models.SystemLog(**log.model_dump())
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log


def get_system_logs(db: Session, skip: int = 0, limit: int = 100, level: Optional[str] = None) -> List[models.SystemLog]:
    """Obtenir les logs système"""
    query = db.query(models.SystemLog)
    if level:
        query = query.filter(models.SystemLog.level == level)
    return query.order_by(desc(models.SystemLog.created_at)).offset(skip).limit(limit).all()


# ============= VEHICLE CRUD =============

def get_vehicle_by_id(db: Session, vehicle_id: int) -> Optional[models.Vehicle]:
    """Obtenir un véhicule par ID"""
    return db.query(models.Vehicle).filter(models.Vehicle.id == vehicle_id).first()


def get_vehicles_by_event(db: Session, event_id: int) -> List[models.Vehicle]:
    """Obtenir les véhicules d'un événement"""
    return db.query(models.Vehicle).filter(models.Vehicle.event_id == event_id).all()


def get_vehicles_by_license_plate(db: Session, license_plate: str) -> List[models.Vehicle]:
    """Obtenir les véhicules par plaque d'immatriculation"""
    return db.query(models.Vehicle).filter(models.Vehicle.license_plate == license_plate).all()


def create_vehicle(db: Session, vehicle: schemas.VehicleCreate) -> models.Vehicle:
    """Créer un nouvel enregistrement de véhicule"""
    detected_at = vehicle.detected_at or datetime.now()
    db_vehicle = models.Vehicle(
        **vehicle.model_dump(exclude={"detected_at"}),
        detected_at=detected_at
    )
    db.add(db_vehicle)
    db.commit()
    db.refresh(db_vehicle)
    return db_vehicle
