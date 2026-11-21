"""Measure feature extraction, ported verbatim from the KG2MD notebook's
``measure_additivity_model.features`` module so the trained .joblib models see
exactly the representation they were trained on (pandas dependency removed)."""
from __future__ import annotations

import re
from typing import Dict, Any, List, Optional, Union


def _isna(x) -> bool:
    return x is None or (isinstance(x, float) and x != x)

# Canonical semantic indicator stems
NON_ADDITIVE_STEMS = {
    "rate", "ratio", "pct", "percent", "percentage", "proportion",
    "avg", "average", "mean", "median", "mode",
    "index", "indices", "score", "scores", "rank", "ranking", "grade",
    "temp", "temperature", "heart", "bp", "pulse",
    "speed", "velocity", "acceleration", "frequency", "rpm", "hz",
    "price", "costper", "perunit", "margin", "yield",
    "density", "viscosity", "ph", "voltage", "current", "resistance",
    "pressure", "humidity", "salinity", "luminosity", "efficiency",
    "intensity", "saturation", "concentration",
}

ADDITIVE_STEMS = {
    "count", "counts", "total", "totals", "number", "numbers",
    "quantity", "quantities", "qty", "sum", "sums",
    "amount", "amt", "cost", "revenue", "sales", "fee", "tax",
    "deposit", "withdrawal", "balance", "profit", "expenditure",
    "mass", "weight", "volume", "liters", "tonnes", "kg", "grams",
    "distance", "miles", "km", "meters", "length", "area", "sqm",
    "duration", "hours", "seconds", "minutes", "days",
    "bytes", "packets", "trips", "views", "clicks", "impressions",
    "emissions", "waste", "energy", "kwh", "joules",
    "credits", "population", "headcount", "dosage",
}


def split_identifier_tokens(name: str) -> List[str]:
    """
    Split camelCase, PascalCase, snake_case, or kebab-case identifier into tokens.
    
    Examples:
        'salesAmount' -> ['sales', 'amount']
        'heartRate' -> ['heart', 'rate']
        'hasNumericalValue' -> ['has', 'numerical', 'value']
        'systolic_bp' -> ['systolic', 'bp']
        'discount-pct' -> ['discount', 'pct']
    """
    if not name or not isinstance(name, str):
        return []
    # Insert space before capital letters in camelCase/PascalCase
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", spaced)
    tokens = [t.lower() for t in cleaned.split() if t]
    return tokens


def normalize_unit(unit: Optional[str]) -> str:
    """Normalize unit of measure string into standard semantic tokens."""
    if not unit or _isna(unit):
        return "none"
    u = str(unit).strip().lower()
    if "#" in u:
        u = u.split("#")[-1]
    elif "/" in u:
        u = u.split("/")[-1]
    
    synonym_map = {
        "%": "percent",
        "pct": "percent",
        "percentage": "percent",
        "ratio": "ratio",
        "usd": "currency_usd",
        "eur": "currency_eur",
        "gbp": "currency_gbp",
        "$": "currency_usd",
        "count": "unit_count",
        "item_count": "unit_count",
        "items": "unit_count",
        "units": "unit_count",
        "celsius": "temp_celsius",
        "fahrenheit": "temp_fahrenheit",
        "bpm": "rate_bpm",
        "tonne": "mass_tonne",
        "kg": "mass_kg",
        "grams": "mass_g",
        "hours": "time_hours",
        "seconds": "time_seconds",
        "days": "time_days",
        "liters": "volume_liters",
        "m3": "volume_m3",
        "hz": "freq_hz",
        "rpm": "speed_rpm",
        "db": "sound_db",
        "v": "elec_volt",
        "ohms": "elec_ohm",
    }
    return synonym_map.get(u, u)


def normalize_datatype(dt: Optional[str]) -> str:
    """Normalize XSD datatype into standard token."""
    if not dt or _isna(dt):
        return "xsd_float"
    s = str(dt).strip().lower()
    if "#" in s:
        s = s.split("#")[-1]
    elif "/" in s:
        s = s.split("/")[-1]
    s = s.replace(":", "_").replace("-", "_")
    return s


def build_text_representation(
    measure_name: str,
    datatype: Optional[str] = None,
    unit: Optional[str] = None,
    is_bounded_0_1: int = 0,
    domain_class: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Construct a dense, unified semantic text representation for vectorization.
    Combines tokenized identifier terms, morphological n-gram stems, normalized
    datatype, normalized unit, domain context, semantic tags, and bounded range flag.
    """
    tokens = split_identifier_tokens(measure_name)
    token_str = " ".join(tokens)
    
    norm_dt = normalize_datatype(datatype)
    norm_u = normalize_unit(unit)
    
    semantic_tags = []
    if is_bounded_0_1 == 1:
        bounded_str = "bounded_interval bounded_interval"
        semantic_tags.append("tag_non_additive_marker")
    else:
        bounded_str = "unbounded_interval"
    token_set = set(tokens)
    if token_set & NON_ADDITIVE_STEMS:
        semantic_tags.append("tag_non_additive_marker")
    if token_set & ADDITIVE_STEMS:
        semantic_tags.append("tag_additive_marker")
        
    # Check suffixes
    for t in tokens:
        if any(t.endswith(stem) for stem in ("rate", "ratio", "pct", "temp", "score", "price", "speed", "frequency", "hz", "density")):
            semantic_tags.append("tag_non_additive_marker")
        if any(t.endswith(stem) for stem in ("count", "total", "amount", "cost", "hours", "mass", "volume", "weight")):
            semantic_tags.append("tag_additive_marker")

    if norm_u in ("percent", "ratio", "rate_bpm", "temp_celsius", "temp_fahrenheit", "freq_hz", "speed_rpm", "sound_db"):
        semantic_tags.append("tag_non_additive_unit")
    elif norm_u in ("unit_count", "mass_tonne", "mass_kg", "mass_g", "time_hours", "time_seconds", "volume_liters", "currency_usd", "currency_eur"):
        semantic_tags.append("tag_additive_unit")

    tag_str = " ".join(set(semantic_tags))

    domain_str = ""
    if domain_class and not _isna(domain_class):
        domain_tokens = split_identifier_tokens(domain_class)
        domain_str = "domain_" + "_".join(domain_tokens)
        
    desc_str = ""
    if description and not _isna(description):
        desc_tokens = split_identifier_tokens(description)
        desc_str = " ".join(desc_tokens[:10])

    # Composite representation: weighted by token repetition
    rep = f"{token_str} {token_str} {tag_str} dt_{norm_dt} unit_{norm_u} {bounded_str} {domain_str} {desc_str}".strip()
    return rep


