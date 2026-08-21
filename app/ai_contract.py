"""Contrat commun pour les artefacts d'évaluation IA comparative.

Ce module ne dépend d'aucun fournisseur ou modèle. Il fournit uniquement la
canonicalisation, les hashes, les validations de schéma et les garde-fous
déterministes définis dans ``docs/CONTRAT_EVALUATION_IA.md``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


PROFILE_SCHEMA_VERSION = 1
INPUT_SCHEMA_VERSION = 1
PROFILE_ARTIFACT_TYPE = "ai_evaluation_profile"
INPUT_ARTIFACT_TYPE = "ai_comparative_input"
POLICY_VERSION = "comparative-classification-v1"

CLASSIFICATION_DEFINITIONS = {
    "credible": (
        "Candidature crédible immédiatement : le socle essentiel du poste précis "
        "est déjà exercé et aucun écart majeur ne bloque une candidature immédiate."
    ),
    "audacious": (
        "Candidature audacieuse mais défendable : des correspondances établies et "
        "des compétences transférables permettent une candidature immédiate malgré "
        "des écarts significatifs à expliquer et vérifier."
    ),
    "evolution": (
        "Piste d'évolution : le poste précis n'est pas accessible immédiatement, "
        "mais un socle exercé fournit une passerelle crédible après une formation "
        "ciblée ou une expérience intermédiaire réelle."
    ),
    "out_of_scope": (
        "Hors cible pour l'offre précise : incompatibilité avec les critères validés "
        "ou expertise technique, sectorielle ou principalement manuelle déjà requise "
        "et non compensable par une simple formation."
    ),
}
CLASSIFICATION_CODES = tuple(CLASSIFICATION_DEFINITIONS)

COMPARATIVE_GUARDRAILS = [
    "consultative_proposal_only",
    "mechanical_statuses_are_immutable",
    "manual_reference_is_unavailable_to_evaluator",
    "each_opportunity_is_evaluated_independently",
    "scope_is_specific_offer_only",
    "out_of_scope_never_auto_excludes_sector",
    "no_score_probability_priority_or_final_verdict",
]

PROFILE_PAYLOAD_KEYS = {
    "skills",
    "generalized_experiences",
    "education",
    "languages",
    "technical_boundaries",
    "preferences",
    "decision_criteria",
    "unknowns",
}
INPUT_TOP_LEVEL_KEYS = {
    "schema_version",
    "artifact_type",
    "provenance",
    "policy",
    "profile",
    "selection",
    "opportunities",
    "integrity",
}
FORBIDDEN_OPPORTUNITY_KEYS = {
    "application_status",
    "application_url",
    "final_verdict",
    "latitude",
    "longitude",
    "manual_classification",
    "manual_justification",
    "manual_priority",
    "origin_label",
    "priority",
    "probability",
    "provider_options_json",
    "provider_response_json",
    "raw_offer_json",
    "score",
    "source_url",
}

OFFER_KEYS = {
    "source_offer_id",
    "title",
    "description_cleaned",
    "employer",
    "contract",
    "schedule",
    "salary",
    "work_location",
    "travel",
    "professional_travel",
    "requirements",
}
EMPLOYER_KEYS = {"name", "is_anonymous", "establishment_size", "sector"}
SECTOR_KEYS = {"code", "label"}
CONTRACT_KEYS = {
    "code",
    "label",
    "family",
    "nature_code",
    "work_time_type",
    "weekly_hours",
}
SCHEDULE_KEYS = {
    "text",
    "work_context",
    "works_at_night",
    "works_shifted_hours",
    "works_weekend",
    "works_saturday",
    "works_sunday",
}
WORK_CONTEXT_OPTIONAL_KEYS = {"conditionsExercice", "horaires"}
SALARY_KEYS = {
    "label_cleaned",
    "comment_cleaned",
    "unit",
    "amount_min",
    "amount_max",
    "payment_months",
    "monthly_gross_min",
    "monthly_gross_max",
    "conversion_method",
    "complements",
}
SALARY_COMPLEMENT_OPTIONAL_KEYS = {"code", "libelle"}
WORK_LOCATION_KEYS = {"public_area"}
TRAVEL_KEYS = {"duration_minutes", "distance_meters", "band"}
PROFESSIONAL_TRAVEL_KEYS = {"code", "label", "required"}
REQUIREMENTS_KEYS = {
    "experience",
    "qualification",
    "skills",
    "education",
    "licences_and_authorizations",
    "professional_qualities",
}
EXPERIENCE_KEYS = {"code", "label", "comment"}
QUALIFICATION_KEYS = {"code", "label"}
SKILL_OPTIONAL_KEYS = {"code", "libelle", "exigence"}
EDUCATION_OPTIONAL_KEYS = {
    "codeFormation",
    "domaineLibelle",
    "exigence",
    "niveauLibelle",
}
LICENCE_OPTIONAL_KEYS = {"exigence", "libelle"}
PROFESSIONAL_QUALITY_OPTIONAL_KEYS = {"description", "libelle"}
MECHANICAL_KEYS = {"status", "review_reasons", "warnings", "schedule_penalty"}
DUPLICATES_KEYS = {"group_key", "representative_offer_id", "group_size"}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Artefact absent, incohérent ou non conforme au contrat."""


def canonical_json_bytes(value: Any) -> bytes:
    """Retourne le JSON canonique UTF-8 défini par le contrat."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"Valeur non canonicalisable en JSON : {exc}") from exc
    return text.encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def payload_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_json_constant(value: str) -> None:
    raise ContractError(f"Constante JSON non autorisée : {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Clé JSON dupliquée : {key}")
        result[key] = value
    return result


def parse_json_text(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except ContractError:
        raise
    except json.JSONDecodeError as exc:
        raise ContractError(f"JSON invalide : {exc}") from exc


def load_json_file(path: Path) -> Any:
    try:
        return parse_json_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"Lecture JSON impossible ({path}) : {exc}") from exc


def canonical_opportunity_key(offer_ids: list[str]) -> str:
    if not isinstance(offer_ids, list) or not offer_ids:
        raise ContractError("Une opportunité doit couvrir au moins un identifiant.")
    if any(not isinstance(value, str) or not value.strip() for value in offer_ids):
        raise ContractError("Tous les identifiants d'offres doivent être des chaînes.")
    normalized = sorted(set(offer_ids))
    return "offers:" + "|".join(normalized)


def build_policy() -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "classification_definitions": copy.deepcopy(CLASSIFICATION_DEFINITIONS),
        "guardrails": list(COMPARATIVE_GUARDRAILS),
    }


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} doit être un objet JSON.")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} doit être un tableau JSON.")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractError(
            f"Clés invalides pour {label}; absentes={missing}, supplémentaires={extra}."
        )


def _require_known_keys(
    value: dict[str, Any],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required - optional)
    if missing or extra:
        raise ContractError(
            f"Clés invalides pour {label}; absentes={missing}, supplémentaires={extra}."
        )


def _require_integer(value: Any, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ContractError(f"{label} doit être un entier JSON.")
    if minimum is not None and value < minimum:
        raise ContractError(f"{label} doit être supérieur ou égal à {minimum}.")
    return value


def _require_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ContractError(f"{label} doit être booléen.")
    return value


def _require_bool_or_none(value: Any, label: str) -> bool | None:
    if value is not None:
        _require_bool(value, label)
    return value


def _require_number_or_none(value: Any, label: str) -> int | float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ContractError(f"{label} doit être un nombre JSON fini ou null.")
    return value


def _require_string_or_none(value: Any, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ContractError(f"{label} doit être une chaîne ou null.")
    return value


def _require_string_list(value: Any, label: str) -> list[Any]:
    items = _require_list(value, label)
    if any(not isinstance(item, str) for item in items):
        raise ContractError(f"{label} doit contenir uniquement des chaînes.")
    return items


def _validate_optional_string_object(
    value: Any,
    label: str,
    allowed_keys: set[str],
) -> dict[str, Any]:
    item = _require_mapping(value, label)
    _require_known_keys(item, set(), allowed_keys, label)
    for key, child in item.items():
        _require_string_or_none(child, f"{label}.{key}")
    return item


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{label} doit être un SHA-256 hexadécimal minuscule.")
    return value


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} doit être une chaîne non vide.")
    return value


def validate_ai_evaluation_profile(
    document: Any,
    *,
    source_artifact_sha256: str | None = None,
    require_local_approval: bool = False,
    require_external_approval: bool = False,
) -> dict[str, Any]:
    profile_document = _require_mapping(document, "ai_evaluation_profile")
    _require_exact_keys(
        profile_document,
        {
            "schema_version",
            "artifact_type",
            "source",
            "manual_review",
            "evaluation_profile",
            "integrity",
        },
        "ai_evaluation_profile",
    )
    _require_integer(profile_document["schema_version"], "schema_version", minimum=1)
    if profile_document["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise ContractError("Version de profil IA non prise en charge.")
    if profile_document["artifact_type"] != PROFILE_ARTIFACT_TYPE:
        raise ContractError("artifact_type du profil IA invalide.")

    source = _require_mapping(profile_document["source"], "source")
    _require_exact_keys(source, {"validation_date", "source_artifact_sha256"}, "source")
    _require_non_empty_string(source["validation_date"], "source.validation_date")
    stored_source_hash = _require_sha256(
        source["source_artifact_sha256"], "source.source_artifact_sha256"
    )
    if source_artifact_sha256 is not None and stored_source_hash != source_artifact_sha256:
        raise ContractError("Le hash du profil professionnel source a changé.")

    manual_review = _require_mapping(profile_document["manual_review"], "manual_review")
    _require_exact_keys(
        manual_review,
        {
            "status",
            "reviewed_at_utc",
            "approved_for_evaluation",
            "approved_for_external_evaluation",
            "privacy_checks",
        },
        "manual_review",
    )
    if manual_review["status"] not in {"pending", "approved"}:
        raise ContractError("manual_review.status doit valoir pending ou approved.")
    for field in ("approved_for_evaluation", "approved_for_external_evaluation"):
        _require_bool(manual_review[field], f"manual_review.{field}")
    privacy_checks = _require_mapping(
        manual_review["privacy_checks"], "manual_review.privacy_checks"
    )
    if not privacy_checks:
        raise ContractError("Les contrôles de confidentialité sont absents.")
    if any(type(value) is not bool for value in privacy_checks.values()):
        raise ContractError("Tous les contrôles de confidentialité doivent être booléens.")

    evaluation_profile = _require_mapping(
        profile_document["evaluation_profile"], "evaluation_profile"
    )
    _require_exact_keys(evaluation_profile, PROFILE_PAYLOAD_KEYS, "evaluation_profile")
    for field in (
        "skills",
        "generalized_experiences",
        "education",
        "languages",
        "technical_boundaries",
        "unknowns",
    ):
        _require_list(evaluation_profile[field], f"evaluation_profile.{field}")
    _require_mapping(evaluation_profile["preferences"], "evaluation_profile.preferences")
    _require_mapping(
        evaluation_profile["decision_criteria"], "evaluation_profile.decision_criteria"
    )

    integrity = _require_mapping(profile_document["integrity"], "integrity")
    _require_exact_keys(integrity, {"evaluation_profile_sha256"}, "integrity")
    stored_profile_hash = _require_sha256(
        integrity["evaluation_profile_sha256"], "integrity.evaluation_profile_sha256"
    )
    calculated_profile_hash = payload_sha256(evaluation_profile)
    if stored_profile_hash != calculated_profile_hash:
        raise ContractError("Le hash canonique de evaluation_profile est invalide.")

    if require_local_approval:
        if manual_review["status"] != "approved":
            raise ContractError("Le profil n'a pas été approuvé par relecture humaine.")
        if not manual_review["approved_for_evaluation"]:
            raise ContractError("Le profil n'est pas autorisé pour une évaluation locale.")
        if not isinstance(manual_review["reviewed_at_utc"], str) or not manual_review[
            "reviewed_at_utc"
        ].strip():
            raise ContractError("La date de relecture humaine est absente.")
        failed_checks = sorted(
            key for key, value in privacy_checks.items() if value is not True
        )
        if failed_checks:
            raise ContractError(
                "Contrôles de confidentialité non réussis : " + ", ".join(failed_checks)
            )
    if require_external_approval and not manual_review[
        "approved_for_external_evaluation"
    ]:
        raise ContractError("Le profil n'est pas autorisé pour une évaluation externe.")

    return profile_document


def compute_input_payload_sha256(document: dict[str, Any]) -> str:
    """Hash de l'entrée sans le seul champ qui contient ce hash."""

    logical_copy = copy.deepcopy(_require_mapping(document, "ai_comparative_input"))
    integrity = _require_mapping(logical_copy.get("integrity"), "integrity")
    integrity.pop("input_payload_sha256", None)
    return payload_sha256(logical_copy)


def add_input_integrity(document: dict[str, Any]) -> dict[str, Any]:
    """Ajoute les quatre hashes sans utiliser de valeur neutre temporaire."""

    if "input_payload_sha256" in _require_mapping(document.get("integrity"), "integrity"):
        raise ContractError("input_payload_sha256 existe déjà avant sa construction.")
    integrity = document["integrity"]
    integrity["input_payload_sha256"] = compute_input_payload_sha256(document)
    return document


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(key)
            keys.extend(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(_walk_keys(child))
    return keys


def _validate_offer_payload(value: Any, label: str) -> dict[str, Any]:
    offer = _require_mapping(value, label)
    _require_exact_keys(offer, OFFER_KEYS, label)
    _require_non_empty_string(offer["source_offer_id"], f"{label}.source_offer_id")
    for field in ("title", "description_cleaned"):
        _require_string_or_none(offer[field], f"{label}.{field}")

    employer = _require_mapping(offer["employer"], f"{label}.employer")
    _require_exact_keys(employer, EMPLOYER_KEYS, f"{label}.employer")
    _require_string_or_none(employer["name"], f"{label}.employer.name")
    _require_bool(employer["is_anonymous"], f"{label}.employer.is_anonymous")
    _require_string_or_none(
        employer["establishment_size"], f"{label}.employer.establishment_size"
    )
    sector = _require_mapping(employer["sector"], f"{label}.employer.sector")
    _require_exact_keys(sector, SECTOR_KEYS, f"{label}.employer.sector")
    for field in SECTOR_KEYS:
        _require_string_or_none(sector[field], f"{label}.employer.sector.{field}")

    contract = _require_mapping(offer["contract"], f"{label}.contract")
    _require_exact_keys(contract, CONTRACT_KEYS, f"{label}.contract")
    for field in CONTRACT_KEYS - {"weekly_hours"}:
        _require_string_or_none(contract[field], f"{label}.contract.{field}")
    _require_number_or_none(contract["weekly_hours"], f"{label}.contract.weekly_hours")

    schedule = _require_mapping(offer["schedule"], f"{label}.schedule")
    _require_exact_keys(schedule, SCHEDULE_KEYS, f"{label}.schedule")
    _require_string_or_none(schedule["text"], f"{label}.schedule.text")
    work_context = _require_mapping(
        schedule["work_context"], f"{label}.schedule.work_context"
    )
    _require_known_keys(
        work_context,
        set(),
        WORK_CONTEXT_OPTIONAL_KEYS,
        f"{label}.schedule.work_context",
    )
    for field, items in work_context.items():
        _require_string_list(items, f"{label}.schedule.work_context.{field}")
    for field in SCHEDULE_KEYS - {"text", "work_context"}:
        _require_bool_or_none(schedule[field], f"{label}.schedule.{field}")

    salary = _require_mapping(offer["salary"], f"{label}.salary")
    _require_exact_keys(salary, SALARY_KEYS, f"{label}.salary")
    for field in {
        "label_cleaned",
        "comment_cleaned",
        "unit",
        "conversion_method",
    }:
        _require_string_or_none(salary[field], f"{label}.salary.{field}")
    for field in {
        "amount_min",
        "amount_max",
        "payment_months",
        "monthly_gross_min",
        "monthly_gross_max",
    }:
        _require_number_or_none(salary[field], f"{label}.salary.{field}")
    complements = _require_list(salary["complements"], f"{label}.salary.complements")
    for index, item in enumerate(complements):
        _validate_optional_string_object(
            item,
            f"{label}.salary.complements[{index}]",
            SALARY_COMPLEMENT_OPTIONAL_KEYS,
        )

    work_location = _require_mapping(
        offer["work_location"], f"{label}.work_location"
    )
    _require_exact_keys(work_location, WORK_LOCATION_KEYS, f"{label}.work_location")
    _require_string_or_none(
        work_location["public_area"], f"{label}.work_location.public_area"
    )

    travel = _require_mapping(offer["travel"], f"{label}.travel")
    _require_exact_keys(travel, TRAVEL_KEYS, f"{label}.travel")
    _require_number_or_none(
        travel["duration_minutes"], f"{label}.travel.duration_minutes"
    )
    _require_number_or_none(
        travel["distance_meters"], f"{label}.travel.distance_meters"
    )
    _require_string_or_none(travel["band"], f"{label}.travel.band")

    professional_travel = _require_mapping(
        offer["professional_travel"], f"{label}.professional_travel"
    )
    _require_exact_keys(
        professional_travel,
        PROFESSIONAL_TRAVEL_KEYS,
        f"{label}.professional_travel",
    )
    for field in {"code", "label"}:
        _require_string_or_none(
            professional_travel[field], f"{label}.professional_travel.{field}"
        )
    _require_bool_or_none(
        professional_travel["required"], f"{label}.professional_travel.required"
    )

    requirements = _require_mapping(offer["requirements"], f"{label}.requirements")
    _require_exact_keys(requirements, REQUIREMENTS_KEYS, f"{label}.requirements")
    experience = _require_mapping(
        requirements["experience"], f"{label}.requirements.experience"
    )
    _require_exact_keys(experience, EXPERIENCE_KEYS, f"{label}.requirements.experience")
    for field in EXPERIENCE_KEYS:
        _require_string_or_none(
            experience[field], f"{label}.requirements.experience.{field}"
        )
    qualification = _require_mapping(
        requirements["qualification"], f"{label}.requirements.qualification"
    )
    _require_exact_keys(
        qualification, QUALIFICATION_KEYS, f"{label}.requirements.qualification"
    )
    for field in QUALIFICATION_KEYS:
        _require_string_or_none(
            qualification[field], f"{label}.requirements.qualification.{field}"
        )

    item_schemas = {
        "skills": SKILL_OPTIONAL_KEYS,
        "education": EDUCATION_OPTIONAL_KEYS,
        "licences_and_authorizations": LICENCE_OPTIONAL_KEYS,
        "professional_qualities": PROFESSIONAL_QUALITY_OPTIONAL_KEYS,
    }
    for field, allowed_keys in item_schemas.items():
        items = _require_list(requirements[field], f"{label}.requirements.{field}")
        for index, item in enumerate(items):
            _validate_optional_string_object(
                item,
                f"{label}.requirements.{field}[{index}]",
                allowed_keys,
            )
    return offer


def validate_ai_comparative_input(document: Any) -> dict[str, Any]:
    artifact = _require_mapping(document, "ai_comparative_input")
    _require_exact_keys(artifact, INPUT_TOP_LEVEL_KEYS, "ai_comparative_input")
    _require_integer(artifact["schema_version"], "schema_version", minimum=1)
    if artifact["schema_version"] != INPUT_SCHEMA_VERSION:
        raise ContractError("Version d'entrée IA non prise en charge.")
    if artifact["artifact_type"] != INPUT_ARTIFACT_TYPE:
        raise ContractError("artifact_type de l'entrée IA invalide.")

    provenance = _require_mapping(artifact["provenance"], "provenance")
    _require_exact_keys(
        provenance,
        {
            "capture_id",
            "capture_source_sha256",
            "filter_rules_version",
            "duplicate_detection_version",
        },
        "provenance",
    )
    _require_integer(provenance["capture_id"], "provenance.capture_id", minimum=1)
    _require_sha256(provenance["capture_source_sha256"], "capture_source_sha256")
    _require_non_empty_string(provenance["filter_rules_version"], "filter_rules_version")
    _require_non_empty_string(
        provenance["duplicate_detection_version"], "duplicate_detection_version"
    )

    policy = _require_mapping(artifact["policy"], "policy")
    _require_exact_keys(
        policy,
        {"policy_version", "classification_definitions", "guardrails"},
        "policy",
    )
    if policy["policy_version"] != POLICY_VERSION:
        raise ContractError("Version de politique comparative invalide.")
    if policy["classification_definitions"] != CLASSIFICATION_DEFINITIONS:
        raise ContractError("Les quatre définitions de classification ont changé.")
    if policy["guardrails"] != COMPARATIVE_GUARDRAILS:
        raise ContractError("Les garde-fous comparatifs sont incomplets ou réordonnés.")

    profile = _require_mapping(artifact["profile"], "profile")
    _require_exact_keys(
        profile,
        {"profile_schema_version", "profile_payload_sha256", "snapshot"},
        "profile",
    )
    _require_integer(
        profile["profile_schema_version"], "profile.profile_schema_version", minimum=1
    )
    if profile["profile_schema_version"] != PROFILE_SCHEMA_VERSION:
        raise ContractError("Version du snapshot de profil invalide.")
    snapshot = _require_mapping(profile["snapshot"], "profile.snapshot")
    _require_exact_keys(snapshot, PROFILE_PAYLOAD_KEYS, "profile.snapshot")
    stored_profile_hash = _require_sha256(
        profile["profile_payload_sha256"], "profile.profile_payload_sha256"
    )
    if stored_profile_hash != payload_sha256(snapshot):
        raise ContractError("Le hash du snapshot de profil est invalide.")

    selection = _require_mapping(artifact["selection"], "selection")
    _require_exact_keys(
        selection,
        {
            "eligible_mechanical_statuses",
            "duplicate_policy",
            "opportunity_count",
            "covered_offer_id_count",
        },
        "selection",
    )
    if selection["eligible_mechanical_statuses"] != ["KEEP", "REVIEW"]:
        raise ContractError("Les seuls statuts mécaniques éligibles sont KEEP et REVIEW.")
    if selection["duplicate_policy"] != "stored_representative_only":
        raise ContractError("La politique de représentants de doublons est invalide.")
    _require_integer(
        selection["opportunity_count"], "selection.opportunity_count", minimum=1
    )
    _require_integer(
        selection["covered_offer_id_count"],
        "selection.covered_offer_id_count",
        minimum=1,
    )

    opportunities = _require_list(artifact["opportunities"], "opportunities")
    if not opportunities:
        raise ContractError("L'entrée ne contient aucune opportunité.")
    seen_keys: set[str] = set()
    covered_ids: set[str] = set()
    for index, raw_opportunity in enumerate(opportunities):
        opportunity = _require_mapping(raw_opportunity, f"opportunities[{index}]")
        _require_exact_keys(
            opportunity,
            {"opportunity_key", "offer_ids", "scope", "offer", "mechanical", "duplicates"},
            f"opportunities[{index}]",
        )
        offer_ids = _require_list(opportunity["offer_ids"], "offer_ids")
        if any(not isinstance(value, str) for value in offer_ids):
            raise ContractError("Les offer_ids doivent être des chaînes.")
        if offer_ids != sorted(set(offer_ids)):
            raise ContractError("Les offer_ids doivent être triés et dédupliqués.")
        expected_key = canonical_opportunity_key(offer_ids)
        if opportunity["opportunity_key"] != expected_key:
            raise ContractError(f"Clé canonique invalide : {opportunity['opportunity_key']}")
        if expected_key in seen_keys:
            raise ContractError(f"Clé canonique dupliquée : {expected_key}")
        overlap = covered_ids.intersection(offer_ids)
        if overlap:
            raise ContractError("Identifiants couverts par plusieurs opportunités : " + ", ".join(sorted(overlap)))
        seen_keys.add(expected_key)
        covered_ids.update(offer_ids)
        if opportunity["scope"] != "specific_offer_only":
            raise ContractError("Chaque opportunité doit avoir scope=specific_offer_only.")

        offer = _validate_offer_payload(
            opportunity["offer"], f"opportunities[{index}].offer"
        )
        source_offer_id = offer.get("source_offer_id")
        if source_offer_id not in offer_ids:
            raise ContractError("L'offre représentative n'appartient pas à offer_ids.")
        mechanical = _require_mapping(opportunity["mechanical"], "mechanical")
        _require_exact_keys(
            mechanical,
            MECHANICAL_KEYS,
            "mechanical",
        )
        if mechanical.get("status") not in {"KEEP", "REVIEW"}:
            raise ContractError("Une opportunité doit provenir de KEEP ou REVIEW.")
        _require_string_list(mechanical["review_reasons"], "mechanical.review_reasons")
        _require_string_list(mechanical["warnings"], "mechanical.warnings")
        _require_integer(
            mechanical["schedule_penalty"], "mechanical.schedule_penalty", minimum=0
        )
        duplicates = _require_mapping(opportunity["duplicates"], "duplicates")
        _require_exact_keys(
            duplicates,
            DUPLICATES_KEYS,
            "duplicates",
        )
        representative = duplicates.get("representative_offer_id")
        if representative is not None and representative != source_offer_id:
            raise ContractError("Le représentant du groupe ne correspond pas à l'offre transmise.")
        _require_integer(duplicates["group_size"], "duplicates.group_size", minimum=1)
        if duplicates["group_size"] != len(offer_ids):
            raise ContractError("duplicates.group_size ne correspond pas à offer_ids.")
        if duplicates["group_key"] is None:
            if representative is not None or len(offer_ids) != 1:
                raise ContractError("Une offre hors groupe ne doit pas déclarer de représentant.")
        else:
            _require_non_empty_string(duplicates["group_key"], "duplicates.group_key")
            if representative is None or len(offer_ids) < 2:
                raise ContractError("Un groupe doit déclarer son représentant et ses membres.")
        forbidden = sorted(set(_walk_keys(opportunity)) & FORBIDDEN_OPPORTUNITY_KEYS)
        if forbidden:
            raise ContractError("Champs interdits dans une opportunité : " + ", ".join(forbidden))

    if selection["opportunity_count"] != len(opportunities):
        raise ContractError("selection.opportunity_count est incohérent.")
    if selection["covered_offer_id_count"] != len(covered_ids):
        raise ContractError("selection.covered_offer_id_count est incohérent.")

    integrity = _require_mapping(artifact["integrity"], "integrity")
    _require_exact_keys(
        integrity,
        {
            "policy_payload_sha256",
            "profile_payload_sha256",
            "opportunities_payload_sha256",
            "input_payload_sha256",
        },
        "integrity",
    )
    expected_hashes = {
        "policy_payload_sha256": payload_sha256(policy),
        "profile_payload_sha256": payload_sha256(snapshot),
        "opportunities_payload_sha256": payload_sha256(opportunities),
        "input_payload_sha256": compute_input_payload_sha256(artifact),
    }
    for name, expected in expected_hashes.items():
        stored = _require_sha256(integrity[name], f"integrity.{name}")
        if stored != expected:
            raise ContractError(f"Hash invalide : integrity.{name}")
    if integrity["profile_payload_sha256"] != profile["profile_payload_sha256"]:
        raise ContractError("Les deux références au hash de profil divergent.")

    return artifact


# Foundation v2 -------------------------------------------------------------
#
# These validators deliberately do not extend the v1 input artifact.  A v2
# preparation will be introduced later; for now callers provide a prepared
# opportunity, its domain provenance and its profile snapshot explicitly.

V2_SCHEMA_VERSION = 2
V2_EVALUATION_ARTIFACT_TYPE = "ai_opportunity_evaluation"

REQUIREMENT_KINDS_V2 = {
    "education",
    "licence_or_authorization",
    "certification",
    "skill",
    "experience",
    "responsibility",
    "working_condition",
    "other",
}
EXPECTATIONS_V2 = {"required", "desired", "unknown"}
CENTRALITIES_V2 = {"core", "supporting", "unknown"}
ASSESSMENTS_V2 = {"established", "transferable", "gap", "missing"}

_PREPARED_OPPORTUNITY_V2_KEYS = {
    "offer",
    "normalized_requirements",
    "domain_text_units",
    "domain_inputs",
    "deterministic_conditions",
}
_NORMALIZED_REQUIREMENT_V2_KEYS = {
    "requirement_id",
    "source_path",
    "kind",
    "label",
    "source_code",
    "expectation_source_code",
    "expectation",
    "centrality",
}
_DOMAIN_TEXT_UNIT_V2_KEYS = {"unit_id", "source_path", "source_excerpt"}
_DOMAIN_INPUT_V2_KEYS = {
    "domain_id",
    "domain",
    "source_unit_ids",
    "source_path",
    "source_excerpt",
    "centrality",
}
_REQUIREMENT_COVERAGE_V2_KEYS = {
    "requirement_id",
    "source_path",
    "kind",
    "label",
    "expectation",
    "centrality",
    "assessment",
    "profile_evidence_paths",
    "reason",
}
_DOMAIN_COVERAGE_V2_KEYS = {
    "domain_id",
    "domain",
    "source_unit_ids",
    "source_path",
    "source_excerpt",
    "centrality",
    "assessment",
    "profile_evidence_paths",
    "reason",
}
_DOMAIN_PROVENANCE_V2_KEYS = {
    "segmentation_version",
    "segmentation_rules_sha256",
    "segmentation_schema_sha256",
    "extractor_version",
    "extractor_instruction_sha256",
    "extractor_schema_sha256",
    "extractor_model_identifier",
    "extractor_model_sha256",
}
_DOMAIN_INTEGRITY_V2_KEYS = {
    "domain_extraction_payload_sha256",
    "domain_inputs_payload_sha256",
}
_DETERMINISTIC_CONDITION_NAMES_V2 = {
    "salary",
    "commute",
    "schedule",
    "contract_type",
    "employer_size",
    "team_size",
    "functional_support",
}
_EVALUATION_RESULT_V2_KEYS = {
    "requirement_coverage",
    "domain_coverage",
    "deterministic_conditions",
    "classification_code",
    "classification_justification",
    "missing_information",
}
_EVALUATION_DOCUMENT_V2_KEYS = {
    "schema_version",
    "artifact_type",
    "evaluation",
    "integrity",
}


def _require_non_empty_string_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, label)


def _require_enum(value: Any, allowed: set[str], label: str) -> str:
    value = _require_non_empty_string(value, label)
    if value not in allowed:
        raise ContractError(f"{label} a une valeur non autorisée : {value}")
    return value


def _decode_json_pointer_token(token: str, label: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(token):
        character = token[index]
        if character != "~":
            result.append(character)
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise ContractError(f"{label} contient un échappement RFC 6901 invalide.")
        result.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(result)


def resolve_json_pointer(document: Any, pointer: Any, label: str = "JSON Pointer") -> Any:
    """Résout strictement un JSON Pointer RFC 6901 dans un objet JSON."""

    if not isinstance(pointer, str):
        raise ContractError(f"{label} doit être une chaîne.")
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ContractError(f"{label} doit être vide ou commencer par '/'.")

    current = document
    for raw_token in pointer[1:].split("/"):
        token = _decode_json_pointer_token(raw_token, label)
        if isinstance(current, dict):
            if token not in current:
                raise ContractError(f"{label} ne résout aucune clé : {pointer}")
            current = current[token]
            continue
        if isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise ContractError(f"{label} contient un index de tableau invalide : {pointer}")
            position = int(token)
            if position >= len(current):
                raise ContractError(f"{label} dépasse un tableau : {pointer}")
            current = current[position]
            continue
        raise ContractError(f"{label} traverse une valeur scalaire : {pointer}")
    return current


def compute_requirement_id(
    source_path: Any,
    kind: Any,
    source_code: Any,
    expectation_source_code: Any,
    label: Any,
) -> str:
    """Calcule l'identifiant stable défini par le contrat v2."""

    source_path = _require_non_empty_string(source_path, "source_path")
    kind = _require_enum(kind, REQUIREMENT_KINDS_V2, "kind")
    source_code = _require_non_empty_string_or_none(source_code, "source_code")
    expectation_source_code = _require_non_empty_string_or_none(
        expectation_source_code, "expectation_source_code"
    )
    label = _require_non_empty_string(label, "label")
    material = "\n".join(
        (
            source_path,
            kind,
            source_code or "",
            expectation_source_code or "",
            label,
        )
    )
    return "req:" + sha256_bytes(material.encode("utf-8"))


def _expected_expectation_v2(expectation_source_code: str | None) -> str:
    if expectation_source_code == "E":
        return "required"
    if expectation_source_code == "S":
        return "desired"
    return "unknown"


def _validate_source_excerpt(
    prepared_opportunity: dict[str, Any], source_path: Any, source_excerpt: Any, label: str
) -> None:
    source = resolve_json_pointer(prepared_opportunity, source_path, f"{label}.source_path")
    source_excerpt = _require_non_empty_string(source_excerpt, f"{label}.source_excerpt")
    if not isinstance(source, str) or source_excerpt not in source:
        raise ContractError(f"{label}.source_excerpt n'est pas un extrait exact de sa source.")


def _validate_normalized_requirements_v2(
    prepared_opportunity: dict[str, Any], value: Any
) -> list[dict[str, Any]]:
    requirements = _require_list(value, "normalized_requirements")
    seen_ids: set[str] = set()
    for index, raw_requirement in enumerate(requirements):
        label = f"normalized_requirements[{index}]"
        requirement = _require_mapping(raw_requirement, label)
        _require_exact_keys(requirement, _NORMALIZED_REQUIREMENT_V2_KEYS, label)
        requirement_id = _require_non_empty_string(requirement["requirement_id"], f"{label}.requirement_id")
        expected_id = compute_requirement_id(
            requirement["source_path"],
            requirement["kind"],
            requirement["source_code"],
            requirement["expectation_source_code"],
            requirement["label"],
        )
        if requirement_id != expected_id:
            raise ContractError(f"{label}.requirement_id est invalide.")
        if requirement_id in seen_ids:
            raise ContractError("normalized_requirements contient un requirement_id dupliqué.")
        seen_ids.add(requirement_id)
        resolve_json_pointer(prepared_opportunity, requirement["source_path"], f"{label}.source_path")
        _require_enum(requirement["centrality"], CENTRALITIES_V2, f"{label}.centrality")
        expected_expectation = _expected_expectation_v2(requirement["expectation_source_code"])
        if requirement["expectation"] != expected_expectation:
            raise ContractError(f"{label}.expectation ne correspond pas au code source.")
    return requirements


def _validate_domain_text_units_v2(
    prepared_opportunity: dict[str, Any], value: Any
) -> dict[str, dict[str, Any]]:
    units = _require_list(value, "domain_text_units")
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw_unit in enumerate(units):
        label = f"domain_text_units[{index}]"
        unit = _require_mapping(raw_unit, label)
        _require_exact_keys(unit, _DOMAIN_TEXT_UNIT_V2_KEYS, label)
        unit_id = _require_non_empty_string(unit["unit_id"], f"{label}.unit_id")
        if unit_id in by_id:
            raise ContractError("domain_text_units contient un unit_id dupliqué.")
        _validate_source_excerpt(prepared_opportunity, unit["source_path"], unit["source_excerpt"], label)
        by_id[unit_id] = unit
    return by_id


def _validate_domain_inputs_v2(
    prepared_opportunity: dict[str, Any], units_by_id: dict[str, dict[str, Any]], value: Any
) -> list[dict[str, Any]]:
    domains = _require_list(value, "domain_inputs")
    seen_ids: set[str] = set()
    for index, raw_domain in enumerate(domains):
        label = f"domain_inputs[{index}]"
        domain = _require_mapping(raw_domain, label)
        _require_exact_keys(domain, _DOMAIN_INPUT_V2_KEYS, label)
        domain_id = _require_non_empty_string(domain["domain_id"], f"{label}.domain_id")
        if domain_id in seen_ids:
            raise ContractError("domain_inputs contient un domain_id dupliqué.")
        seen_ids.add(domain_id)
        _require_non_empty_string(domain["domain"], f"{label}.domain")
        source_unit_ids = _require_string_list(domain["source_unit_ids"], f"{label}.source_unit_ids")
        if not source_unit_ids or len(source_unit_ids) != len(set(source_unit_ids)):
            raise ContractError(f"{label}.source_unit_ids doit être non vide et sans doublon.")
        unknown_units = sorted(set(source_unit_ids) - set(units_by_id))
        if unknown_units:
            raise ContractError(f"{label} référence des unités inconnues : {', '.join(unknown_units)}")
        _validate_source_excerpt(prepared_opportunity, domain["source_path"], domain["source_excerpt"], label)
        if not any(
            unit["source_path"] == domain["source_path"]
            and domain["source_excerpt"] in unit["source_excerpt"]
            for unit_id, unit in units_by_id.items()
            if unit_id in source_unit_ids
        ):
            raise ContractError(f"{label} ne rattache pas son extrait à une unité source.")
        _require_enum(domain["centrality"], CENTRALITIES_V2, f"{label}.centrality")
    return domains


def validate_domain_preparation_v2(provenance: Any, integrity: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Valide les métadonnées locales du segmenter et de l'extracteur v2."""

    provenance = _require_mapping(provenance, "domain_preparation")
    _require_exact_keys(provenance, _DOMAIN_PROVENANCE_V2_KEYS, "domain_preparation")
    for field in {"segmentation_version", "extractor_version", "extractor_model_identifier"}:
        _require_non_empty_string(provenance[field], f"domain_preparation.{field}")
    for field in _DOMAIN_PROVENANCE_V2_KEYS - {
        "segmentation_version",
        "extractor_version",
        "extractor_model_identifier",
    }:
        _require_sha256(provenance[field], f"domain_preparation.{field}")

    integrity = _require_mapping(integrity, "domain_integrity")
    _require_exact_keys(integrity, _DOMAIN_INTEGRITY_V2_KEYS, "domain_integrity")
    for field in _DOMAIN_INTEGRITY_V2_KEYS:
        _require_sha256(integrity[field], f"domain_integrity.{field}")
    return provenance, integrity


def _validate_condition_source_paths_v2(
    prepared_opportunity: dict[str, Any], value: Any, label: str
) -> list[str]:
    paths = _require_string_list(value, f"{label}.source_paths")
    for index, pointer in enumerate(paths):
        resolve_json_pointer(prepared_opportunity, pointer, f"{label}.source_paths[{index}]")
    return paths


def _validate_number_or_none_v2(value: Any, label: str, *, positive: bool = False) -> None:
    number = _require_number_or_none(value, label)
    if number is not None and positive and number <= 0:
        raise ContractError(f"{label} doit être strictement positif ou null.")


def _validate_deterministic_fact_v2(
    prepared_opportunity: dict[str, Any], name: str, value: Any, *, output: bool
) -> dict[str, Any]:
    label = f"deterministic_conditions.{name}"
    condition = _require_mapping(value, label)
    expected_keys = {"source_paths", "information_status", "source_values", "mechanical_assessment"}
    if output:
        expected_keys.add("business_comment")
    _require_exact_keys(condition, expected_keys, label)
    _validate_condition_source_paths_v2(prepared_opportunity, condition["source_paths"], label)
    _require_enum(condition["information_status"], {"known", "unknown"}, f"{label}.information_status")
    source_values = _require_mapping(condition["source_values"], f"{label}.source_values")

    if name == "salary":
        _require_exact_keys(source_values, {"monthly_gross_min_eur", "monthly_gross_max_eur", "threshold_eur"}, f"{label}.source_values")
        _validate_number_or_none_v2(source_values["monthly_gross_min_eur"], f"{label}.source_values.monthly_gross_min_eur")
        _validate_number_or_none_v2(source_values["monthly_gross_max_eur"], f"{label}.source_values.monthly_gross_max_eur")
        _validate_number_or_none_v2(source_values["threshold_eur"], f"{label}.source_values.threshold_eur", positive=True)
        _require_enum(condition["mechanical_assessment"], {"below_threshold", "partially_meets_threshold", "meets_threshold", "unknown"}, f"{label}.mechanical_assessment")
    elif name == "commute":
        _require_exact_keys(source_values, {"duration_minutes", "band"}, f"{label}.source_values")
        duration = source_values["duration_minutes"]
        if duration is not None:
            _require_integer(duration, f"{label}.source_values.duration_minutes", minimum=1)
        _require_enum(source_values["band"], {"UP_TO_35", "BETWEEN_35_60", "OVER_60", "UNKNOWN"}, f"{label}.source_values.band")
        _require_enum(condition["mechanical_assessment"], {"target_condition", "review_condition", "exclude_condition", "unknown"}, f"{label}.mechanical_assessment")
    elif name == "schedule":
        fields = {"works_shifted_hours", "works_at_night", "works_weekend", "works_saturday", "works_sunday"}
        _require_exact_keys(source_values, fields, f"{label}.source_values")
        for field in fields:
            _require_bool_or_none(source_values[field], f"{label}.source_values.{field}")
        _require_enum(condition["mechanical_assessment"], {"no_penalty", "penalized", "unknown"}, f"{label}.mechanical_assessment")
    elif name == "contract_type":
        _require_exact_keys(source_values, {"family"}, f"{label}.source_values")
        _require_enum(source_values["family"], {"cdi", "cdd", "interim", "other", "unknown"}, f"{label}.source_values.family")
        _require_enum(condition["mechanical_assessment"], {"accepted", "unknown"}, f"{label}.mechanical_assessment")
    elif name == "employer_size":
        _require_exact_keys(source_values, {"establishment_size_label"}, f"{label}.source_values")
        _require_non_empty_string_or_none(source_values["establishment_size_label"], f"{label}.source_values.establishment_size_label")
        _require_enum(condition["mechanical_assessment"], {"known", "unknown"}, f"{label}.mechanical_assessment")
    elif name == "team_size":
        _require_exact_keys(source_values, {"minimum", "maximum"}, f"{label}.source_values")
        minimum = source_values["minimum"]
        maximum = source_values["maximum"]
        if minimum is not None:
            _require_integer(minimum, f"{label}.source_values.minimum", minimum=1)
        if maximum is not None:
            _require_integer(maximum, f"{label}.source_values.maximum", minimum=1)
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ContractError(f"{label}.source_values.minimum ne peut dépasser maximum.")
        _require_enum(condition["mechanical_assessment"], {"known", "unknown"}, f"{label}.mechanical_assessment")
    elif name == "functional_support":
        _require_exact_keys(source_values, {"support_status", "support_types"}, f"{label}.source_values")
        _require_enum(source_values["support_status"], {"present", "absent", "unknown"}, f"{label}.source_values.support_status")
        types = _require_string_list(source_values["support_types"], f"{label}.source_values.support_types")
        if len(types) != len(set(types)) or any(value not in {"administrative", "technical", "operational", "other"} for value in types):
            raise ContractError(f"{label}.source_values.support_types est invalide.")
        _require_enum(condition["mechanical_assessment"], {"known", "unknown"}, f"{label}.mechanical_assessment")
    else:  # pragma: no cover - protected by _DETERMINISTIC_CONDITION_NAMES_V2
        raise ContractError(f"Condition déterministe inconnue : {name}")

    if output:
        _require_non_empty_string(condition["business_comment"], f"{label}.business_comment")
    return condition


def _validate_deterministic_conditions_v2(
    prepared_opportunity: dict[str, Any], value: Any, *, output: bool
) -> dict[str, Any]:
    conditions = _require_mapping(value, "deterministic_conditions")
    _require_exact_keys(conditions, _DETERMINISTIC_CONDITION_NAMES_V2, "deterministic_conditions")
    for name in sorted(_DETERMINISTIC_CONDITION_NAMES_V2):
        _validate_deterministic_fact_v2(prepared_opportunity, name, conditions[name], output=output)
    return conditions


def validate_prepared_opportunity_v2(
    prepared_opportunity: Any, domain_preparation: Any, domain_integrity: Any
) -> dict[str, Any]:
    """Valide une opportunité v2 gelée, sans lire de base ni de profil local."""

    prepared_opportunity = _require_mapping(prepared_opportunity, "prepared_opportunity")
    _require_exact_keys(prepared_opportunity, _PREPARED_OPPORTUNITY_V2_KEYS, "prepared_opportunity")
    _require_mapping(prepared_opportunity["offer"], "prepared_opportunity.offer")
    _validate_normalized_requirements_v2(prepared_opportunity, prepared_opportunity["normalized_requirements"])
    units_by_id = _validate_domain_text_units_v2(prepared_opportunity, prepared_opportunity["domain_text_units"])
    domains = _validate_domain_inputs_v2(prepared_opportunity, units_by_id, prepared_opportunity["domain_inputs"])
    _validate_deterministic_conditions_v2(prepared_opportunity, prepared_opportunity["deterministic_conditions"], output=False)
    _provenance, integrity = validate_domain_preparation_v2(domain_preparation, domain_integrity)
    if integrity["domain_inputs_payload_sha256"] != payload_sha256(domains):
        raise ContractError("Le hash de domain_inputs est invalide.")
    return prepared_opportunity


def compute_evaluation_payload_sha256(document: dict[str, Any]) -> str:
    """Hash v2 après retrait du seul champ d'auto-référence de sortie."""

    logical_copy = copy.deepcopy(_require_mapping(document, "ai_opportunity_evaluation"))
    integrity = _require_mapping(logical_copy.get("integrity"), "integrity")
    integrity.pop("evaluation_payload_sha256", None)
    return payload_sha256(logical_copy)


def add_evaluation_integrity_v2(document: dict[str, Any]) -> dict[str, Any]:
    """Ajoute l'auto-hash v2 sans valeur neutre temporaire."""

    integrity = _require_mapping(document.get("integrity"), "integrity")
    if "evaluation_payload_sha256" in integrity:
        raise ContractError("evaluation_payload_sha256 existe déjà avant sa construction.")
    integrity["evaluation_payload_sha256"] = compute_evaluation_payload_sha256(document)
    return document


def _validate_requirement_coverage_v2(
    prepared_opportunity: dict[str, Any], profile_snapshot: dict[str, Any], value: Any
) -> list[dict[str, Any]]:
    coverage = _require_list(value, "evaluation.requirement_coverage")
    requirements = {
        item["requirement_id"]: item for item in prepared_opportunity["normalized_requirements"]
    }
    if len(coverage) != len(requirements):
        raise ContractError("La couverture des exigences est incomplète ou supplémentaire.")
    seen_ids: set[str] = set()
    copied_fields = {"source_path", "kind", "label", "expectation", "centrality"}
    for index, raw_item in enumerate(coverage):
        label = f"evaluation.requirement_coverage[{index}]"
        item = _require_mapping(raw_item, label)
        _require_exact_keys(item, _REQUIREMENT_COVERAGE_V2_KEYS, label)
        requirement_id = _require_non_empty_string(item["requirement_id"], f"{label}.requirement_id")
        if requirement_id in seen_ids or requirement_id not in requirements:
            raise ContractError("La couverture des exigences contient un identifiant invalide ou dupliqué.")
        seen_ids.add(requirement_id)
        source = requirements[requirement_id]
        if any(item[field] != source[field] for field in copied_fields):
            raise ContractError(f"{label} modifie une exigence préparée.")
        _require_enum(item["assessment"], ASSESSMENTS_V2, f"{label}.assessment")
        for path_index, pointer in enumerate(_require_string_list(item["profile_evidence_paths"], f"{label}.profile_evidence_paths")):
            resolve_json_pointer(profile_snapshot, pointer, f"{label}.profile_evidence_paths[{path_index}]")
        _require_non_empty_string(item["reason"], f"{label}.reason")
    if seen_ids != set(requirements):
        raise ContractError("La couverture des exigences ne couvre pas toutes les exigences préparées.")
    return coverage


def _validate_domain_coverage_v2(
    prepared_opportunity: dict[str, Any], profile_snapshot: dict[str, Any], value: Any
) -> list[dict[str, Any]]:
    coverage = _require_list(value, "evaluation.domain_coverage")
    domains = {item["domain_id"]: item for item in prepared_opportunity["domain_inputs"]}
    if len(coverage) != len(domains):
        raise ContractError("La couverture des domaines est incomplète ou supplémentaire.")
    seen_ids: set[str] = set()
    copied_fields = {"domain", "source_unit_ids", "source_path", "source_excerpt", "centrality"}
    for index, raw_item in enumerate(coverage):
        label = f"evaluation.domain_coverage[{index}]"
        item = _require_mapping(raw_item, label)
        _require_exact_keys(item, _DOMAIN_COVERAGE_V2_KEYS, label)
        domain_id = _require_non_empty_string(item["domain_id"], f"{label}.domain_id")
        if domain_id in seen_ids or domain_id not in domains:
            raise ContractError("La couverture des domaines contient un identifiant invalide ou dupliqué.")
        seen_ids.add(domain_id)
        source = domains[domain_id]
        if any(item[field] != source[field] for field in copied_fields):
            raise ContractError(f"{label} modifie un domaine préparé.")
        _require_enum(item["assessment"], ASSESSMENTS_V2, f"{label}.assessment")
        for path_index, pointer in enumerate(_require_string_list(item["profile_evidence_paths"], f"{label}.profile_evidence_paths")):
            resolve_json_pointer(profile_snapshot, pointer, f"{label}.profile_evidence_paths[{path_index}]")
        _require_non_empty_string(item["reason"], f"{label}.reason")
    if seen_ids != set(domains):
        raise ContractError("La couverture des domaines ne couvre pas tous les domaines préparés.")
    return coverage


def _validate_missing_information_v2(prepared_opportunity: dict[str, Any], value: Any) -> None:
    items = _require_list(value, "evaluation.missing_information")
    expected_keys = {"subject", "source_paths", "reason", "classification_impact"}
    for index, raw_item in enumerate(items):
        label = f"evaluation.missing_information[{index}]"
        item = _require_mapping(raw_item, label)
        _require_exact_keys(item, expected_keys, label)
        _require_non_empty_string(item["subject"], f"{label}.subject")
        for path_index, pointer in enumerate(_require_string_list(item["source_paths"], f"{label}.source_paths")):
            resolve_json_pointer(prepared_opportunity, pointer, f"{label}.source_paths[{path_index}]")
        _require_non_empty_string(item["reason"], f"{label}.reason")
        _require_non_empty_string(item["classification_impact"], f"{label}.classification_impact")


def validate_ai_opportunity_evaluation_v2(
    document: Any,
    prepared_opportunity: Any,
    profile_snapshot: Any,
    domain_preparation: Any,
    domain_integrity: Any,
) -> dict[str, Any]:
    """Valide une sortie v2 contre les faits explicitement fournis par l'appelant."""

    prepared = validate_prepared_opportunity_v2(
        prepared_opportunity, domain_preparation, domain_integrity
    )
    profile = _require_mapping(profile_snapshot, "profile_snapshot")
    document = _require_mapping(document, "ai_opportunity_evaluation")
    _require_exact_keys(document, _EVALUATION_DOCUMENT_V2_KEYS, "ai_opportunity_evaluation")
    if _require_integer(document["schema_version"], "schema_version", minimum=1) != V2_SCHEMA_VERSION:
        raise ContractError("Version de sortie IA v2 invalide.")
    if document["artifact_type"] != V2_EVALUATION_ARTIFACT_TYPE:
        raise ContractError("artifact_type de sortie IA v2 invalide.")

    evaluation = _require_mapping(document["evaluation"], "evaluation")
    _require_exact_keys(evaluation, _EVALUATION_RESULT_V2_KEYS, "evaluation")
    requirement_coverage = _validate_requirement_coverage_v2(
        prepared, profile, evaluation["requirement_coverage"]
    )
    _validate_domain_coverage_v2(prepared, profile, evaluation["domain_coverage"])
    output_conditions = _validate_deterministic_conditions_v2(
        prepared, evaluation["deterministic_conditions"], output=True
    )
    for name in _DETERMINISTIC_CONDITION_NAMES_V2:
        copied_facts = dict(output_conditions[name])
        copied_facts.pop("business_comment")
        if canonical_json_bytes(copied_facts) != canonical_json_bytes(prepared["deterministic_conditions"][name]):
            raise ContractError(f"La sortie modifie les faits déterministes de {name}.")
    classification = _require_enum(evaluation["classification_code"], set(CLASSIFICATION_CODES), "evaluation.classification_code")
    _require_non_empty_string(evaluation["classification_justification"], "evaluation.classification_justification")
    _validate_missing_information_v2(prepared, evaluation["missing_information"])

    if classification == "credible" and any(
        item["expectation"] == "required" and item["assessment"] in {"gap", "missing"}
        for item in requirement_coverage
    ):
        raise ContractError("credible est interdit par une exigence required en gap ou missing.")

    integrity = _require_mapping(document["integrity"], "integrity")
    if "evaluation_payload_sha256" not in integrity:
        raise ContractError("integrity.evaluation_payload_sha256 est absent.")
    stored_hash = _require_sha256(
        integrity["evaluation_payload_sha256"], "integrity.evaluation_payload_sha256"
    )
    if stored_hash != compute_evaluation_payload_sha256(document):
        raise ContractError("Le hash canonique de sortie v2 est invalide.")
    return document
