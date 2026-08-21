"""Préparation déterministe v2 limitée aux fixtures entièrement synthétiques.

Ce module ne fournit volontairement ni CLI, ni accès fichier, ni connexion à
une base. Il construit uniquement les faits gelés qui précèdent l'extraction
des domaines et l'évaluation métier.
"""

from __future__ import annotations

import copy
from typing import Any

from ai_contract import (
    ContractError,
    compute_requirement_id,
    payload_sha256,
    resolve_json_pointer,
)


SYNTHETIC_FIXTURE_SCOPE = "synthetic_only"

_REQUIREMENT_GROUPS = (
    ("skills", "skill"),
    ("education", "education"),
    ("licences_and_authorizations", "licence_or_authorization"),
    ("certifications", "certification"),
    ("experiences", "experience"),
    ("responsibilities", "responsibility"),
    ("working_conditions", "working_condition"),
    ("other", "other"),
)

_SYNTHETIC_OFFER_KEYS = {
    "fixture_scope",
    "requirements",
    "salary",
    "travel",
    "schedule",
    "contract",
    "employer",
    "team",
    "functional_support",
}
_REQUIREMENT_ITEM_KEYS = {"label", "source_code", "expectation_source_code"}
_SCHEDULE_FIELDS = {
    "works_shifted_hours",
    "works_at_night",
    "works_weekend",
    "works_saturday",
    "works_sunday",
}
_SUPPORT_TYPES = {"administrative", "technical", "operational", "other"}


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} doit être un objet JSON.")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("absentes=" + ",".join(missing))
        if extra:
            details.append("inattendues=" + ",".join(extra))
        raise ContractError(f"{label} possède des clés invalides ({'; '.join(details)}).")


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} doit être une chaîne non vide.")
    return value


def _string_or_none(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, label)


def _number_or_none(value: Any, label: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} doit être un nombre ou null.")
    if value < 0:
        raise ContractError(f"{label} ne peut pas être négatif.")
    return value


def _positive_integer_or_none(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{label} doit être un entier positif ou null.")
    return value


def _bool_or_none(value: Any, label: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ContractError(f"{label} doit être un booléen ou null.")
    return value


def _expectation_from_code(code: str | None) -> str:
    if code == "E":
        return "required"
    if code == "S":
        return "desired"
    return "unknown"


def _validate_synthetic_offer_shape(offer: Any) -> dict[str, Any]:
    offer = _mapping(offer, "synthetic_offer")
    _exact_keys(offer, _SYNTHETIC_OFFER_KEYS, "synthetic_offer")
    if offer["fixture_scope"] != SYNTHETIC_FIXTURE_SCOPE:
        raise ContractError("La préparation v2 de cette étape accepte uniquement une fixture synthétique.")

    requirements = _mapping(offer["requirements"], "synthetic_offer.requirements")
    expected_groups = {group for group, _kind in _REQUIREMENT_GROUPS}
    _exact_keys(requirements, expected_groups, "synthetic_offer.requirements")
    for group, _kind in _REQUIREMENT_GROUPS:
        items = requirements[group]
        if not isinstance(items, list):
            raise ContractError(f"synthetic_offer.requirements.{group} doit être un tableau.")
        for index, raw_item in enumerate(items):
            label = f"synthetic_offer.requirements.{group}[{index}]"
            item = _mapping(raw_item, label)
            _exact_keys(item, _REQUIREMENT_ITEM_KEYS, label)
            _non_empty_string(item["label"], f"{label}.label")
            _string_or_none(item["source_code"], f"{label}.source_code")
            _string_or_none(
                item["expectation_source_code"], f"{label}.expectation_source_code"
            )
    return offer


def normalize_requirements_v2(synthetic_offer: Any) -> list[dict[str, Any]]:
    """Normalise toutes les exigences synthétiques dans un ordre stable."""

    offer = _validate_synthetic_offer_shape(synthetic_offer)
    normalized: list[dict[str, Any]] = []
    for group, kind in _REQUIREMENT_GROUPS:
        for index, item in enumerate(offer["requirements"][group]):
            source_path = f"/offer/requirements/{group}/{index}"
            requirement = {
                "requirement_id": compute_requirement_id(
                    source_path,
                    kind,
                    item["source_code"],
                    item["expectation_source_code"],
                    item["label"],
                ),
                "source_path": source_path,
                "kind": kind,
                "label": item["label"],
                "source_code": item["source_code"],
                "expectation_source_code": item["expectation_source_code"],
                "expectation": _expectation_from_code(item["expectation_source_code"]),
                "centrality": "unknown",
            }
            normalized.append(requirement)

    prepared_root = {"offer": offer}
    for index, requirement in enumerate(normalized):
        resolve_json_pointer(
            prepared_root,
            requirement["source_path"],
            f"normalized_requirements[{index}].source_path",
        )
    return normalized


def _condition(
    source_path: str,
    information_status: str,
    source_values: dict[str, Any],
    mechanical_assessment: str,
) -> dict[str, Any]:
    return {
        "source_paths": [source_path],
        "information_status": information_status,
        "source_values": source_values,
        "mechanical_assessment": mechanical_assessment,
    }


def build_deterministic_conditions_v2(
    synthetic_offer: Any, *, salary_threshold_eur: int | float = 2500
) -> dict[str, dict[str, Any]]:
    """Construit les sept conditions fermées, sans commentaire métier."""

    offer = _validate_synthetic_offer_shape(synthetic_offer)
    threshold = _number_or_none(salary_threshold_eur, "salary_threshold_eur")
    if threshold is None or threshold <= 0:
        raise ContractError("salary_threshold_eur doit être strictement positif.")

    salary = _mapping(offer["salary"], "synthetic_offer.salary")
    _exact_keys(salary, {"monthly_gross_min_eur", "monthly_gross_max_eur"}, "synthetic_offer.salary")
    salary_min = _number_or_none(salary["monthly_gross_min_eur"], "synthetic_offer.salary.monthly_gross_min_eur")
    salary_max = _number_or_none(salary["monthly_gross_max_eur"], "synthetic_offer.salary.monthly_gross_max_eur")
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        raise ContractError("Le salaire minimal synthétique ne peut dépasser le maximum.")
    if salary_min is None and salary_max is None:
        salary_status, salary_assessment = "unknown", "unknown"
    elif salary_max is not None and salary_max < threshold:
        salary_status, salary_assessment = "known", "below_threshold"
    elif salary_min is not None and salary_min >= threshold:
        salary_status, salary_assessment = "known", "meets_threshold"
    else:
        salary_status, salary_assessment = "known", "partially_meets_threshold"

    travel = _mapping(offer["travel"], "synthetic_offer.travel")
    _exact_keys(travel, {"duration_minutes", "band"}, "synthetic_offer.travel")
    duration = _positive_integer_or_none(travel["duration_minutes"], "synthetic_offer.travel.duration_minutes")
    band = travel["band"]
    commute_assessments = {
        "UP_TO_35": "target_condition",
        "BETWEEN_35_60": "review_condition",
        "OVER_60": "exclude_condition",
        "UNKNOWN": "unknown",
    }
    if band not in commute_assessments:
        raise ContractError("synthetic_offer.travel.band est invalide.")
    if (band == "UNKNOWN") != (duration is None):
        raise ContractError("La durée et la bande de trajet synthétiques sont incohérentes.")

    schedule = _mapping(offer["schedule"], "synthetic_offer.schedule")
    _exact_keys(schedule, _SCHEDULE_FIELDS, "synthetic_offer.schedule")
    schedule_values = {
        field: _bool_or_none(schedule[field], f"synthetic_offer.schedule.{field}")
        for field in sorted(_SCHEDULE_FIELDS)
    }
    known_schedule = any(value is not None for value in schedule_values.values())
    if not known_schedule:
        schedule_assessment = "unknown"
    elif schedule_values["works_shifted_hours"] is True or schedule_values["works_at_night"] is True:
        schedule_assessment = "penalized"
    else:
        schedule_assessment = "no_penalty"

    contract = _mapping(offer["contract"], "synthetic_offer.contract")
    _exact_keys(contract, {"family"}, "synthetic_offer.contract")
    family = contract["family"]
    if family not in {"cdi", "cdd", "interim", "other", "unknown"}:
        raise ContractError("synthetic_offer.contract.family est invalide.")

    employer = _mapping(offer["employer"], "synthetic_offer.employer")
    _exact_keys(employer, {"establishment_size_label"}, "synthetic_offer.employer")
    establishment_size = _string_or_none(
        employer["establishment_size_label"],
        "synthetic_offer.employer.establishment_size_label",
    )

    team = _mapping(offer["team"], "synthetic_offer.team")
    _exact_keys(team, {"minimum", "maximum"}, "synthetic_offer.team")
    team_minimum = _positive_integer_or_none(team["minimum"], "synthetic_offer.team.minimum")
    team_maximum = _positive_integer_or_none(team["maximum"], "synthetic_offer.team.maximum")
    if team_minimum is not None and team_maximum is not None and team_minimum > team_maximum:
        raise ContractError("La taille minimale d'équipe ne peut dépasser le maximum.")

    support = _mapping(offer["functional_support"], "synthetic_offer.functional_support")
    _exact_keys(support, {"support_status", "support_types"}, "synthetic_offer.functional_support")
    support_status = support["support_status"]
    if support_status not in {"present", "absent", "unknown"}:
        raise ContractError("synthetic_offer.functional_support.support_status est invalide.")
    support_types = support["support_types"]
    if not isinstance(support_types, list) or any(
        not isinstance(value, str) or value not in _SUPPORT_TYPES for value in support_types
    ):
        raise ContractError("synthetic_offer.functional_support.support_types est invalide.")
    if len(support_types) != len(set(support_types)):
        raise ContractError("Les types de soutien synthétiques ne peuvent être dupliqués.")
    if support_status != "present" and support_types:
        raise ContractError("Des types de soutien exigent un support_status à present.")

    conditions = {
        "salary": _condition(
            "/offer/salary",
            salary_status,
            {
                "monthly_gross_min_eur": salary_min,
                "monthly_gross_max_eur": salary_max,
                "threshold_eur": threshold,
            },
            salary_assessment,
        ),
        "commute": _condition(
            "/offer/travel",
            "unknown" if band == "UNKNOWN" else "known",
            {"duration_minutes": duration, "band": band},
            commute_assessments[band],
        ),
        "schedule": _condition(
            "/offer/schedule",
            "known" if known_schedule else "unknown",
            schedule_values,
            schedule_assessment,
        ),
        "contract_type": _condition(
            "/offer/contract",
            "unknown" if family == "unknown" else "known",
            {"family": family},
            "accepted" if family in {"cdi", "cdd", "interim"} else "unknown",
        ),
        "employer_size": _condition(
            "/offer/employer",
            "known" if establishment_size is not None else "unknown",
            {"establishment_size_label": establishment_size},
            "known" if establishment_size is not None else "unknown",
        ),
        "team_size": _condition(
            "/offer/team",
            "known" if team_minimum is not None or team_maximum is not None else "unknown",
            {"minimum": team_minimum, "maximum": team_maximum},
            "known" if team_minimum is not None or team_maximum is not None else "unknown",
        ),
        "functional_support": _condition(
            "/offer/functional_support",
            "unknown" if support_status == "unknown" else "known",
            {"support_status": support_status, "support_types": list(support_types)},
            "unknown" if support_status == "unknown" else "known",
        ),
    }
    prepared_root = {"offer": offer}
    for name, condition in conditions.items():
        for pointer in condition["source_paths"]:
            resolve_json_pointer(prepared_root, pointer, f"deterministic_conditions.{name}.source_paths")
    return conditions


def build_initial_requirement_coverage_v2(
    normalized_requirements: Any,
) -> list[dict[str, Any]]:
    """Crée la couverture exhaustive neutre avant toute lecture de profil."""

    if not isinstance(normalized_requirements, list):
        raise ContractError("normalized_requirements doit être un tableau.")
    coverage: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    copied_fields = ("source_path", "kind", "label", "expectation", "centrality")
    for index, raw_requirement in enumerate(normalized_requirements):
        requirement = _mapping(raw_requirement, f"normalized_requirements[{index}]")
        requirement_id = _non_empty_string(
            requirement.get("requirement_id"), f"normalized_requirements[{index}].requirement_id"
        )
        if requirement_id in seen_ids:
            raise ContractError("normalized_requirements contient un identifiant dupliqué.")
        seen_ids.add(requirement_id)
        try:
            copied = {field: copy.deepcopy(requirement[field]) for field in copied_fields}
        except KeyError as error:
            raise ContractError(
                f"normalized_requirements[{index}] ne contient pas {error.args[0]}."
            ) from error
        coverage.append(
            {
                "requirement_id": requirement_id,
                **copied,
                "assessment": "missing",
                "profile_evidence_paths": [],
                "reason": "Aucun profil n'est utilisé pendant la préparation déterministe.",
            }
        )
    return coverage


def deterministic_conditions_sha256_v2(conditions: Any) -> str:
    """Calcule l'empreinte canonique des faits déterministes préparés."""

    return payload_sha256(conditions)


def verify_deterministic_conditions_sha256_v2(conditions: Any, expected_sha256: Any) -> None:
    """Refuse un ensemble de faits modifié après sa préparation."""

    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ContractError("Le hash attendu des conditions déterministes est invalide.")
    if deterministic_conditions_sha256_v2(conditions) != expected_sha256:
        raise ContractError("Les faits déterministes ont été modifiés après leur préparation.")


def prepare_synthetic_opportunity_v2(
    synthetic_offer: Any, *, salary_threshold_eur: int | float = 2500
) -> dict[str, Any]:
    """Prépare une fixture v2 sans profil, extraction de domaine ou I/O."""

    offer = copy.deepcopy(_validate_synthetic_offer_shape(synthetic_offer))
    normalized = normalize_requirements_v2(offer)
    conditions = build_deterministic_conditions_v2(
        offer, salary_threshold_eur=salary_threshold_eur
    )
    prepared = {
        "offer": offer,
        "normalized_requirements": normalized,
        "domain_text_units": [],
        "domain_inputs": [],
        "deterministic_conditions": conditions,
    }
    return {
        "prepared_opportunity": prepared,
        "initial_requirement_coverage": build_initial_requirement_coverage_v2(normalized),
        "deterministic_conditions_sha256": deterministic_conditions_sha256_v2(conditions),
    }
