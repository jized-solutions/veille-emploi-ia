from __future__ import annotations

import copy
import hashlib
import sqlite3
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from ai_contract import (  # noqa: E402
    ContractError,
    INPUT_ARTIFACT_TYPE,
    INPUT_SCHEMA_VERSION,
    add_input_integrity,
    build_policy,
    payload_sha256,
    validate_ai_comparative_input,
)
from prepare_ai_input import (  # noqa: E402
    PreparationError,
    open_read_only_database,
    privacy_check,
    sanitize_text,
    write_exclusive_and_validate,
)


def build_fictitious_artifact() -> dict:
    profile = {
        "skills": [],
        "generalized_experiences": [],
        "education": [],
        "languages": [],
        "technical_boundaries": [],
        "preferences": {},
        "decision_criteria": {},
        "unknowns": [],
    }
    opportunity = {
        "opportunity_key": "offers:FICTIVE-001",
        "offer_ids": ["FICTIVE-001"],
        "scope": "specific_offer_only",
        "offer": {
            "source_offer_id": "FICTIVE-001",
            "title": "Poste fictif",
            "description_cleaned": "Description entièrement fictive.",
            "employer": {
                "name": "Employeur fictif",
                "is_anonymous": False,
                "establishment_size": None,
                "sector": {"code": None, "label": None},
            },
            "contract": {
                "code": "CDI",
                "label": "Contrat fictif",
                "family": "permanent",
                "nature_code": None,
                "work_time_type": None,
                "weekly_hours": 35.0,
            },
            "schedule": {
                "text": None,
                "work_context": {},
                "works_at_night": None,
                "works_shifted_hours": False,
                "works_weekend": None,
                "works_saturday": None,
                "works_sunday": None,
            },
            "salary": {
                "label_cleaned": None,
                "comment_cleaned": None,
                "unit": None,
                "amount_min": None,
                "amount_max": None,
                "payment_months": None,
                "monthly_gross_min": None,
                "monthly_gross_max": None,
                "conversion_method": None,
                "complements": [],
            },
            "work_location": {"public_area": "Zone fictive"},
            "travel": {
                "duration_minutes": 20.0,
                "distance_meters": 10000,
                "band": "TARGET",
            },
            "professional_travel": {
                "code": None,
                "label": None,
                "required": None,
            },
            "requirements": {
                "experience": {"code": None, "label": None, "comment": None},
                "qualification": {"code": None, "label": None},
                "skills": [],
                "education": [],
                "licences_and_authorizations": [],
                "professional_qualities": [],
            },
        },
        "mechanical": {
            "status": "KEEP",
            "review_reasons": [],
            "warnings": [],
            "schedule_penalty": 0,
        },
        "duplicates": {
            "group_key": None,
            "representative_offer_id": None,
            "group_size": 1,
        },
    }
    policy = build_policy()
    artifact = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "artifact_type": INPUT_ARTIFACT_TYPE,
        "provenance": {
            "capture_id": 999,
            "capture_source_sha256": "1" * 64,
            "filter_rules_version": "fictitious-filter-v1",
            "duplicate_detection_version": "fictitious-duplicates-v1",
        },
        "policy": policy,
        "profile": {
            "profile_schema_version": 1,
            "profile_payload_sha256": payload_sha256(profile),
            "snapshot": profile,
        },
        "selection": {
            "eligible_mechanical_statuses": ["KEEP", "REVIEW"],
            "duplicate_policy": "stored_representative_only",
            "opportunity_count": 1,
            "covered_offer_id_count": 1,
        },
        "opportunities": [opportunity],
        "integrity": {
            "policy_payload_sha256": payload_sha256(policy),
            "profile_payload_sha256": payload_sha256(profile),
            "opportunities_payload_sha256": payload_sha256([opportunity]),
        },
    }
    add_input_integrity(artifact)
    validate_ai_comparative_input(artifact)
    return artifact


class FixedDatetime:
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 8, 19, 13, 0, 0, tzinfo=timezone.utc)


class ExclusiveWriteTests(unittest.TestCase):
    def test_collision_preserves_preexisting_file_content_and_hash(self):
        artifact = build_fictitious_artifact()
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            existing = output_dir / "ai_comparative_input_capture_999_20260819T130000000000Z.json"
            existing.write_bytes(b"preexisting fictitious artifact\n")
            hash_before = hashlib.sha256(existing.read_bytes()).hexdigest()
            content_before = existing.read_bytes()

            with patch("prepare_ai_input.datetime", FixedDatetime):
                with self.assertRaises(FileExistsError):
                    write_exclusive_and_validate(artifact, output_dir, 999)

            self.assertEqual(existing.read_bytes(), content_before)
            self.assertEqual(hashlib.sha256(existing.read_bytes()).hexdigest(), hash_before)

    def test_validation_failure_deletes_only_file_created_by_current_run(self):
        artifact = build_fictitious_artifact()
        with TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            output_path = output_dir / "ai_comparative_input_capture_999_20260819T130000000000Z.json"
            with (
                patch("prepare_ai_input.datetime", FixedDatetime),
                patch(
                    "prepare_ai_input.load_json_file",
                    side_effect=ContractError("synthetic validation failure"),
                ),
            ):
                with self.assertRaises(ContractError):
                    write_exclusive_and_validate(artifact, output_dir, 999)
            self.assertFalse(output_path.exists())


class PrivacyPatternTests(unittest.TestCase):
    def assert_detected_and_cleaned(self, sample: str, finding: str):
        findings = privacy_check({"text": sample})
        self.assertTrue(findings[finding], sample)
        cleaned = sanitize_text(f"Début fictif. {sample} Fin fictive.")
        cleaned_findings = privacy_check({"text": cleaned or ""})
        self.assertFalse(cleaned_findings[finding], sample)

    def test_domains_and_protocol_urls(self):
        for sample in (
            "example.fr",
            "recrutement.example.com",
            "https://example.fr/candidature",
            "www.example.fr/offre",
        ):
            with self.subTest(sample=sample):
                self.assert_detected_and_cleaned(sample, "url")

    def test_classic_and_obfuscated_emails(self):
        for sample in (
            "candidat@example.fr",
            "candidat [at] example [dot] fr",
            "candidat (at) example (dot) fr",
            "candidat arobase example [dot] fr",
        ):
            with self.subTest(sample=sample):
                self.assert_detected_and_cleaned(sample, "email")

    def test_french_phone_formats(self):
        for sample in (
            "06 12 34 56 78",
            "+33 6 12 34 56 78",
            "0033 6 12 34 56 78",
        ):
            with self.subTest(sample=sample):
                self.assert_detected_and_cleaned(sample, "phone")

    def test_windows_unc_and_unix_paths(self):
        for sample in (
            r"C:\Temp\fiction.txt",
            r"\\server-fictif\partage\fiction.txt",
            "/home/fictif/fiction.txt",
        ):
            with self.subTest(sample=sample):
                self.assert_detected_and_cleaned(sample, "local_path")

    def test_precise_postal_address(self):
        self.assert_detected_and_cleaned("12 rue des Fleurs", "postal_address")

    def test_explicit_application_instruction(self):
        self.assert_detected_and_cleaned(
            "Merci d’adresser votre CV au service fictif.",
            "contact_or_application_instruction",
        )

    def test_version_is_not_a_domain(self):
        text = "La version v1.2 reste stable."
        self.assertFalse(privacy_check({"text": text})["url"])
        self.assertEqual(sanitize_text(text), text)

    def test_sentence_boundary_without_space_is_not_a_domain(self):
        text = "Une première phrase se termine ici.La suivante reste utile."
        self.assertFalse(privacy_check({"text": text})["url"])
        self.assertEqual(sanitize_text(text), text)

    def test_ordinary_point_sentence_is_not_an_email(self):
        text = "Le point important concerne uniquement le poste fictif."
        self.assertFalse(privacy_check({"text": text})["email"])
        self.assertEqual(sanitize_text(text), text)

    def test_salary_and_date_are_not_phone_numbers(self):
        text = "Salaire 2500 euros, validation le 19/08/2026."
        self.assertFalse(privacy_check({"text": text})["phone"])
        self.assertEqual(sanitize_text(text), text)


class StrictContractTests(unittest.TestCase):
    def test_boolean_is_rejected_for_schema_version_and_capture_id(self):
        for path in ("schema_version", "capture_id"):
            artifact = build_fictitious_artifact()
            if path == "schema_version":
                artifact["schema_version"] = True
            else:
                artifact["provenance"]["capture_id"] = True
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    validate_ai_comparative_input(artifact)

    def test_non_boolean_is_rejected_for_boolean_field(self):
        artifact = build_fictitious_artifact()
        artifact["opportunities"][0]["offer"]["employer"]["is_anonymous"] = 0
        with self.assertRaises(ContractError):
            validate_ai_comparative_input(artifact)

    def test_unknown_nested_offer_key_is_rejected(self):
        artifact = build_fictitious_artifact()
        artifact["opportunities"][0]["offer"]["employer"][
            "unexpected_private_note"
        ] = "fiction"
        with self.assertRaises(ContractError):
            validate_ai_comparative_input(artifact)

    def test_each_altered_integrity_hash_is_rejected(self):
        for name in (
            "policy_payload_sha256",
            "profile_payload_sha256",
            "opportunities_payload_sha256",
            "input_payload_sha256",
        ):
            artifact = build_fictitious_artifact()
            artifact["integrity"][name] = "0" * 64
            with self.subTest(name=name):
                with self.assertRaises(ContractError):
                    validate_ai_comparative_input(artifact)


class SqliteLifecycleTests(unittest.TestCase):
    def test_connection_is_closed_when_initialization_fails(self):
        connection = Mock()
        connection.execute.side_effect = sqlite3.OperationalError("synthetic failure")
        with patch("prepare_ai_input.sqlite3.connect", return_value=connection):
            with self.assertRaises(PreparationError):
                open_read_only_database(Path("fictitious.sqlite"))
        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
