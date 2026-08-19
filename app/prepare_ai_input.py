"""Prépare une entrée IA comparative locale sans exécuter de modèle.

La commande lit uniquement les résultats déjà enregistrés dans SQLite, valide
un profil minimisé approuvé et produit un nouvel artefact privé sous ``data/``.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_contract import (
    ContractError,
    INPUT_ARTIFACT_TYPE,
    INPUT_SCHEMA_VERSION,
    add_input_integrity,
    build_policy,
    canonical_opportunity_key,
    file_sha256,
    load_json_file,
    payload_sha256,
    validate_ai_comparative_input,
    validate_ai_evaluation_profile,
)


ELIGIBLE_STATUSES = ("KEEP", "REVIEW")
REQUIRED_TABLES = {
    "captures",
    "offers",
    "filter_results",
    "travel_results",
    "duplicate_runs",
    "duplicate_results",
}

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
OBFUSCATED_EMAIL_RE = re.compile(
    r"(?ix)\b[A-Z0-9._%+-]{1,64}\s*"
    r"(?:\[at\]|\(at\)|arobase)\s*"
    r"[A-Z0-9-]+(?:\s*(?:\[dot\]|\(dot\)|point)\s*[A-Z0-9-]+)+\b"
)
URL_RE = re.compile(
    r"(?ix)(?:"
    r"\b(?:https?://|www\.)[^\s\"'<>]+|"
    r"(?<![@\w.-])(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
    r"(?:fr|com|org|net|eu|io|co|info|biz|pro|jobs|uk|de|es|it|be|ch|nl)\b"
    r")"
)
PHONE_RE = re.compile(
    r"(?<!\d)(?:(?:\+|00)33\s*(?:\(0\)\s*)?|0)"
    r"[1-9](?:[ .-]?\d{2}){4}(?!\d)"
)
WINDOWS_PATH_RE = re.compile(
    r"(?i)(?<![A-Z0-9_])(?:[A-Z]:[\\/][^\s\"'<>|]+|"
    r"\\\\[A-Z0-9._$ -]+\\[^\s\"'<>|]+)"
)
UNIX_PATH_RE = re.compile(
    r"(?i)(?<![:\w])/(?:home|users|var|etc|opt|srv|tmp|mnt|usr|data)/"
    r"[^\s\"'<>|]+"
)
POSTAL_ADDRESS_RE = re.compile(
    r"(?ix)\b\d{1,4}\s*(?:bis|ter)?\s+"
    r"(?:rue|avenue|av\.?|boulevard|bd\.?|chemin|impasse|route|place|"
    r"all[ée]e|quai|cours)\s+"
    r"[A-ZÀ-ÖØ-öø-ÿ][A-ZÀ-ÖØ-öø-ÿ'’ -]{1,80}"
)
COORDINATE_PAIR_RE = re.compile(
    r"(?<!\d)[+-]?\d{1,2}\.\d{4,}\s*[,;]\s*[+-]?\d{1,3}\.\d{4,}(?!\d)"
)
APPLICATION_INSTRUCTION_RE = re.compile(
    r"(?i)(?:"
    r"\bpour\s+(?:postuler|candidater)\b|"
    r"\b(?:postulez|candidatez)\b|"
    r"\bmerci\s+d['’ ](?:envoyer|adresser|transmettre)\b|"
    r"\b(?:envoyez|adressez|transmettez|envoyer|adresser|transmettre)\b"
    r".{0,80}\b(?:cv|candidature|lettre de motivation)\b|"
    r"\b(?:cv|candidature|lettre de motivation)\b.{0,80}"
    r"\b(?:envoyer|adresser|transmettre)\b|"
    r"^\s*(?:contact|personne à contacter)\s*[:\-]|"
    r"\bcontact(?:er|ez)\s+(?:m\.?|mme|monsieur|madame|le service|la société)\b"
    r")"
)

NESTED_KEYS_TO_REMOVE = {
    "adresse",
    "application_url",
    "contact",
    "courriel",
    "email",
    "latitude",
    "longitude",
    "mail",
    "nom_contact",
    "telephone",
    "téléphone",
    "url",
}

ARTIFACT_FORBIDDEN_KEYS = {
    "application_status",
    "application_url",
    "final_verdict",
    "latitude",
    "longitude",
    "manual_classification",
    "manual_justification",
    "manual_priority",
    "origin_label",
    "provider_options_json",
    "provider_response_json",
    "raw_offer_json",
    "source_file",
    "source_url",
}


class PreparationError(RuntimeError):
    """Préparation impossible sans enfreindre le contrat."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prépare une entrée IA comparative locale sans appeler de modèle."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Construit un nouvel artefact privé.")
    build.add_argument("--database", type=Path, required=True)
    build.add_argument("--capture-id", type=int, required=True)
    build.add_argument("--profile", type=Path, required=True)
    build.add_argument("--source-profile", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def database_snapshot(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PreparationError(f"Base SQLite introuvable : {path}")
    before = path.stat()
    digest = file_sha256(path)
    after = path.stat()
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise PreparationError("La base SQLite a changé pendant le calcul de son hash.")
    return {
        "size_bytes": after.st_size,
        "modified_at_utc": datetime.fromtimestamp(
            after.st_mtime, timezone.utc
        ).isoformat(),
        "modified_at_ns": after.st_mtime_ns,
        "sha256": digest,
    }


def open_read_only_database(path: Path) -> sqlite3.Connection:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()[0]
        if query_only != 1:
            raise PreparationError("PRAGMA query_only n'a pas été activé.")
        connection.execute("PRAGMA temp_store=MEMORY")
        return connection
    except Exception as exc:
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
        if isinstance(exc, PreparationError):
            raise
        if isinstance(exc, sqlite3.Error):
            raise PreparationError(
                f"Ouverture SQLite en lecture seule impossible : {exc}"
            ) from exc
        raise


def check_database_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing = REQUIRED_TABLES - tables
    if missing:
        raise PreparationError(
            "Tables SQLite manquantes : " + ", ".join(sorted(missing))
        )


def decode_json_field(value: Any, label: str, expected_type: type) -> Any:
    if not isinstance(value, str):
        raise PreparationError(f"{label} n'est pas un texte JSON.")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PreparationError(f"{label} contient un JSON invalide : {exc}") from exc
    if not isinstance(parsed, expected_type):
        raise PreparationError(f"{label} n'a pas le type JSON attendu.")
    return parsed


def sanitize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(character if character in "\n\t" or ord(character) >= 32 else " " for character in text)
    retained: list[str] = []
    for line in text.split("\n"):
        fragments = re.split(r"(?<=[.!?])\s+", line)
        for fragment in fragments:
            if APPLICATION_INSTRUCTION_RE.search(fragment):
                continue
            cleaned = EMAIL_RE.sub("", fragment)
            cleaned = OBFUSCATED_EMAIL_RE.sub("", cleaned)
            cleaned = URL_RE.sub("", cleaned)
            cleaned = PHONE_RE.sub("", cleaned)
            cleaned = WINDOWS_PATH_RE.sub("", cleaned)
            cleaned = UNIX_PATH_RE.sub("", cleaned)
            cleaned = POSTAL_ADDRESS_RE.sub("", cleaned)
            cleaned = COORDINATE_PAIR_RE.sub("", cleaned)
            cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
            if cleaned:
                retained.append(cleaned)
    result = "\n".join(retained).strip()
    return result or None


def sanitize_nested(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value) or ""
    if isinstance(value, list):
        return [sanitize_nested(item) for item in value]
    if isinstance(value, dict):
        return {
            key: sanitize_nested(child)
            for key, child in value.items()
            if key.casefold() not in NESTED_KEYS_TO_REMOVE
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise PreparationError(f"Type non pris en charge dans une donnée normalisée : {type(value).__name__}")


def bool_or_none(value: Any) -> bool | None:
    return None if value is None else bool(value)


def build_offer_payload(row: sqlite3.Row) -> dict[str, Any]:
    salary_complements = sanitize_nested(
        decode_json_field(row["salary_complements_json"], "salary_complements_json", list)
    )
    work_context = sanitize_nested(
        decode_json_field(row["work_context_json"], "work_context_json", dict)
    )
    requirements = {
        "experience": {
            "code": sanitize_text(row["experience_code"]),
            "label": sanitize_text(row["experience_label"]),
            "comment": sanitize_text(row["experience_comment"]),
        },
        "qualification": {
            "code": sanitize_text(row["qualification_code"]),
            "label": sanitize_text(row["qualification_label"]),
        },
        "skills": sanitize_nested(
            decode_json_field(row["skills_json"], "skills_json", list)
        ),
        "education": sanitize_nested(
            decode_json_field(row["education_json"], "education_json", list)
        ),
        "licences_and_authorizations": sanitize_nested(
            decode_json_field(row["licences_json"], "licences_json", list)
        ),
        "professional_qualities": sanitize_nested(
            decode_json_field(
                row["professional_qualities_json"], "professional_qualities_json", list
            )
        ),
    }
    employer_name = None if bool(row["employer_is_anonymous"]) else sanitize_text(
        row["employer_name"]
    )
    return {
        "source_offer_id": str(row["source_offer_id"]),
        "title": sanitize_text(row["title_raw"]),
        "description_cleaned": sanitize_text(row["description_raw"]),
        "employer": {
            "name": employer_name,
            "is_anonymous": bool(row["employer_is_anonymous"]),
            "establishment_size": sanitize_text(row["establishment_size_label"]),
            "sector": {
                "code": sanitize_text(row["sector_code"]),
                "label": sanitize_text(row["sector_label"]),
            },
        },
        "contract": {
            "code": sanitize_text(row["contract_code"]),
            "label": sanitize_text(row["contract_label"]),
            "family": sanitize_text(row["contract_family"]),
            "nature_code": sanitize_text(row["contract_nature_code"]),
            "work_time_type": sanitize_text(row["work_time_type"]),
            "weekly_hours": row["weekly_hours"],
        },
        "schedule": {
            "text": sanitize_text(row["work_schedule_text"]),
            "work_context": work_context,
            "works_at_night": bool_or_none(row["works_at_night"]),
            "works_shifted_hours": bool_or_none(row["works_shifted_hours"]),
            "works_weekend": bool_or_none(row["works_weekend"]),
            "works_saturday": bool_or_none(row["works_saturday"]),
            "works_sunday": bool_or_none(row["works_sunday"]),
        },
        "salary": {
            "label_cleaned": sanitize_text(row["salary_label_raw"]),
            "comment_cleaned": sanitize_text(row["salary_comment_raw"]),
            "unit": sanitize_text(row["salary_unit"]),
            "amount_min": row["salary_amount_min"],
            "amount_max": row["salary_amount_max"],
            "payment_months": row["salary_payment_months"],
            "monthly_gross_min": row["salary_monthly_gross_min"],
            "monthly_gross_max": row["salary_monthly_gross_max"],
            "conversion_method": sanitize_text(row["salary_conversion_method"]),
            "complements": salary_complements,
        },
        "work_location": {"public_area": sanitize_text(row["location_label"])},
        "travel": {
            "duration_minutes": row["duration_minutes"],
            "distance_meters": row["distance_meters"],
            "band": sanitize_text(row["travel_band"]),
        },
        "professional_travel": {
            "code": sanitize_text(row["travel_code"]),
            "label": sanitize_text(row["travel_label"]),
            "required": bool_or_none(row["travel_required"]),
        },
        "requirements": requirements,
    }


def select_capture_and_versions(
    connection: sqlite3.Connection, capture_id: int
) -> tuple[sqlite3.Row, str, str]:
    capture = connection.execute(
        "SELECT id, source, captured_at_utc, source_sha256, offer_count "
        "FROM captures WHERE id = ?",
        (capture_id,),
    ).fetchone()
    if capture is None:
        raise PreparationError(f"Capture SQLite inconnue : {capture_id}")

    filter_versions = connection.execute(
        """
        SELECT f.rules_version, COUNT(*) AS row_count
        FROM offers AS o
        JOIN filter_results AS f ON f.offer_id = o.id
        WHERE o.capture_id = ?
        GROUP BY f.rules_version
        """,
        (capture_id,),
    ).fetchall()
    if len(filter_versions) != 1 or filter_versions[0]["row_count"] != capture["offer_count"]:
        raise PreparationError("Les résultats de filtres sont absents, incomplets ou multiversions.")

    duplicate_run = connection.execute(
        "SELECT detection_version FROM duplicate_runs WHERE capture_id = ?",
        (capture_id,),
    ).fetchone()
    if duplicate_run is None:
        raise PreparationError("La détection enregistrée des quasi-doublons est absente.")
    return capture, str(filter_versions[0]["rules_version"]), str(
        duplicate_run["detection_version"]
    )


def select_eligible_rows(
    connection: sqlite3.Connection, capture_id: int
) -> list[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT
            o.id, o.source_offer_id, o.title_raw, o.description_raw,
            o.contract_code, o.contract_label, o.contract_family,
            o.contract_nature_code, o.work_time_type, o.weekly_hours,
            o.work_schedule_text, o.works_at_night, o.works_shifted_hours,
            o.works_weekend, o.works_saturday, o.works_sunday,
            o.work_context_json, o.salary_label_raw, o.salary_comment_raw,
            o.salary_unit, o.salary_amount_min, o.salary_amount_max,
            o.salary_payment_months, o.salary_monthly_gross_min,
            o.salary_monthly_gross_max, o.salary_conversion_method,
            o.salary_complements_json, o.location_label, o.travel_code,
            o.travel_label, o.travel_required, o.employer_name,
            o.employer_is_anonymous, o.establishment_size_label,
            o.sector_code, o.sector_label, o.experience_code,
            o.experience_label, o.experience_comment, o.qualification_code,
            o.qualification_label, o.skills_json, o.education_json,
            o.licences_json, o.professional_qualities_json,
            f.status, f.review_reasons_json, f.warnings_json,
            f.schedule_penalty, t.distance_meters, t.duration_minutes,
            t.travel_band,
            d.group_key AS duplicate_group_key,
            d.group_size AS duplicate_group_size,
            d.representative_offer_id,
            representative.source_offer_id AS duplicate_representative_source_id
        FROM offers AS o
        JOIN filter_results AS f ON f.offer_id = o.id
        LEFT JOIN travel_results AS t ON t.offer_id = o.id
        LEFT JOIN duplicate_results AS d ON d.offer_id = o.id
        LEFT JOIN offers AS representative ON representative.id = d.representative_offer_id
        WHERE o.capture_id = ? AND f.status IN ('KEEP', 'REVIEW')
        ORDER BY o.source_offer_id
        """,
        (capture_id,),
    ).fetchall()
    if not rows:
        raise PreparationError("Aucune offre KEEP ou REVIEW n'est enregistrée.")
    missing_travel = [
        str(row["source_offer_id"]) for row in rows if row["travel_band"] is None
    ]
    if missing_travel:
        raise PreparationError(
            "Trajets enregistrés absents pour : " + ", ".join(missing_travel)
        )
    return rows


def select_duplicate_members(
    connection: sqlite3.Connection, capture_id: int
) -> dict[str, list[tuple[str, str]]]:
    rows = connection.execute(
        """
        SELECT d.group_key, member.source_offer_id, f.status
        FROM duplicate_results AS d
        JOIN offers AS member ON member.id = d.offer_id
        JOIN filter_results AS f ON f.offer_id = member.id
        WHERE d.capture_id = ?
        ORDER BY d.group_key, member.source_offer_id
        """,
        (capture_id,),
    ).fetchall()
    groups: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        groups.setdefault(str(row["group_key"]), []).append(
            (str(row["source_offer_id"]), str(row["status"]))
        )
    return groups


def build_opportunities(
    connection: sqlite3.Connection, capture_id: int
) -> list[dict[str, Any]]:
    rows = select_eligible_rows(connection, capture_id)
    group_members = select_duplicate_members(connection, capture_id)
    eligible_ids = {str(row["source_offer_id"]) for row in rows}
    opportunities: list[dict[str, Any]] = []

    for row in rows:
        source_offer_id = str(row["source_offer_id"])
        group_key = row["duplicate_group_key"]
        if group_key is None:
            offer_ids = [source_offer_id]
            representative_source_id = None
            group_size = 1
        else:
            representative_source_id = str(row["duplicate_representative_source_id"])
            if source_offer_id != representative_source_id:
                continue
            members = group_members.get(str(group_key), [])
            if not members:
                raise PreparationError(f"Membres absents pour le groupe {group_key}.")
            non_eligible = sorted(
                offer_id for offer_id, status in members if status not in ELIGIBLE_STATUSES
            )
            if non_eligible:
                raise PreparationError(
                    f"Le groupe {group_key} mélange des offres éligibles et non éligibles."
                )
            offer_ids = sorted({offer_id for offer_id, _status in members})
            group_size = int(row["duplicate_group_size"])
            if group_size != len(offer_ids):
                raise PreparationError(f"Taille incohérente pour le groupe {group_key}.")

        opportunity = {
            "opportunity_key": canonical_opportunity_key(offer_ids),
            "offer_ids": offer_ids,
            "scope": "specific_offer_only",
            "offer": build_offer_payload(row),
            "mechanical": {
                "status": str(row["status"]),
                "review_reasons": sanitize_nested(
                    decode_json_field(
                        row["review_reasons_json"], "review_reasons_json", list
                    )
                ),
                "warnings": sanitize_nested(
                    decode_json_field(row["warnings_json"], "warnings_json", list)
                ),
                "schedule_penalty": int(row["schedule_penalty"]),
            },
            "duplicates": {
                "group_key": None if group_key is None else str(group_key),
                "representative_offer_id": representative_source_id,
                "group_size": group_size,
            },
        }
        opportunities.append(opportunity)

    opportunities.sort(key=lambda item: item["opportunity_key"])
    covered_ids = {
        offer_id for opportunity in opportunities for offer_id in opportunity["offer_ids"]
    }
    if covered_ids != eligible_ids:
        missing = sorted(eligible_ids - covered_ids)
        extra = sorted(covered_ids - eligible_ids)
        raise PreparationError(
            f"Couverture des offres éligibles incohérente; absentes={missing}, supplémentaires={extra}."
        )
    return opportunities


def walk_document(value: Any, path: str = "$") -> list[tuple[str, str]]:
    strings: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            strings.extend(walk_document(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            strings.extend(walk_document(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        strings.append((path, value))
    return strings


def walk_keys(value: Any, path: str = "$") -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append((f"{path}.{key}", key))
            keys.extend(walk_keys(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            keys.extend(walk_keys(child, f"{path}[{index}]"))
    return keys


def privacy_check(document: dict[str, Any]) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {
        "email": [],
        "phone": [],
        "url": [],
        "local_path": [],
        "postal_address": [],
        "precise_coordinates": [],
        "contact_or_application_instruction": [],
        "forbidden_field": [],
    }
    for path, text in walk_document(document):
        if EMAIL_RE.search(text) or OBFUSCATED_EMAIL_RE.search(text):
            findings["email"].append(path)
        if not path.endswith("sha256") and PHONE_RE.search(text):
            findings["phone"].append(path)
        if URL_RE.search(text):
            findings["url"].append(path)
        if WINDOWS_PATH_RE.search(text) or UNIX_PATH_RE.search(text):
            findings["local_path"].append(path)
        if POSTAL_ADDRESS_RE.search(text):
            findings["postal_address"].append(path)
        if not path.endswith("sha256") and COORDINATE_PAIR_RE.search(text):
            findings["precise_coordinates"].append(path)
        if APPLICATION_INSTRUCTION_RE.search(text):
            findings["contact_or_application_instruction"].append(path)
    for path, key in walk_keys(document):
        if key.casefold() in ARTIFACT_FORBIDDEN_KEYS:
            findings["forbidden_field"].append(path)
    return findings


def ensure_privacy_checks_passed(findings: dict[str, list[str]]) -> None:
    failed = {name: paths for name, paths in findings.items() if paths}
    if failed:
        details = "; ".join(
            f"{name}={','.join(paths)}" for name, paths in sorted(failed.items())
        )
        raise PreparationError("Contrôle de confidentialité en échec : " + details)


def build_artifact(
    connection: sqlite3.Connection,
    capture_id: int,
    profile_document: dict[str, Any],
) -> dict[str, Any]:
    capture, filter_version, duplicate_version = select_capture_and_versions(
        connection, capture_id
    )
    opportunities = build_opportunities(connection, capture_id)
    profile_snapshot = profile_document["evaluation_profile"]
    policy = build_policy()
    profile_hash = payload_sha256(profile_snapshot)
    artifact: dict[str, Any] = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "artifact_type": INPUT_ARTIFACT_TYPE,
        "provenance": {
            "capture_id": int(capture["id"]),
            "capture_source_sha256": str(capture["source_sha256"]),
            "filter_rules_version": filter_version,
            "duplicate_detection_version": duplicate_version,
        },
        "policy": policy,
        "profile": {
            "profile_schema_version": int(profile_document["schema_version"]),
            "profile_payload_sha256": profile_hash,
            "snapshot": profile_snapshot,
        },
        "selection": {
            "eligible_mechanical_statuses": list(ELIGIBLE_STATUSES),
            "duplicate_policy": "stored_representative_only",
            "opportunity_count": len(opportunities),
            "covered_offer_id_count": sum(
                len(opportunity["offer_ids"]) for opportunity in opportunities
            ),
        },
        "opportunities": opportunities,
        "integrity": {
            "policy_payload_sha256": payload_sha256(policy),
            "profile_payload_sha256": profile_hash,
            "opportunities_payload_sha256": payload_sha256(opportunities),
        },
    }
    add_input_integrity(artifact)
    validate_ai_comparative_input(artifact)
    return artifact


def serialize_artifact(artifact: dict[str, Any]) -> str:
    return json.dumps(
        artifact,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"


def write_exclusive_and_validate(
    artifact: dict[str, Any], output_dir: Path, capture_id: int
) -> Path:
    serialized = serialize_artifact(artifact)
    parsed_in_memory = json.loads(serialized)
    validate_ai_comparative_input(parsed_in_memory)
    ensure_privacy_checks_passed(privacy_check(parsed_in_memory))

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_path = output_dir / f"ai_comparative_input_capture_{capture_id}_{timestamp}.json"
    created_by_this_run = False
    try:
        stream = output_path.open("x", encoding="utf-8", newline="\n")
        created_by_this_run = True
        with stream:
            stream.write(serialized)
        reloaded = load_json_file(output_path)
        validate_ai_comparative_input(reloaded)
        ensure_privacy_checks_passed(privacy_check(reloaded))
    except Exception:
        if created_by_this_run and output_path.exists():
            output_path.unlink()
        raise
    return output_path


def execute_build(args: argparse.Namespace) -> dict[str, Any]:
    database_path = args.database.resolve()
    profile_path = args.profile.resolve()
    source_profile_path = args.source_profile.resolve()

    database_before = database_snapshot(database_path)
    source_hash = file_sha256(source_profile_path)
    profile_document = validate_ai_evaluation_profile(
        load_json_file(profile_path),
        source_artifact_sha256=source_hash,
        require_local_approval=True,
        require_external_approval=False,
    )

    with closing(open_read_only_database(database_path)) as connection:
        check_database_schema(connection)
        artifact = build_artifact(connection, args.capture_id, profile_document)
        first_validation = validate_ai_comparative_input(artifact)
        findings = privacy_check(first_validation)
        ensure_privacy_checks_passed(findings)

    database_after = database_snapshot(database_path)
    if database_before != database_after:
        raise PreparationError(
            "La base SQLite a changé pendant la préparation ; aucun artefact n'a été écrit."
        )

    output_path = write_exclusive_and_validate(
        artifact, args.output_dir, args.capture_id
    )
    return {
        "output_path": str(output_path),
        "selection": artifact["selection"],
        "opportunity_keys": [
            opportunity["opportunity_key"] for opportunity in artifact["opportunities"]
        ],
        "provenance": artifact["provenance"],
        "integrity": artifact["integrity"],
        "profile_approval": {
            "approved_for_evaluation": profile_document["manual_review"][
                "approved_for_evaluation"
            ],
            "approved_for_external_evaluation": profile_document["manual_review"][
                "approved_for_external_evaluation"
            ],
        },
        "privacy_checks": {name: not paths for name, paths in findings.items()},
        "database_before": database_before,
        "database_after": database_after,
    }


def main() -> int:
    args = parse_args()
    try:
        if args.command != "build":
            raise PreparationError(f"Commande inconnue : {args.command}")
        summary = execute_build(args)
    except (ContractError, PreparationError, OSError, sqlite3.Error) as exc:
        print(f"Préparation impossible : {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
