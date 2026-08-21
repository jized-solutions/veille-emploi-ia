from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from ai_contract import (  # noqa: E402
    ContractError,
    V2_EVALUATION_ARTIFACT_TYPE,
    V2_SCHEMA_VERSION,
    add_evaluation_integrity_v2,
    compute_evaluation_payload_sha256,
    compute_requirement_id,
    payload_sha256,
    resolve_json_pointer,
    validate_ai_comparative_input,
    validate_ai_opportunity_evaluation_v2,
    validate_prepared_opportunity_v2,
)
from test_ai_input_security import build_fictitious_artifact  # noqa: E402


def build_synthetic_prepared_opportunity() -> tuple[dict, dict, dict, dict]:
    offer = {
        "description_cleaned": "Appliquer une règle synthétique au parc fictif.",
        "requirements": {
            "skills": [
                {
                    "code": "SYN-PLAN-01",
                    "libelle": "Planifier des interventions fictives",
                    "exigence": "E",
                }
            ],
            "licences_and_authorizations": [
                {
                    "libelle": "Autorisation fictive de conduite",
                    "exigence": "S",
                }
            ],
        },
        "salary": {"monthly_gross_min": 2400, "monthly_gross_max": 2800},
        "travel": {"duration_minutes": 42, "band": "BETWEEN_35_60"},
        "schedule": {
            "works_shifted_hours": False,
            "works_at_night": None,
            "works_weekend": None,
            "works_saturday": None,
            "works_sunday": None,
        },
        "contract": {"family": "cdd"},
        "employer": {"establishment_size": "50 à 99 salariés"},
    }
    skill_id = compute_requirement_id(
        "/offer/requirements/skills/0",
        "skill",
        "SYN-PLAN-01",
        "E",
        "Planifier des interventions fictives",
    )
    licence_id = compute_requirement_id(
        "/offer/requirements/licences_and_authorizations/0",
        "licence_or_authorization",
        None,
        "S",
        "Autorisation fictive de conduite",
    )
    prepared = {
        "offer": offer,
        "normalized_requirements": [
            {
                "requirement_id": skill_id,
                "source_path": "/offer/requirements/skills/0",
                "kind": "skill",
                "label": "Planifier des interventions fictives",
                "source_code": "SYN-PLAN-01",
                "expectation_source_code": "E",
                "expectation": "required",
                "centrality": "core",
            },
            {
                "requirement_id": licence_id,
                "source_path": "/offer/requirements/licences_and_authorizations/0",
                "kind": "licence_or_authorization",
                "label": "Autorisation fictive de conduite",
                "source_code": None,
                "expectation_source_code": "S",
                "expectation": "desired",
                "centrality": "supporting",
            },
        ],
        "domain_text_units": [
            {
                "unit_id": "segment:synthetic:0",
                "source_path": "/offer/description_cleaned",
                "source_excerpt": "Appliquer une règle synthétique au parc fictif.",
            }
        ],
        "domain_inputs": [
            {
                "domain_id": "domain:synthetic-rule",
                "domain": "synthetic_rule",
                "source_unit_ids": ["segment:synthetic:0"],
                "source_path": "/offer/description_cleaned",
                "source_excerpt": "Appliquer une règle synthétique au parc fictif.",
                "centrality": "core",
            }
        ],
        "deterministic_conditions": {
            "salary": {
                "source_paths": [
                    "/offer/salary/monthly_gross_min",
                    "/offer/salary/monthly_gross_max",
                ],
                "information_status": "known",
                "source_values": {
                    "monthly_gross_min_eur": 2400,
                    "monthly_gross_max_eur": 2800,
                    "threshold_eur": 2500,
                },
                "mechanical_assessment": "partially_meets_threshold",
            },
            "commute": {
                "source_paths": ["/offer/travel/duration_minutes", "/offer/travel/band"],
                "information_status": "known",
                "source_values": {"duration_minutes": 42, "band": "BETWEEN_35_60"},
                "mechanical_assessment": "review_condition",
            },
            "schedule": {
                "source_paths": [
                    "/offer/schedule/works_shifted_hours",
                    "/offer/schedule/works_at_night",
                    "/offer/schedule/works_weekend",
                    "/offer/schedule/works_saturday",
                    "/offer/schedule/works_sunday",
                ],
                "information_status": "known",
                "source_values": {
                    "works_shifted_hours": False,
                    "works_at_night": None,
                    "works_weekend": None,
                    "works_saturday": None,
                    "works_sunday": None,
                },
                "mechanical_assessment": "no_penalty",
            },
            "contract_type": {
                "source_paths": ["/offer/contract/family"],
                "information_status": "known",
                "source_values": {"family": "cdd"},
                "mechanical_assessment": "accepted",
            },
            "employer_size": {
                "source_paths": ["/offer/employer/establishment_size"],
                "information_status": "known",
                "source_values": {"establishment_size_label": "50 à 99 salariés"},
                "mechanical_assessment": "known",
            },
            "team_size": {
                "source_paths": [],
                "information_status": "unknown",
                "source_values": {"minimum": None, "maximum": None},
                "mechanical_assessment": "unknown",
            },
            "functional_support": {
                "source_paths": [],
                "information_status": "unknown",
                "source_values": {"support_status": "unknown", "support_types": []},
                "mechanical_assessment": "unknown",
            },
        },
    }
    domain_preparation = {
        "segmentation_version": "synthetic-segmenter-v2",
        "segmentation_rules_sha256": "1" * 64,
        "segmentation_schema_sha256": "2" * 64,
        "extractor_version": "synthetic-extractor-v2",
        "extractor_instruction_sha256": "3" * 64,
        "extractor_schema_sha256": "4" * 64,
        "extractor_model_identifier": "synthetic-local-extractor",
        "extractor_model_sha256": "5" * 64,
    }
    domain_integrity = {
        "domain_extraction_payload_sha256": "6" * 64,
        "domain_inputs_payload_sha256": payload_sha256(prepared["domain_inputs"]),
    }
    profile = {"skills": [{"label": "Planification fictive"}]}
    return prepared, domain_preparation, domain_integrity, profile


def build_synthetic_output(
    prepared: dict, profile: dict, *, classification: str = "audacious"
) -> dict:
    conditions = copy.deepcopy(prepared["deterministic_conditions"])
    for name, condition in conditions.items():
        condition["business_comment"] = f"Commentaire synthétique pour {name}."
    requirements = prepared["normalized_requirements"]
    domains = prepared["domain_inputs"]
    output = {
        "schema_version": V2_SCHEMA_VERSION,
        "artifact_type": V2_EVALUATION_ARTIFACT_TYPE,
        "evaluation": {
            "requirement_coverage": [
                {
                    "requirement_id": requirements[0]["requirement_id"],
                    "source_path": requirements[0]["source_path"],
                    "kind": requirements[0]["kind"],
                    "label": requirements[0]["label"],
                    "expectation": requirements[0]["expectation"],
                    "centrality": requirements[0]["centrality"],
                    "assessment": "transferable",
                    "profile_evidence_paths": ["/skills/0"],
                    "reason": "Compétence synthétique exercée dans un autre contexte.",
                },
                {
                    "requirement_id": requirements[1]["requirement_id"],
                    "source_path": requirements[1]["source_path"],
                    "kind": requirements[1]["kind"],
                    "label": requirements[1]["label"],
                    "expectation": requirements[1]["expectation"],
                    "centrality": requirements[1]["centrality"],
                    "assessment": "missing",
                    "profile_evidence_paths": [],
                    "reason": "Information synthétique non fournie.",
                },
            ],
            "domain_coverage": [
                {
                    "domain_id": domains[0]["domain_id"],
                    "domain": domains[0]["domain"],
                    "source_unit_ids": domains[0]["source_unit_ids"],
                    "source_path": domains[0]["source_path"],
                    "source_excerpt": domains[0]["source_excerpt"],
                    "centrality": domains[0]["centrality"],
                    "assessment": "gap",
                    "profile_evidence_paths": [],
                    "reason": "Domaine synthétique non établi.",
                }
            ],
            "deterministic_conditions": conditions,
            "classification_code": classification,
            "classification_justification": "Conclusion synthétique strictement consultative.",
            "missing_information": [],
        },
        "integrity": {},
    }
    add_evaluation_integrity_v2(output)
    return output


class V1RegressionTests(unittest.TestCase):
    def test_v1_success_is_unchanged(self):
        artifact = build_fictitious_artifact()
        self.assertEqual(validate_ai_comparative_input(artifact), artifact)


class V2ContractTests(unittest.TestCase):
    def setUp(self):
        self.prepared, self.provenance, self.domain_integrity, self.profile = (
            build_synthetic_prepared_opportunity()
        )

    def validate_output(self, output: dict) -> dict:
        return validate_ai_opportunity_evaluation_v2(
            output,
            self.prepared,
            self.profile,
            self.provenance,
            self.domain_integrity,
        )

    def test_complete_v2_success(self):
        output = build_synthetic_output(self.prepared, self.profile)
        self.assertEqual(self.validate_output(output), output)

    def test_altered_requirement_id_is_rejected(self):
        prepared = copy.deepcopy(self.prepared)
        prepared["normalized_requirements"][0]["requirement_id"] = "req:" + "0" * 64
        with self.assertRaises(ContractError):
            validate_prepared_opportunity_v2(prepared, self.provenance, self.domain_integrity)

    def test_certification_requirement_kind_is_accepted(self):
        prepared = copy.deepcopy(self.prepared)
        certification = {
            "libelle": "Certification fictive de conformité",
            "code": "SYN-CERT-01",
            "exigence": "S",
        }
        prepared["offer"]["requirements"]["certifications"] = [certification]
        source_path = "/offer/requirements/certifications/0"
        prepared["normalized_requirements"].append(
            {
                "requirement_id": compute_requirement_id(
                    source_path,
                    "certification",
                    "SYN-CERT-01",
                    "S",
                    "Certification fictive de conformité",
                ),
                "source_path": source_path,
                "kind": "certification",
                "label": "Certification fictive de conformité",
                "source_code": "SYN-CERT-01",
                "expectation_source_code": "S",
                "expectation": "desired",
                "centrality": "supporting",
            }
        )
        self.assertIs(
            validate_prepared_opportunity_v2(
                prepared, self.provenance, self.domain_integrity
            ),
            prepared,
        )

    def test_unknown_requirement_kind_is_rejected(self):
        prepared = copy.deepcopy(self.prepared)
        prepared["normalized_requirements"][0]["kind"] = "unknown_nature"
        with self.assertRaises(ContractError):
            validate_prepared_opportunity_v2(
                prepared, self.provenance, self.domain_integrity
            )

    def test_invalid_offer_pointer_is_rejected(self):
        prepared = copy.deepcopy(self.prepared)
        prepared["normalized_requirements"][0]["source_path"] = "/offer/missing"
        with self.assertRaises(ContractError):
            validate_prepared_opportunity_v2(prepared, self.provenance, self.domain_integrity)

    def test_invalid_profile_pointer_is_rejected(self):
        output = build_synthetic_output(self.prepared, self.profile)
        output["evaluation"]["requirement_coverage"][0]["profile_evidence_paths"] = [
            "/skills/99"
        ]
        output["integrity"] = {}
        add_evaluation_integrity_v2(output)
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_missing_requirement_coverage_is_rejected(self):
        output = build_synthetic_output(self.prepared, self.profile)
        output["evaluation"]["requirement_coverage"].pop()
        output["integrity"] = {}
        add_evaluation_integrity_v2(output)
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_duplicate_requirement_coverage_is_rejected(self):
        output = build_synthetic_output(self.prepared, self.profile)
        coverage = output["evaluation"]["requirement_coverage"]
        coverage[1] = copy.deepcopy(coverage[0])
        output["integrity"] = {}
        add_evaluation_integrity_v2(output)
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_missing_domain_coverage_is_rejected(self):
        output = build_synthetic_output(self.prepared, self.profile)
        output["evaluation"]["domain_coverage"] = []
        output["integrity"] = {}
        add_evaluation_integrity_v2(output)
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_deterministic_fact_modification_is_rejected(self):
        output = build_synthetic_output(self.prepared, self.profile)
        output["evaluation"]["deterministic_conditions"]["salary"]["source_values"][
            "monthly_gross_min_eur"
        ] = 9999
        output["integrity"] = {}
        add_evaluation_integrity_v2(output)
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_deterministic_condition_type_is_rejected(self):
        prepared = copy.deepcopy(self.prepared)
        prepared["deterministic_conditions"]["commute"]["source_values"][
            "duration_minutes"
        ] = True
        with self.assertRaises(ContractError):
            validate_prepared_opportunity_v2(prepared, self.provenance, self.domain_integrity)

    def test_credible_is_rejected_for_required_gap(self):
        output = build_synthetic_output(self.prepared, self.profile, classification="credible")
        output["evaluation"]["requirement_coverage"][0]["assessment"] = "gap"
        output["integrity"] = {}
        add_evaluation_integrity_v2(output)
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_credible_is_rejected_for_required_missing(self):
        output = build_synthetic_output(self.prepared, self.profile, classification="credible")
        output["evaluation"]["requirement_coverage"][0]["assessment"] = "missing"
        output["integrity"] = {}
        add_evaluation_integrity_v2(output)
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_altered_evaluation_auto_hash_is_rejected(self):
        output = build_synthetic_output(self.prepared, self.profile)
        output["integrity"]["evaluation_payload_sha256"] = "0" * 64
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_hash_calculated_without_removing_self_field_is_rejected(self):
        output = build_synthetic_output(self.prepared, self.profile)
        output["integrity"]["evaluation_payload_sha256"] = payload_sha256(output)
        with self.assertRaises(ContractError):
            self.validate_output(output)

    def test_json_pointer_rfc_6901_escaping(self):
        document = {"a/b": {"tilde~key": ["synthetic"]}}
        self.assertEqual(resolve_json_pointer(document, "/a~1b/tilde~0key/0"), "synthetic")


if __name__ == "__main__":
    unittest.main()
