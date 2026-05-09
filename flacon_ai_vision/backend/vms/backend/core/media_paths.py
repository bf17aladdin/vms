from __future__ import annotations

from typing import Optional


def to_public_media_path(path: Optional[str]) -> Optional[str]:
    clean = str(path or "").strip().replace("\\", "/")
    if not clean:
        return None
    if clean.startswith(("http://", "https://", "data:")):
        return clean

    lowered = clean.lower()
    if lowered.startswith("/media/"):
        return clean
    if lowered.startswith("/media-storage/"):
        return clean
    if lowered.startswith("/data/"):
        return f"/media/{clean[6:]}"
    if lowered.startswith("/storage/"):
        return f"/media-storage/{clean[9:]}"
    if lowered.startswith("media/"):
        return f"/{clean}"
    if lowered.startswith("storage/"):
        return f"/media-storage/{clean[8:]}"
    if lowered.startswith("data/"):
        return f"/media/{clean[5:]}"

    data_marker = "/data/"
    data_index = lowered.rfind(data_marker)
    if data_index >= 0:
        return f"/media/{clean[data_index + len(data_marker):]}"

    storage_marker = "/storage/"
    storage_index = lowered.rfind(storage_marker)
    if storage_index >= 0:
        return f"/media-storage/{clean[storage_index + len(storage_marker):]}"

    if clean.startswith("/"):
        return clean
    return f"/media/{clean.lstrip('/')}"
