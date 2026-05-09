# vms/backend/routers/personnel.py - Routes API Personnel

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import uuid
import logging

from ..core.database import get_db
from ..core.security import get_current_user
from ..models import User, Tenant, Personnel, FaceDetection, FaceEncoding, FaceImage, ZoneOccupancy
from ..schemas import (
    PersonnelOut, PersonnelCreate, PersonnelUpdate, PersonnelEventOut,
    PersonnelBulkDeactivateRequest, PersonnelBulkDeactivateResult,
    PersonnelCategoryEnum, validate_personnel_grade_for_category
)
from ..services.personnel_service import PersonnelService
from ..services.setup_config_service import get_setup_config_service

router = APIRouter(prefix="/api/personnel", tags=["Personnel"])
logger = logging.getLogger(__name__)


def _resolve_project_type(db: Session, current_user: dict) -> str:
    tenant_id = current_user.get("tenant_id") or current_user.get("tenant")
    if tenant_id:
        try:
            tenant = db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
            if tenant and getattr(tenant, "project_type", None):
                return str(tenant.project_type)
        except Exception:
            pass
    config = get_setup_config_service().get_config()
    return str(config.get("project_type") or "soc")


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _generate_unique_identifier(db: Session, column, prefix: str) -> str:
    for _ in range(5):
        candidate = f"{prefix}-{uuid.uuid4().hex[:8]}"
        if not db.query(Personnel).filter(column == candidate).first():
            return candidate
    return f"{prefix}-{uuid.uuid4().hex}"


class _LazyPersonnelService:
    def __init__(self):
        self._instance: Optional[PersonnelService] = None

    def _get(self) -> PersonnelService:
        if self._instance is None:
            self._instance = PersonnelService()
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._get(), name)


personnel_svc = _LazyPersonnelService()

# ========== CRUD PERSONNEL ==========

@router.post("/", response_model=PersonnelOut, status_code=status.HTTP_201_CREATED)
@router.post("", response_model=PersonnelOut, status_code=status.HTTP_201_CREATED)
def create_personnel(
    data: PersonnelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Créer une nouvelle personne enregistrée.

    Les champs d'identité avancés (CIN, reference, categorie, grade) restent
    disponibles pour compatibilité SOC, mais peuvent être omis en mode standard.
    """
    try:
        project_type = _resolve_project_type(db, current_user)
        cin_value = _normalize_optional_text(data.cin)
        recruit_value = _normalize_optional_text(data.num_recrutement)
        category_value = data.categorie or PersonnelCategoryEnum.CIVIL
        grade_value = _normalize_optional_text(data.grade)

        if project_type == "soc":
            missing = []
            if not cin_value:
                missing.append("cin")
            if not recruit_value:
                missing.append("num_recrutement")
            if not data.categorie:
                missing.append("categorie")
            if not grade_value:
                missing.append("grade")
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required fields: {', '.join(missing)}",
                )

        # Vérifier unicité des identifiants fournis
        if cin_value:
            existing_cin = db.query(Personnel).filter(Personnel.cin == cin_value).first()
            if existing_cin:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Identifiant '{cin_value}' déjà enregistré",
                )

        if recruit_value:
            existing_recrutement = (
                db.query(Personnel).filter(Personnel.num_recrutement == recruit_value).first()
            )
            if existing_recrutement:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Reference '{recruit_value}' déjà enregistrée",
                )

        if not cin_value:
            cin_value = _generate_unique_identifier(db, Personnel.cin, "ID")
        if not recruit_value:
            recruit_value = _generate_unique_identifier(db, Personnel.num_recrutement, "REF")
        if not grade_value:
            grade_value = "Unassigned"

        # Créer nouvelle personne
        personnel = Personnel(
            nom=str(data.nom).strip(),
            prenom=str(data.prenom).strip(),
            full_name=f"{str(data.prenom).strip()} {str(data.nom).strip()}".strip(),
            cin=cin_value,
            num_recrutement=recruit_value,
            categorie=category_value,
            grade=grade_value,
            unite=_normalize_optional_text(data.unite),
            gender=data.gender,
            email=data.email,
            telephone=data.telephone,
            photo_path=data.photo_path,
            allowed_camera_ids=data.allowed_camera_ids,
            authorized_hours_start=data.authorized_hours_start,
            authorized_hours_end=data.authorized_hours_end,
            notes=data.notes,
            custom_fields=data.custom_fields,
            is_active=True,
        )
        
        db.add(personnel)
        db.commit()
        db.refresh(personnel)
        
        logger.info(f"? Person created: {personnel.nom} {personnel.prenom} ({personnel.grade})")
        return personnel
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Person creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{personnel_id:int}", response_model=PersonnelOut)
def get_personnel(
    personnel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Récupérer les détails d'un personnel"""
    personnel = db.query(Personnel).filter(Personnel.id == personnel_id).first()
    
    if not personnel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Personnel #{personnel_id} non trouvé"
        )
    
    return personnel


@router.get("/", response_model=List[PersonnelOut])
@router.get("", response_model=List[PersonnelOut])
def list_personnel(
    grade: Optional[str] = Query(None),
    categorie: Optional[PersonnelCategoryEnum] = Query(None),
    unite: Optional[str] = Query(None),
    is_active: bool = Query(True),
    is_blacklisted: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lister les personnes avec filtres.

    **Filtres disponibles:**
    - `grade`: Filtrer par role/intitule
    - `categorie`: categorie legacy (SOC)
    - `unite`: equipe/departement
    - `is_active`: Actif/Inactif
    - `is_blacklisted`: Personne signalée
    """
    try:
        query = db.query(Personnel)
        
        if grade:
            query = query.filter(Personnel.grade.ilike(f"%{grade}%"))
        
        if categorie:
            query = query.filter(Personnel.categorie == categorie)
        
        if unite:
            query = query.filter(Personnel.unite.ilike(f"%{unite}%"))
        
        query = query.filter(Personnel.is_active == is_active)
        query = query.filter(Personnel.is_blacklisted == is_blacklisted)
        
        personnel_list = query.offset(skip).limit(limit).all()
        
        logger.info("? %s people listed", len(personnel_list))
        return personnel_list
    
    except Exception as e:
        logger.error("Person list error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bulk/deactivate", response_model=PersonnelBulkDeactivateResult)
def bulk_deactivate_personnel(
    payload: PersonnelBulkDeactivateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Désactiver plusieurs personnels en une seule transaction."""
    del current_user

    try:
        requested_ids = []
        seen_ids = set()
        for raw_id in payload.personnel_ids:
            personnel_id = int(raw_id)
            if personnel_id <= 0 or personnel_id in seen_ids:
                continue
            seen_ids.add(personnel_id)
            requested_ids.append(personnel_id)

        if not requested_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Aucun identifiant de personnel valide fourni",
            )

        personnel_rows = db.query(Personnel).filter(Personnel.id.in_(requested_ids)).all()
        personnel_by_id = {int(row.id): row for row in personnel_rows}

        updated_ids: List[int] = []
        already_inactive_count = 0
        now = datetime.utcnow()

        for personnel_id in requested_ids:
            personnel = personnel_by_id.get(personnel_id)
            if personnel is None:
                continue
            if personnel.is_active:
                personnel.is_active = False
                personnel.date_modification = now
                db.add(personnel)
                updated_ids.append(personnel_id)
            else:
                already_inactive_count += 1

        db.commit()

        missing_ids = [personnel_id for personnel_id in requested_ids if personnel_id not in personnel_by_id]
        logger.info(
            "? Suppression logique groupée personnel: %s mis en inactif, %s déjà inactif(s), %s introuvable(s)",
            len(updated_ids),
            already_inactive_count,
            len(missing_ids),
        )
        return PersonnelBulkDeactivateResult(
            requested_count=len(requested_ids),
            updated_count=len(updated_ids),
            already_inactive_count=already_inactive_count,
            missing_ids=missing_ids,
            updated_ids=updated_ids,
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur suppression groupée personnel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{personnel_id:int}", response_model=PersonnelOut)
def update_personnel(
    personnel_id: int,
    data: PersonnelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mettre à jour les infos d'une personne."""
    try:
        personnel = db.query(Personnel).filter(Personnel.id == personnel_id).first()
        
        if not personnel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Personne #{personnel_id} non trouvée"
            )

        # Mettre à jour les champs fournis
        update_data = data.model_dump(exclude_unset=True)
        project_type = _resolve_project_type(db, current_user)

        # Normaliser les champs texte optionnels (ignore les valeurs vides)
        for field_name in ["cin", "num_recrutement", "grade", "unite", "nom", "prenom"]:
            if field_name in update_data:
                cleaned = _normalize_optional_text(update_data.get(field_name))
                if cleaned is None:
                    update_data.pop(field_name, None)
                else:
                    update_data[field_name] = cleaned

        # Validation stricte catégorie/grade pour les updates partiels.
        # Si un seul des deux champs est envoyé, on combine avec la valeur actuelle DB.
        if "categorie" in update_data or "grade" in update_data:
            effective_category = update_data.get("categorie", personnel.categorie)
            effective_grade = update_data.get("grade", personnel.grade)
            try:
                validate_personnel_grade_for_category(effective_category, effective_grade)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                )
        if project_type == "soc":
            missing = []
            if "cin" in update_data and not update_data.get("cin"):
                missing.append("cin")
            if "num_recrutement" in update_data and not update_data.get("num_recrutement"):
                missing.append("num_recrutement")
            if "grade" in update_data and not update_data.get("grade"):
                missing.append("grade")
            if "categorie" in update_data and not update_data.get("categorie"):
                missing.append("categorie")
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required fields: {', '.join(missing)}",
                )

        # Vérifier unicité CIN si modifié
        if "cin" in update_data and update_data.get("cin"):
            new_cin = str(update_data.get("cin")).strip()
            existing_cin = (
                db.query(Personnel)
                .filter(Personnel.cin == new_cin)
                .filter(Personnel.id != personnel_id)
                .first()
            )
            if existing_cin:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Identifiant '{new_cin}' déjà enregistré",
                )
            update_data["cin"] = new_cin

        # Vérifier unicité numéro de recrutement si modifié
        if "num_recrutement" in update_data and update_data.get("num_recrutement"):
            new_recruit = str(update_data.get("num_recrutement")).strip()
            existing_recruit = (
                db.query(Personnel)
                .filter(Personnel.num_recrutement == new_recruit)
                .filter(Personnel.id != personnel_id)
                .first()
            )
            if existing_recruit:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Reference '{new_recruit}' déjà enregistrée",
                )
            update_data["num_recrutement"] = new_recruit

        for field, value in update_data.items():
            if value is not None:
                if field in ['nom', 'prenom']:
                    setattr(personnel, field, value)
                    # Mettre à jour full_name
                    personnel.full_name = f"{personnel.prenom} {personnel.nom}"
                else:
                    setattr(personnel, field, value)
        
        personnel.date_modification = datetime.utcnow()
        
        db.add(personnel)
        db.commit()
        db.refresh(personnel)
        
        logger.info(f"? Person updated: {personnel.nom} {personnel.prenom}")
        return personnel
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Person update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{personnel_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_personnel(
    personnel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Supprimer définitivement un personnel"""
    try:
        personnel = db.query(Personnel).filter(Personnel.id == personnel_id).first()
        
        if not personnel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Personnel #{personnel_id} non trouvé"
            )

        personnel_name = str(personnel.full_name or f"{personnel.prenom} {personnel.nom}").strip()
        now = datetime.utcnow()
        logger.info(f"Début suppression personnel {personnel_id}: {personnel_name}")

        face_image_ids = [
            int(face_image_id)
            for (face_image_id,) in db.query(FaceImage.id).filter(FaceImage.personnel_id == personnel_id).all()
        ]

        face_encoding_filter = FaceEncoding.personnel_id == personnel_id
        if face_image_ids:
            face_encoding_filter = or_(
                face_encoding_filter,
                FaceEncoding.face_image_id.in_(face_image_ids),
            )
        face_encoding_query = db.query(FaceEncoding).filter(face_encoding_filter)
        deleted_face_encodings = face_encoding_query.delete(synchronize_session=False)

        deleted_face_images = (
            db.query(FaceImage)
            .filter(FaceImage.personnel_id == personnel_id)
            .delete(synchronize_session=False)
        )

        detached_face_detections = (
            db.query(FaceDetection)
            .filter(FaceDetection.personnel_id == personnel_id)
            .update({FaceDetection.personnel_id: None}, synchronize_session=False)
        )

        closed_zone_occupancies = (
            db.query(ZoneOccupancy)
            .filter(
                ZoneOccupancy.personnel_id == personnel_id,
                ZoneOccupancy.is_active.is_(True),
            )
            .update(
                {
                    ZoneOccupancy.personnel_id: None,
                    ZoneOccupancy.is_active: False,
                    ZoneOccupancy.exit_time: now,
                },
                synchronize_session=False,
            )
        )

        detached_zone_occupancies = (
            db.query(ZoneOccupancy)
            .filter(ZoneOccupancy.personnel_id == personnel_id)
            .update({ZoneOccupancy.personnel_id: None}, synchronize_session=False)
        )

        db.delete(personnel)
        db.commit()

        logger.info(
            "? Personnel supprimé définitivement: %s (encodages=%s, images=%s, detections detachées=%s, occupances clôturées=%s, occupances détachées=%s)",
            personnel_name,
            deleted_face_encodings,
            deleted_face_images,
            detached_face_detections,
            closed_zone_occupancies,
            detached_zone_occupancies,
        )
        return None
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur suppression personnel {personnel_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== ACTIONS SPÉCIALES ==========

@router.post("/{personnel_id:int}/blacklist", response_model=PersonnelOut)
def blacklist_personnel(
    personnel_id: int,
    reason: str = Query(..., min_length=5),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Ajouter un personnel à la liste noire
    
    **Paramètres:**
    - `reason`: Raison du signalement
    """
    try:
        personnel = db.query(Personnel).filter(Personnel.id == personnel_id).first()
        
        if not personnel:
            raise HTTPException(status_code=404, detail="Personnel non trouvé")

        # Idempotence: si déjà blacklisté, ne pas créer de second signalement.
        if personnel.is_blacklisted:
            logger.info(
                "Blacklist idempotent: personnel déjà signalé (%s %s, id=%s)",
                personnel.nom,
                personnel.prenom,
                personnel.id,
            )
            return personnel

        personnel.is_blacklisted = True
        personnel.blacklist_reason = reason
        db.add(personnel)
        db.commit()
        db.refresh(personnel)
        
        logger.warning(f"? Personnel blacklisté: {personnel.nom} {personnel.prenom} - {reason}")
        return personnel
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{personnel_id:int}/unblacklist", response_model=PersonnelOut)
def unblacklist_personnel(
    personnel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retirer un personnel de la liste noire"""
    try:
        personnel = db.query(Personnel).filter(Personnel.id == personnel_id).first()
        
        if not personnel:
            raise HTTPException(status_code=404, detail="Personnel non trouvé")
        
        personnel.is_blacklisted = False
        personnel.blacklist_reason = None
        db.add(personnel)
        db.commit()
        db.refresh(personnel)
        
        logger.info(f"? Personnel retiré de la liste noire: {personnel.nom} {personnel.prenom}")
        return personnel
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ========== STATISTIQUES ==========

@router.get("/stats/summary", response_model=dict)
async def get_summary_stats(db: Session = Depends(get_db)):
    """
    Obtenir les statistiques résumées du personnel
    
    **Retourne:**
    - Total de personnels
    - Nombre par catégorie/grade
    - Nombre de personnels actifs
    - Nombre de personnels blacklistés
    """
    try:
        total = db.query(Personnel).count()
        actifs = db.query(Personnel).filter(Personnel.is_active == True).count()
        blacklistes = db.query(Personnel).filter(Personnel.is_blacklisted == True).count()
        
        # Compter par catégorie
        categories = {}
        for cat in PersonnelCategoryEnum:
            count = db.query(Personnel).filter(
                Personnel.categorie == cat
            ).count()
            categories[cat.value] = count
        
        return {
            "total": total,
            "actifs": actifs,
            "blacklistes": blacklistes,
            "par_categorie": categories,
        }
    
    except Exception as e:
        logger.error(f"Erreur statistiques: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== RECONNAISSANCE FACIALE ==========

@router.post("/{personnel_id:int}/load-face")
def load_face_encoding(
    personnel_id: int,
    image_path: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Charger encodage facial depuis une image
    
    Nécessite:
    - image_path: chemin complet vers image PNG/JPG
    - Image doit contenir visage clair et non-occludé
    """
    personnel = personnel_svc.get_personnel(db, personnel_id)
    if not personnel:
        raise HTTPException(status_code=404, detail="Personnel non trouvé")
    
    success = personnel_svc.load_face_encoding(db, personnel_id, image_path)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Erreur: pas de visage détecté dans l'image"
        )
    
    return {
        "status": "ok",
        "personnel_id": personnel_id,
        "message": f"Encodage chargé pour {personnel.full_name}"
    }

@router.get("/{personnel_id:int}/has-face-encoding", response_model=dict)
def has_face_encoding(
    personnel_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Vérifier si personnel a encodage facial"""
    personnel = personnel_svc.get_personnel(db, personnel_id)
    if not personnel:
        raise HTTPException(status_code=404, detail="Personnel non trouvé")
    
    has_encoding = personnel_svc.has_face_encoding(personnel_id)
    return {
        "personnel_id": personnel_id,
        "full_name": personnel.full_name,
        "has_face_encoding": has_encoding,
    }

# ========== ÉVÉNEMENTS PERSONNEL ==========

@router.get("/{personnel_id:int}/events", response_model=List[PersonnelEventOut])
def get_personnel_events(
    personnel_id: int,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Récupérer événements personnel (entrée/sortie)"""
    personnel = personnel_svc.get_personnel(db, personnel_id)
    if not personnel:
        raise HTTPException(status_code=404, detail="Personnel non trouvé")
    
    return personnel_svc.get_personnel_events(db, personnel_id, limit)

# ========== STATISTIQUES ==========

@router.get("/stats/daily", response_model=dict)
def get_daily_summary(
    camera_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Résumé quotidien: entrées, sorties, par catégorie"""
    return personnel_svc.get_daily_summary(db, camera_id)

@router.get("/{personnel_id:int}/analytics", response_model=dict)
def get_personnel_analytics(
    personnel_id: int,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analytics pour une personne (jours, fréquence, confiance)"""
    personnel = personnel_svc.get_personnel(db, personnel_id)
    if not personnel:
        raise HTTPException(status_code=404, detail="Personnel non trouvé")
    
    return personnel_svc.get_personnel_analytics(db, personnel_id, days)

# ========== RECHERCHE ==========

@router.get("/search/by-cin", response_model=Optional[PersonnelOut])
def search_by_cin(
    cin: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chercher personnel par numéro CIN"""
    result = personnel_svc.get_personnel_by_cin(db, cin)
    if not result:
        raise HTTPException(status_code=404, detail="Personnel non trouvé")
    return result

@router.get("/search/by-recruitment-id", response_model=Optional[PersonnelOut])
def search_by_recruitment_id(
    recruitment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chercher personnel par ID recrutement"""
    result = personnel_svc.get_personnel_by_recruitment_id(db, recruitment_id)
    if not result:
        raise HTTPException(status_code=404, detail="Personnel non trouvé")
    return result

# ========== CATÉGORIES ==========

@router.get("/categories", response_model=dict)
def get_categories_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compter personnel par catégorie"""
    from sqlalchemy import func
    
    results = (db.query(Personnel.categorie, func.count(Personnel.id))
              .filter_by(is_active=True)
              .group_by(Personnel.categorie)
              .all())
    
    return {
        "categories": {
            (row[0].value if hasattr(row[0], "value") else row[0]): row[1]
            for row in results
        }
    }

@router.get("/status/active-count", response_model=dict)
def get_active_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Nombre de personnel actuellement présent"""
    from sqlalchemy import func
    from datetime import datetime, timedelta
    
    # Personnel ayant une entrée aujourd'hui sans sortie
    threshold = datetime.utcnow() - timedelta(hours=12)
    
    from ..models import PersonnelEvent
    active_count = (db.query(func.count(func.distinct(PersonnelEvent.personnel_id)))
                   .filter(PersonnelEvent.detected_at >= threshold)
                   .scalar() or 0)
    
    return {
        "currently_present": active_count,
        "last_update": datetime.utcnow().isoformat(),
    }
