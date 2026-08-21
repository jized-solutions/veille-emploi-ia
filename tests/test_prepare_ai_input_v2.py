import copy
import sys
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from ai_contract import (
    ContractError,
    compute_requirement_id,
    payload_sha256,
    resolve_json_pointer,
    validate_prepared_opportunity_v2,
)
from prepare_ai_input_v2 import (
    build_deterministic_conditions_v2,
    build_initial_requirement_coverage_v2,
    normalize_requirements_v2,
    prepare_synthetic_opportunity_v2,
    verify_deterministic_conditions_sha256_v2,
)


def synthetic_offer():
    return {
        "fixture_scope": "synthetic_only",
        "requirements": {
            "skills": [
                {
                    "label": "Organiser une activité fictive",
                    "source_code": "SYN-SKILL",
                    "expectation_source_code": "E",
                }
            ],
            "education": [
                {
                    "label": "Diplôme synthétique de niveau 5",
                    "source_code": "SYN-EDU",
                    "expectation_source_code": "S",
                }
            ],
            "licences_and_authorizations": [
                {
                    "label": "Permis fictif catégorie Z",
                    "source_code": "SYN-LICENCE",
                    "expectation_source_code": "E",
                }
            ],
            "certifications": [
                {
                    "label": "Certification synthétique qualité",
                    "source_code": "SYN-CERT",
                    "expectation_source_code": "S",
                }
            ],
            "experiences": [
                {
                    "label": "Expérience fictive en coordination",
                    "source_code": None,
                    "expectation_source_code": "X",
                }
            ],
            "responsibilities": [],
            "working_conditions": [],
            "other": [
                {
                    "label": "Information fictive non codée",
                    "source_code": None,
                    "expectation_source_code": None,
                }
            ],
        },
        "salary": {
            "monthly_gross_min_eur": 2400,
            "monthly_gross_max_eur": 2700,
        },
        "travel": {"duration_minutes": 48, "band": "BETWEEN_35_60"},
        "schedule": {
            "works_shifted_hours": False,
            "works_at_night": False,
            "works_weekend": True,
            "works_saturday": True,
            "works_sunday": None,
        },
        "contract": {"family": "cdi"},
        "employer": {"establishment_size_label": "structure synthétique moyenne"},
        "team": {"minimum": 4, "maximum": 7},
        "functional_support": {
            "support_status": "present",
            "support_types": ["administrative", "technical"],
        },
    }


class PrepareAiInputV2Tests(unittest.TestCase):
    def test_requirement_ids_and_pointers_are_stable(self):
        first = normalize_requirements_v2(synthetic_offer())
        second = normalize_requirements_v2(copy.deepcopy(synthetic_offer()))
        self.assertEqual(first, second)
        prepared = {"offer": synthetic_offer()}
        for requirement in first:
            self.assertEqual(
                requirement["requirement_id"],
                compute_requirement_id(
                    requirement["source_path"],
                    requirement["kind"],
                    requirement["source_code"],
                    requirement["expectation_source_code"],
                    requirement["label"],
                ),
            )
            self.assertIsInstance(resolve_json_pointer(prepared, requirement["source_path"]), dict)

    def test_permit_diploma_certification_and_skill_remain_distinct(self):
        requirements = normalize_requirements_v2(synthetic_offer())
        by_group = {item["source_path"].split("/")[3]: item for item in requirements}
        self.assertEqual(by_group["skills"]["kind"], "skill")
        self.assertEqual(by_group["education"]["kind"], "education")
        self.assertEqual(
            by_group["licences_and_authorizations"]["kind"], "licence_or_authorization"
        )
        self.assertEqual(by_group["certifications"]["kind"], "certification")
        self.assertIn("/certifications/", by_group["certifications"]["source_path"])
        self.assertEqual(by_group["other"]["kind"], "other")
        self.assertEqual(len({item["requirement_id"] for item in by_group.values()}), len(by_group))

    def test_certification_is_accepted_by_v2_foundation(self):
        bundle = prepare_synthetic_opportunity_v2(synthetic_offer())
        certification = next(
            item
            for item in bundle["prepared_opportunity"]["normalized_requirements"]
            if item["kind"] == "certification"
        )
        self.assertEqual(certification["source_path"], "/offer/requirements/certifications/0")
        self.assertTrue(certification["requirement_id"].startswith("req:"))

        provenance = {
            "segmentation_version": "synthetic-test-v1",
            "segmentation_rules_sha256": "1" * 64,
            "segmentation_schema_sha256": "2" * 64,
            "extractor_version": "not-run-synthetic-test-v1",
            "extractor_instruction_sha256": "3" * 64,
            "extractor_schema_sha256": "4" * 64,
            "extractor_model_identifier": "not-run",
            "extractor_model_sha256": "5" * 64,
        }
        integrity = {
            "domain_extraction_payload_sha256": "6" * 64,
            "domain_inputs_payload_sha256": payload_sha256([]),
        }
        self.assertIs(
            validate_prepared_opportunity_v2(
                bundle["prepared_opportunity"], provenance, integrity
            ),
            bundle["prepared_opportunity"],
        )

    def test_expectation_codes_use_conservative_mapping(self):
        requirements = normalize_requirements_v2(synthetic_offer())
        expectations = {
            item["expectation_source_code"]: item["expectation"] for item in requirements
        }
        self.assertEqual(expectations["E"], "required")
        self.assertEqual(expectations["S"], "desired")
        self.assertEqual(expectations["X"], "unknown")
        self.assertEqual(expectations[None], "unknown")
        self.assertTrue(all(item["centrality"] == "unknown" for item in requirements))

    def test_seven_typed_conditions_are_built_without_business_comment(self):
        conditions = build_deterministic_conditions_v2(synthetic_offer())
        self.assertEqual(
            set(conditions),
            {
                "salary",
                "commute",
                "schedule",
                "contract_type",
                "employer_size",
                "team_size",
                "functional_support",
            },
        )
        self.assertEqual(conditions["salary"]["mechanical_assessment"], "partially_meets_threshold")
        self.assertEqual(conditions["commute"]["mechanical_assessment"], "review_condition")
        self.assertEqual(conditions["schedule"]["mechanical_assessment"], "no_penalty")
        self.assertEqual(conditions["contract_type"]["mechanical_assessment"], "accepted")
        for condition in conditions.values():
            self.assertEqual(
                set(condition),
                {"source_paths", "information_status", "source_values", "mechanical_assessment"},
            )
            self.assertNotIn("business_comment", condition)

    def test_initial_coverage_is_exhaustive_unique_and_profile_free(self):
        requirements = normalize_requirements_v2(synthetic_offer())
        coverage = build_initial_requirement_coverage_v2(requirements)
        self.assertEqual(len(coverage), len(requirements))
        self.assertEqual(
            {item["requirement_id"] for item in coverage},
            {item["requirement_id"] for item in requirements},
        )
        self.assertTrue(all(item["assessment"] == "missing" for item in coverage))
        self.assertTrue(all(item["profile_evidence_paths"] == [] for item in coverage))
        self.assertTrue(all("business_comment" not in item for item in coverage))

    def test_prepared_bundle_has_no_domains_before_extractor(self):
        bundle = prepare_synthetic_opportunity_v2(synthetic_offer())
        prepared = bundle["prepared_opportunity"]
        self.assertEqual(prepared["domain_text_units"], [])
        self.assertEqual(prepared["domain_inputs"], [])

    def test_prepared_bundle_is_accepted_by_v2_foundation(self):
        prepared = prepare_synthetic_opportunity_v2(synthetic_offer())["prepared_opportunity"]
        provenance = {
            "segmentation_version": "synthetic-test-v1",
            "segmentation_rules_sha256": "1" * 64,
            "segmentation_schema_sha256": "2" * 64,
            "extractor_version": "not-run-synthetic-test-v1",
            "extractor_instruction_sha256": "3" * 64,
            "extractor_schema_sha256": "4" * 64,
            "extractor_model_identifier": "not-run",
            "extractor_model_sha256": "5" * 64,
        }
        integrity = {
            "domain_extraction_payload_sha256": "6" * 64,
            "domain_inputs_payload_sha256": payload_sha256([]),
        }
        self.assertIs(
            validate_prepared_opportunity_v2(prepared, provenance, integrity), prepared
        )

    def test_invalid_condition_key_and_value_are_rejected(self):
        offer = synthetic_offer()
        offer["salary"]["unexpected"] = 1
        with self.assertRaises(ContractError):
            build_deterministic_conditions_v2(offer)

        offer = synthetic_offer()
        offer["travel"]["band"] = "MAYBE"
        with self.assertRaises(ContractError):
            build_deterministic_conditions_v2(offer)

        offer = synthetic_offer()
        offer["schedule"]["works_at_night"] = 1
        with self.assertRaises(ContractError):
            build_deterministic_conditions_v2(offer)

    def test_invalid_requirement_key_is_rejected(self):
        offer = synthetic_offer()
        offer["requirements"]["skills"][0]["unexpected"] = "forbidden"
        with self.assertRaises(ContractError):
            normalize_requirements_v2(offer)

    def test_unknown_requirement_nature_is_rejected(self):
        offer = synthetic_offer()
        offer["requirements"]["unknown_nature"] = []
        with self.assertRaises(ContractError):
            normalize_requirements_v2(offer)

    def test_non_synthetic_scope_is_rejected(self):
        offer = synthetic_offer()
        offer["fixture_scope"] = "production"
        with self.assertRaises(ContractError):
            prepare_synthetic_opportunity_v2(offer)

    def test_facts_are_copied_and_hash_detects_mutation(self):
        offer = synthetic_offer()
        bundle = prepare_synthetic_opportunity_v2(offer)
        offer["salary"]["monthly_gross_min_eur"] = 1
        self.assertEqual(
            bundle["prepared_opportunity"]["offer"]["salary"]["monthly_gross_min_eur"],
            2400,
        )
        verify_deterministic_conditions_sha256_v2(
            bundle["prepared_opportunity"]["deterministic_conditions"],
            bundle["deterministic_conditions_sha256"],
        )
        changed = copy.deepcopy(bundle["prepared_opportunity"]["deterministic_conditions"])
        changed["salary"]["source_values"]["monthly_gross_min_eur"] = 1
        with self.assertRaises(ContractError):
            verify_deterministic_conditions_sha256_v2(
                changed, bundle["deterministic_conditions_sha256"]
            )

    def test_preparation_performs_no_file_database_or_network_access(self):
        with (
            mock.patch("builtins.open", side_effect=AssertionError("file access")),
            mock.patch("sqlite3.connect", side_effect=AssertionError("sqlite access")),
            mock.patch("socket.create_connection", side_effect=AssertionError("network access")),
        ):
            bundle = prepare_synthetic_opportunity_v2(synthetic_offer())
        self.assertTrue(bundle["prepared_opportunity"]["normalized_requirements"])


if __name__ == "__main__":
    unittest.main()
