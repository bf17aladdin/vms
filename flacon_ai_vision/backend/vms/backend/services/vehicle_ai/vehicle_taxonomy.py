from __future__ import annotations

import re
from typing import Dict, Optional


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_key(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("_", " ").replace("-", " ")
    text = _WHITESPACE_RE.sub(" ", text)
    return text


def _slugify_alnum(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


_COLOR_ALIASES: Dict[str, str] = {
    "unknown": "unknown",
    "inconnu": "unknown",
    "na": "unknown",
    "n a": "unknown",
    "black": "black",
    "noir": "black",
    "noire": "black",
    "white": "white",
    "blanc": "white",
    "blanche": "white",
    "gray": "gray",
    "grey": "gray",
    "gris": "gray",
    "grise": "gray",
    "silver": "silver",
    "argent": "silver",
    "argente": "silver",
    "red": "red",
    "rouge": "red",
    "maroon": "maroon",
    "bordeaux": "maroon",
    "orange": "orange",
    "yellow": "yellow",
    "jaune": "yellow",
    "green": "green",
    "vert": "green",
    "blue": "blue",
    "bleu": "blue",
    "cyan": "cyan",
    "turquoise": "cyan",
    "purple": "purple",
    "violet": "purple",
    "brown": "brown",
    "marron": "brown",
    "beige": "beige",
    "gold": "gold",
    "or": "gold",
}

_CANONICAL_COLORS = {
    "unknown",
    "black",
    "white",
    "gray",
    "silver",
    "red",
    "maroon",
    "orange",
    "yellow",
    "green",
    "blue",
    "cyan",
    "purple",
    "brown",
    "beige",
    "gold",
}

_CANONICAL_BRANDS: Dict[str, str] = {
    "audi": "Audi",
    "bmw": "BMW",
    "chevrolet": "Chevrolet",
    "citroen": "Citroen",
    "dacia": "Dacia",
    "fiat": "Fiat",
    "ford": "Ford",
    "honda": "Honda",
    "hyundai": "Hyundai",
    "isuzu": "Isuzu",
    "iveco": "Iveco",
    "jeep": "Jeep",
    "kia": "Kia",
    "landrover": "Land Rover",
    "lexus": "Lexus",
    "mahindra": "Mahindra",
    "mazda": "Mazda",
    "mercedes": "Mercedes",
    "mercedesbenz": "Mercedes-Benz",
    "mini": "Mini",
    "mitsubishi": "Mitsubishi",
    "nissan": "Nissan",
    "opel": "Opel",
    "peugeot": "Peugeot",
    "porsche": "Porsche",
    "renault": "Renault",
    "seat": "Seat",
    "skoda": "Skoda",
    "ssangyong": "SsangYong",
    "suzuki": "Suzuki",
    "tesla": "Tesla",
    "toyota": "Toyota",
    "volkswagen": "Volkswagen",
    "volvo": "Volvo",
}

_BRAND_ALIASES: Dict[str, str] = {
    "mercedes benz": "mercedesbenz",
    "mercedes-benz": "mercedesbenz",
    "benz": "mercedesbenz",
    "vw": "volkswagen",
    "volks wagon": "volkswagen",
    "land rover": "landrover",
    "rangerover": "landrover",
    "range rover": "landrover",
    "ssang young": "ssangyong",
    "ssangyoung": "ssangyong",
    "sangyoung": "ssangyong",
}

_CATEGORY_ALIASES: Dict[str, str] = {
    "civil": "civil",
    "civile": "civil",
    "civilian": "civil",
    "military": "military",
    "militaire": "military",
    "army": "military",
    "defense": "military",
    "unknown": "unknown",
    "inconnu": "unknown",
}

_BODY_STYLE_ALIASES: Dict[str, str] = {
    "unknown": "unknown",
    "inconnu": "unknown",
    "sedan": "sedan_coupe",
    "coupe": "sedan_coupe",
    "berline": "sedan_coupe",
    "sedan coupe": "sedan_coupe",
    "sedan_coupe": "sedan_coupe",
    "suv": "suv_crossover",
    "crossover": "suv_crossover",
    "4x4": "suv_crossover",
    "suv crossover": "suv_crossover",
    "suv_crossover": "suv_crossover",
    "compact": "compact_hatch",
    "hatch": "compact_hatch",
    "hatchback": "compact_hatch",
    "compact hatch": "compact_hatch",
    "compact_hatch": "compact_hatch",
    "pickup": "truck",
    "pickup truck": "truck",
    "truck": "truck",
    "camion": "truck",
    "bus": "bus",
    "coach": "bus",
    "motorcycle": "motorcycle",
    "motorbike": "motorcycle",
    "bike": "motorcycle",
    "moto": "motorcycle",
}

_VEHICLE_TYPE_ALIASES: Dict[str, str] = {
    "unknown": "unknown",
    "inconnu": "unknown",
    "car": "car",
    "auto": "car",
    "automobile": "car",
    "passenger": "car",
    "passenger car": "car",
    "voiture": "car",
    "truck": "truck",
    "pickup": "truck",
    "pickup truck": "truck",
    "utility": "truck",
    "utilitaire": "truck",
    "bus": "bus",
    "coach": "bus",
    "transport": "bus",
    "motorcycle": "motorcycle",
    "motorbike": "motorcycle",
    "bike": "motorcycle",
    "two wheeler": "motorcycle",
    "two_wheeler": "motorcycle",
    "moto": "motorcycle",
}


def normalize_vehicle_color(value: Optional[str]) -> str:
    key = _normalize_key(value)
    if not key:
        return "unknown"
    canonical = _COLOR_ALIASES.get(key)
    if canonical:
        return canonical
    slug = _slugify_alnum(key)
    for alias, mapped in _COLOR_ALIASES.items():
        if _slugify_alnum(alias) == slug:
            return mapped
    return "unknown"


def normalize_vehicle_brand(value: Optional[str]) -> Optional[str]:
    key = _normalize_key(value)
    if not key:
        return None

    direct = _BRAND_ALIASES.get(key, key)
    slug = _slugify_alnum(direct)
    if slug in _CANONICAL_BRANDS:
        return _CANONICAL_BRANDS[slug]

    for alias, mapped in _BRAND_ALIASES.items():
        if _slugify_alnum(alias) == slug:
            canonical_key = _slugify_alnum(mapped)
            if canonical_key in _CANONICAL_BRANDS:
                return _CANONICAL_BRANDS[canonical_key]

    title = " ".join(part.capitalize() for part in key.split(" ") if part)
    return title or None


def vehicle_brand_key(value: Optional[str]) -> Optional[str]:
    normalized = normalize_vehicle_brand(value)
    if not normalized:
        return None
    key = _slugify_alnum(normalized)
    return key or None


def vehicle_brand_logo_path(value: Optional[str]) -> Optional[str]:
    key = vehicle_brand_key(value)
    if not key:
        return None
    return f"/assets/vehicle-brands/{key}.svg"


def normalize_vehicle_category(value: Optional[str]) -> str:
    key = _normalize_key(value)
    if not key:
        return "unknown"
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    if key.startswith("mil"):
        return "military"
    if key.startswith("civ"):
        return "civil"
    return "unknown"


def normalize_vehicle_model(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    text = _WHITESPACE_RE.sub(" ", text)
    return text


def normalize_vehicle_body_style(value: Optional[str]) -> Optional[str]:
    key = _normalize_key(value)
    if not key:
        return None

    direct = _BODY_STYLE_ALIASES.get(key)
    if direct:
        return None if direct == "unknown" else direct

    slug = _slugify_alnum(key)
    for alias, mapped in _BODY_STYLE_ALIASES.items():
        if _slugify_alnum(alias) == slug:
            return None if mapped == "unknown" else mapped

    return None


def normalize_vehicle_type(value: Optional[str]) -> Optional[str]:
    key = _normalize_key(value)
    if not key:
        return None
    direct = _VEHICLE_TYPE_ALIASES.get(key)
    if direct:
        return direct

    slug = _slugify_alnum(key)
    for alias, mapped in _VEHICLE_TYPE_ALIASES.items():
        if _slugify_alnum(alias) == slug:
            return mapped

    return None


def get_supported_vehicle_colors() -> tuple[str, ...]:
    return tuple(sorted(_CANONICAL_COLORS))


def get_supported_vehicle_body_styles() -> tuple[str, ...]:
    return ("sedan_coupe", "suv_crossover", "compact_hatch", "truck", "bus", "motorcycle")


def get_supported_vehicle_types() -> tuple[str, ...]:
    return ("car", "truck", "bus", "motorcycle", "unknown")
