"""Normalise une capture brute France Travail dans une base SQLite locale.

Étape 4 de la V1 : conservation du brut et création de champs homogènes.
Ce script n'applique aucun filtre, verdict, score, calcul de trajet ou IA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DATABASE = DATA_DIR / "veille_emploi.sqlite"
CAPTURE_PATTERN = "france_travail_brut_*.json"

SCHEMA_VERSION = "3"
SOURCE_NAME = "France Travail - API Offres d'emploi v2"
MAX_CREDIBLE_MONTHLY_GROSS = 20_000.0

SALARY_RE = re.compile(
    r"^\s*(Horaire|Mensuel|Annuel)\s+de\s+"
    r"([\d\s.,]+?)\s+Euros"
    r"(?:\s+à\s+([\d\s.,]+?)\s+Euros)?"
    r"(?:\s+sur\s+([\d\s.,]+?)\s+mois)?\s*$",
    re.IGNORECASE,
)
WEEKLY_HOURS_RE = re.compile(
    r"(?<!\d)(\d{1,2})H(?:(\d{1,2}))?\s*/\s*semaine",
    re.IGNORECASE,
)

CONTRACT_FAMILIES = {
    "CDI": "cdi",
    "CDD": "cdd",
    "MIS": "interim",
    "FRA": "franchise",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sha256 TEXT NOT NULL UNIQUE,
    content_range TEXT,
    request_params_json TEXT NOT NULL,
    raw_capture_metadata_json TEXT NOT NULL,
    normalized_at_utc TEXT NOT NULL,
    offer_count INTEGER NOT NULL CHECK (offer_count >= 0)
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    source_offer_id TEXT NOT NULL,

    title_raw TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    description_raw TEXT NOT NULL,
    created_at_utc TEXT,
    updated_at_utc TEXT,

    contract_code TEXT,
    contract_label TEXT,
    contract_family TEXT NOT NULL,
    contract_nature_code TEXT,
    job_count INTEGER,

    work_time_type TEXT,
    weekly_hours REAL,
    work_schedule_text TEXT,
    works_at_night INTEGER CHECK (works_at_night IN (0, 1) OR works_at_night IS NULL),
    works_shifted_hours INTEGER CHECK (works_shifted_hours IN (0, 1) OR works_shifted_hours IS NULL),
    works_weekend INTEGER CHECK (works_weekend IN (0, 1) OR works_weekend IS NULL),
    works_saturday INTEGER CHECK (works_saturday IN (0, 1) OR works_saturday IS NULL),
    works_sunday INTEGER CHECK (works_sunday IN (0, 1) OR works_sunday IS NULL),
    work_context_json TEXT NOT NULL,

    salary_label_raw TEXT,
    salary_comment_raw TEXT,
    salary_unit TEXT,
    salary_amount_min REAL,
    salary_amount_max REAL,
    salary_payment_months REAL,
    salary_monthly_gross_min REAL,
    salary_monthly_gross_max REAL,
    salary_conversion_method TEXT,
    salary_complements_json TEXT NOT NULL,

    location_label TEXT,
    commune_code TEXT,
    postal_code TEXT,
    latitude REAL,
    longitude REAL,

    travel_code TEXT,
    travel_label TEXT,
    travel_required INTEGER CHECK (travel_required IN (0, 1) OR travel_required IS NULL),

    employer_name TEXT,
    employer_is_anonymous INTEGER NOT NULL CHECK (employer_is_anonymous IN (0, 1)),
    establishment_size_label TEXT,
    naf_code TEXT,
    sector_code TEXT,
    sector_label TEXT,

    rome_code TEXT,
    rome_label TEXT,
    experience_code TEXT,
    experience_label TEXT,
    experience_comment TEXT,
    qualification_code TEXT,
    qualification_label TEXT,

    skills_json TEXT NOT NULL,
    education_json TEXT NOT NULL,
    licences_json TEXT NOT NULL,
    professional_qualities_json TEXT NOT NULL,

    source_origin TEXT,
    source_url TEXT,
    application_url TEXT,
    raw_offer_json TEXT NOT NULL,

    UNIQUE (capture_id, source_offer_id)
);

CREATE INDEX IF NOT EXISTS idx_offers_contract_family
    ON offers(contract_family);
CREATE INDEX IF NOT EXISTS idx_offers_commune
    ON offers(commune_code);
CREATE INDEX IF NOT EXISTS idx_offers_salary_monthly_min
    ON offers(salary_monthly_gross_min);
CREATE INDEX IF NOT EXISTS idx_offers_created_at
    ON offers(created_at_utc);

CREATE TABLE IF NOT EXISTS filter_results (
    offer_id INTEGER PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('KEEP', 'REVIEW', 'EXCLUDE')),
    exclusion_reasons_json TEXT NOT NULL,
    review_reasons_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    schedule_penalty INTEGER NOT NULL CHECK (schedule_penalty >= 0),
    salary_threshold_monthly REAL NOT NULL,
    rules_version TEXT NOT NULL,
    evaluated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS travel_results (
    offer_id INTEGER PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    traffic_profile TEXT NOT NULL,
    origin_label TEXT NOT NULL,
    origin_latitude REAL NOT NULL,
    origin_longitude REAL NOT NULL,
    destination_latitude REAL,
    destination_longitude REAL,
    route_status TEXT NOT NULL CHECK (route_status IN ('OK', 'ERROR')),
    distance_meters INTEGER,
    duration_seconds INTEGER,
    duration_minutes REAL,
    traffic_delay_seconds INTEGER,
    travel_band TEXT NOT NULL CHECK (
        travel_band IN ('LE_35', 'BETWEEN_35_60', 'GT_60', 'UNKNOWN')
    ),
    provider_options_json TEXT NOT NULL,
    provider_response_json TEXT NOT NULL,
    evaluated_at_utc TEXT NOT NULL
);
"""


class NormalizationError(RuntimeError):
    """Capture absente, invalide ou déjà importée."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalise une capture France Travail dans SQLite."
    )
    parser.add_argument(
        "capture",
        nargs="?",
        type=Path,
        help="Capture JSON à importer. Par défaut : la plus récente dans data.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="Base SQLite cible (défaut : data/veille_emploi.sqlite).",
    )
    return parser.parse_args()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def compact_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def searchable_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def parse_number(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace("\u00a0", "").replace(" ", "").strip()
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_weekly_hours(value: Any) -> float | None:
    text = value if isinstance(value, str) else ""
    match = WEEKLY_HOURS_RE.search(text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2) or 0)
    if minutes >= 60:
        return None
    return round(hours + minutes / 60, 2)


def salary_values(
    salary: dict[str, Any], weekly_hours: float | None
) -> dict[str, Any]:
    label = salary.get("libelle") if isinstance(salary.get("libelle"), str) else None
    result: dict[str, Any] = {
        "salary_label_raw": label,
        "salary_comment_raw": salary.get("commentaire"),
        "salary_unit": None,
        "salary_amount_min": None,
        "salary_amount_max": None,
        "salary_payment_months": None,
        "salary_monthly_gross_min": None,
        "salary_monthly_gross_max": None,
        "salary_conversion_method": None,
        "salary_complements_json": json_text(salary.get("listeComplements", [])),
    }
    if not label:
        return result

    match = SALARY_RE.match(label)
    if not match:
        return result

    unit_fr, minimum_text, maximum_text, months_text = match.groups()
    minimum = parse_number(minimum_text)
    maximum = parse_number(maximum_text) if maximum_text else minimum
    months = parse_number(months_text)
    unit = {
        "horaire": "hour",
        "mensuel": "month",
        "annuel": "year",
    }[searchable_text(unit_fr)]

    result.update(
        {
            "salary_unit": unit,
            "salary_amount_min": minimum,
            "salary_amount_max": maximum,
            "salary_payment_months": months,
        }
    )
    if minimum is None or maximum is None:
        return result

    if minimum <= 0 or maximum <= 0 or maximum < minimum:
        result["salary_conversion_method"] = "rejected_invalid_amount_or_range"
        return result

    if unit == "month":
        if months is not None and (months <= 0 or months > 24):
            result["salary_conversion_method"] = "rejected_invalid_payment_months"
            return result
        payment_factor = months / 12 if months is not None else 1.0
        monthly_min, monthly_max = minimum * payment_factor, maximum * payment_factor
        method = (
            "declared_monthly"
            if months is None or months == 12
            else "declared_monthly_times_payment_months_divided_by_12"
        )
    elif unit == "year":
        monthly_min, monthly_max = minimum / 12, maximum / 12
        method = "annual_divided_by_12"
    elif unit == "hour" and weekly_hours is not None:
        factor = weekly_hours * 52 / 12
        monthly_min, monthly_max = minimum * factor, maximum * factor
        method = "hourly_times_weekly_hours"
    else:
        return result

    # L'API peut exceptionnellement annoncer comme mensuels des montants qui
    # ressemblent à une fourchette annuelle. Ne jamais corriger l'unité par
    # supposition : conserver les valeurs sources et demander une vérification.
    if (
        monthly_min > MAX_CREDIBLE_MONTHLY_GROSS
        or monthly_max > MAX_CREDIBLE_MONTHLY_GROSS
    ):
        result["salary_conversion_method"] = "rejected_implausible_monthly_amount"
        return result

    result.update(
        {
            "salary_monthly_gross_min": round(monthly_min, 2),
            "salary_monthly_gross_max": round(monthly_max, 2),
            "salary_conversion_method": method,
        }
    )
    return result


def optional_flag(text: str, terms: Iterable[str]) -> int | None:
    if not text:
        return None
    normalized = searchable_text(text)
    return int(any(term in normalized for term in terms))


def normalize_offer(offer: dict[str, Any], capture_id: int) -> dict[str, Any]:
    offer_id = compact_text(offer.get("id"))
    title_raw = offer.get("intitule") if isinstance(offer.get("intitule"), str) else ""
    description = offer.get("description") if isinstance(offer.get("description"), str) else ""
    if not offer_id or not title_raw or not description:
        raise NormalizationError(
            "Une offre ne contient pas les champs obligatoires id, intitule et description."
        )

    work_duration = offer.get("dureeTravailLibelle")
    weekly_hours = parse_weekly_hours(work_duration)
    context = offer.get("contexteTravail") or {}
    schedules = context.get("horaires") if isinstance(context, dict) else None
    schedule_text = " | ".join(
        compact_text(item) for item in schedules or [] if isinstance(item, str)
    )

    salary = offer.get("salaire") if isinstance(offer.get("salaire"), dict) else {}
    location = (
        offer.get("lieuTravail")
        if isinstance(offer.get("lieuTravail"), dict)
        else {}
    )
    employer = offer.get("entreprise") if isinstance(offer.get("entreprise"), dict) else {}
    origin = (
        offer.get("origineOffre")
        if isinstance(offer.get("origineOffre"), dict)
        else {}
    )
    contact = offer.get("contact") if isinstance(offer.get("contact"), dict) else {}

    travel_label = offer.get("deplacementLibelle")
    if isinstance(travel_label, str):
        travel_required = int(not searchable_text(travel_label).startswith("jamais"))
    else:
        travel_required = None

    contract_code = compact_text(offer.get("typeContrat")) or None
    values: dict[str, Any] = {
        "capture_id": capture_id,
        "source_offer_id": offer_id,
        "title_raw": title_raw,
        "title_normalized": compact_text(title_raw),
        "description_raw": description,
        "created_at_utc": offer.get("dateCreation"),
        "updated_at_utc": offer.get("dateActualisation"),
        "contract_code": contract_code,
        "contract_label": offer.get("typeContratLibelle"),
        "contract_family": CONTRACT_FAMILIES.get(contract_code or "", "other"),
        "contract_nature_code": offer.get("natureContrat"),
        "job_count": offer.get("nombrePostes"),
        "work_time_type": offer.get("dureeTravailLibelleConverti"),
        "weekly_hours": weekly_hours,
        "work_schedule_text": schedule_text or None,
        "works_at_night": optional_flag(schedule_text, ("travail de nuit", "nuit")),
        "works_shifted_hours": optional_flag(schedule_text, ("horaires decales",)),
        "works_weekend": optional_flag(schedule_text, ("week-end", "weekend")),
        "works_saturday": optional_flag(schedule_text, ("samedi",)),
        "works_sunday": optional_flag(schedule_text, ("dimanche",)),
        "work_context_json": json_text(context),
        "location_label": location.get("libelle"),
        "commune_code": location.get("commune"),
        "postal_code": location.get("codePostal"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "travel_code": offer.get("deplacementCode"),
        "travel_label": travel_label,
        "travel_required": travel_required,
        "employer_name": employer.get("nom"),
        "employer_is_anonymous": int(not bool(compact_text(employer.get("nom")))),
        "establishment_size_label": offer.get("trancheEffectifEtab"),
        "naf_code": offer.get("codeNAF"),
        "sector_code": offer.get("secteurActivite"),
        "sector_label": offer.get("secteurActiviteLibelle"),
        "rome_code": offer.get("romeCode"),
        "rome_label": offer.get("romeLibelle"),
        "experience_code": offer.get("experienceExige"),
        "experience_label": offer.get("experienceLibelle"),
        "experience_comment": offer.get("experienceCommentaire"),
        "qualification_code": offer.get("qualificationCode"),
        "qualification_label": offer.get("qualificationLibelle"),
        "skills_json": json_text(offer.get("competences", [])),
        "education_json": json_text(offer.get("formations", [])),
        "licences_json": json_text(offer.get("permis", [])),
        "professional_qualities_json": json_text(
            offer.get("qualitesProfessionnelles", [])
        ),
        "source_origin": origin.get("origine"),
        "source_url": origin.get("urlOrigine"),
        "application_url": contact.get("urlPostulation"),
        "raw_offer_json": json_text(offer),
    }
    values.update(salary_values(salary, weekly_hours))
    return values


def find_latest_capture() -> Path:
    candidates = sorted(DATA_DIR.glob(CAPTURE_PATTERN), key=lambda path: path.name)
    if not candidates:
        raise NormalizationError(
            f"Aucune capture {CAPTURE_PATTERN} trouvée dans {DATA_DIR}."
        )
    return candidates[-1]


def load_capture(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise NormalizationError(f"Impossible de lire {path} : {exc}") from exc

    try:
        document = json.loads(raw_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizationError(f"Capture JSON invalide : {exc}") from exc

    metadata = document.get("_capture")
    response = document.get("response")
    offers = response.get("resultats") if isinstance(response, dict) else None
    if not isinstance(metadata, dict) or not isinstance(offers, list):
        raise NormalizationError(
            "Structure invalide : _capture et response.resultats sont requis."
        )
    if not all(isinstance(offer, dict) for offer in offers):
        raise NormalizationError("response.resultats contient une offre invalide.")

    return metadata, offers, hashlib.sha256(raw_bytes).hexdigest()


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION,),
    )


def insert_capture(
    connection: sqlite3.Connection,
    capture_path: Path,
    metadata: dict[str, Any],
    offers: list[dict[str, Any]],
    source_sha256: str,
) -> int:
    existing = connection.execute(
        "SELECT id FROM captures WHERE source_sha256 = ?", (source_sha256,)
    ).fetchone()
    if existing:
        raise NormalizationError(
            f"Cette capture est déjà importée dans la base (capture #{existing[0]})."
        )

    captured_at = metadata.get("captured_at_utc")
    if not isinstance(captured_at, str) or not captured_at:
        raise NormalizationError("_capture.captured_at_utc est absent ou invalide.")

    cursor = connection.execute(
        """
        INSERT INTO captures(
            source, captured_at_utc, source_file, source_sha256, content_range,
            request_params_json, raw_capture_metadata_json, normalized_at_utc,
            offer_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            metadata.get("source") or SOURCE_NAME,
            captured_at,
            capture_path.name,
            source_sha256,
            metadata.get("content_range"),
            json_text(metadata.get("request_params", {})),
            json_text(metadata),
            datetime.now(timezone.utc).isoformat(),
            len(offers),
        ),
    )
    return int(cursor.lastrowid)


def insert_offers(
    connection: sqlite3.Connection,
    capture_id: int,
    offers: list[dict[str, Any]],
) -> tuple[int, int, int]:
    normalized = [normalize_offer(offer, capture_id) for offer in offers]
    if not normalized:
        return 0, 0, 0

    columns = list(normalized[0])
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO offers ({', '.join(columns)}) VALUES ({placeholders})"
    connection.executemany(sql, ([row[column] for column in columns] for row in normalized))

    parsed_salary = sum(row["salary_unit"] is not None for row in normalized)
    monthly_salary = sum(
        row["salary_monthly_gross_min"] is not None for row in normalized
    )
    return len(normalized), parsed_salary, monthly_salary


def main() -> int:
    args = parse_args()
    try:
        capture_path = (args.capture or find_latest_capture()).resolve()
        database_path = args.database.resolve()
        metadata, offers, source_sha256 = load_capture(capture_path)
        database_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(database_path) as connection:
            initialize_database(connection)
            capture_id = insert_capture(
                connection, capture_path, metadata, offers, source_sha256
            )
            imported, parsed_salary, monthly_salary = insert_offers(
                connection, capture_id, offers
            )
    except (NormalizationError, sqlite3.Error) as exc:
        print(f"Normalisation impossible : {exc}", file=sys.stderr)
        return 1

    print(f"Capture importée : #{capture_id} — {imported} offre(s).")
    print(f"Salaires structurés : {parsed_salary}/{imported}.")
    print(f"Équivalents mensuels calculables : {monthly_salary}/{imported}.")
    print(f"Base SQLite : {database_path}")
    print("Aucun filtre, verdict ou calcul de trajet n'a été appliqué.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
