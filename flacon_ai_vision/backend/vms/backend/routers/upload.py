from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pathlib import Path
import shutil
import time

from ..core.config import settings
from ..core.security import get_current_user

router = APIRouter(prefix="/api/upload", tags=["upload"])


def _store_uploaded_photo(file: UploadFile, folder_name: str, fallback_stem: str) -> str:
    storage_dir = Path(settings.STORAGE_PATH)
    photos_dir = storage_dir / "uploads" / folder_name
    photos_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(file.filename or "").stem.replace(" ", "_") or fallback_stem
    suffix = Path(file.filename or "").suffix or ".jpg"
    filename = f"{stem}_{int(time.time())}{suffix}"
    dest_path = photos_dir / filename

    with dest_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return str(dest_path)


@router.post("/person-photo")
async def upload_person_photo(file: UploadFile = File(...), current_user=Depends(get_current_user)):
    """Upload a person photo and save it to storage; returns server file path"""
    try:
        return {"status": "ok", "path": _store_uploaded_photo(file, "person_photos", "photo")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vehicle-photo")
async def upload_vehicle_photo(file: UploadFile = File(...), current_user=Depends(get_current_user)):
    """Upload a vehicle reference photo and save it to storage; returns server file path."""
    try:
        return {"status": "ok", "path": _store_uploaded_photo(file, "vehicle_photos", "vehicle")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
