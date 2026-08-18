"""Applique les premiers filtres mécaniques aux offres normalisées.

Les résultats KEEP / REVIEW / EXCLUDE restent séparés des offres sources.
Ce ne sont pas les verdicts finaux du projet et aucun trajet ou score IA
n'est calculé ici.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from normalize_france_travail import json_text, searchable_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "veille_emploi.sqlite"

RULES_VERSION = "mechanical-v1.2"
SCHEMA_VERSION = "2"
SALARY_THRESHOLD_MONTHLY = 2500.0
MAX_UNQUANTIFIED_COMPLEMENT_GAP_MONTHLY = 250.0
ACCEPTED_CONTRACTS = {"cdi", "cdd", "interim"}

FILTER_SCHEMA_SQL = """
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
"""

ADMIN_TITLE_PATTERNS = (
    "agent administratif",
    "agente administrative",
    "assistant administratif",
    "assistante administrative",
    "employe administratif",
    "employee administrative",
    "gestionnaire administratif",
    "gestionnaire administrative",
    "secretaire administratif",
    "secretaire administrative",
)
ACCOUNTING_TITLE_PATTERNS = (
    "comptable",
    "aide comptable",
    "assistant comptable",
    "assistante comptable",
    "gestionnaire comptable",
)
GROCERY_MANAGEMENT_TITLE_TERMS = (
    "directeur",
    "directrice",
    "responsable de magasin",
    "manager",
    "commercial",
    "commerciale",
)
GROCERY_SECTOR_TERMS = (
    "hypermarches",
    "supermarches",
    "superettes",
    "grande distribution alimentaire",
    "commerce de detail alimentaires",
)
VARIABLE_PAY_TERMS = (
    "prime",
    "primes",
    "variable",
    "commission",
    "commissions",
    "bonus",
)
PROFIT_SHARING_TERMS = (
    "interessement",
    "participation",
)
NON_SALARY_BENEFIT_TERMS = (
    "titre restaurant",
    "titres restaurant",
    "ticket restaurant",
    "tickets restaurant",
    "prime de panier",
    "panier repas",
    "complementaire sante",
    "mutuelle",
    "cse",
    "remboursement transport",
    "forfait mobilites durables",
    "retraite complementaire",
)
ENTREPRENEURIAL_OFFER_PATTERNS = (
    "lancez votre propre activite",
    "lancer votre propre activite",
    "prendre les commandes de votre propre activite",
    "projet entrepreneurial",
    "creez votre entreprise",
    "creer votre entreprise",
    "devenez independant",
    "devenir independant",
    "statut d'independant",
    "statut independant",
)


class FilterError(RuntimeError):
    """Base absente, incomplète ou capture inconnue."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Applique les filtres mécaniques aux offres SQLite."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="Base SQLite (défaut : data/veille_emploi.sqlite).",
    )
    parser.add_argument(
        "--capture-id",
        type=int,
        help="Capture à traiter. Par défaut : la plus récente.",
    )
    return parser.parse_args()


def parse_json_list(value: Any) -> list[Any]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def unquantified_pay_components(row: sqlite3.Row) -> set[str]:
    components: set[str] = set()
    for item in parse_json_list(row["salary_complements_json"]):
        if not isinstance(item, dict):
            continue
        label = searchable_text(str(item.get("libelle", "")))
        if any(term in label for term in NON_SALARY_BENEFIT_TERMS):
            continue
        if any(term in label for term in PROFIT_SHARING_TERMS):
            components.add("profit_sharing")
        if any(term in label for term in VARIABLE_PAY_TERMS):
            components.add("variable_pay")

    comment = searchable_text(row["salary_comment_raw"] or "")
    if "inclu" not in comment:
        if any(term in comment for term in PROFIT_SHARING_TERMS):
            components.add("profit_sharing")
        if any(term in comment for term in ("variable", "commission", "bonus")):
            components.add("variable_pay")
    return components


def is_pure_admin_title(title: str) -> bool:
    return any(pattern in title for pattern in ADMIN_TITLE_PATTERNS)


def is_pure_accounting_title(title: str) -> bool:
    return any(pattern in title for pattern in ACCOUNTING_TITLE_PATTERNS)


def is_grocery_management(row: sqlite3.Row, title: str) -> bool:
    role_match = any(term in title for term in GROCERY_MANAGEMENT_TITLE_TERMS)
    sector = searchable_text(
        " ".join(
            str(value or "")
            for value in (row["sector_label"], row["description_raw"])
        )
    )
    sector_match = any(term in sector for term in GROCERY_SECTOR_TERMS)
    return role_match and sector_match


def is_entrepreneurial_offer(row: sqlite3.Row) -> bool:
    description = searchable_text(row["description_raw"] or "")
    return any(pattern in description for pattern in ENTREPRENEURIAL_OFFER_PATTERNS)


def evaluate_offer(row: sqlite3.Row) -> dict[str, Any]:
    exclusions: list[str] = []
    reviews: list[str] = []
    warnings: list[str] = []

    contract_family = row["contract_family"]
    if contract_family == "franchise":
        exclusions.append("contrat_franchise_non_salarie")
    elif contract_family not in ACCEPTED_CONTRACTS:
        exclusions.append("type_contrat_non_accepte")

    salary_max = row["salary_monthly_gross_max"]
    if salary_max is None:
        conversion_method = row["salary_conversion_method"] or ""
        if conversion_method.startswith("rejected_"):
            reviews.append("remuneration_structuree_incoherente_a_verifier")
        else:
            reviews.append("remuneration_non_chiffree_a_verifier")
    elif float(salary_max) < SALARY_THRESHOLD_MONTHLY:
        pay_components = unquantified_pay_components(row)
        salary_gap = SALARY_THRESHOLD_MONTHLY - float(salary_max)
        if pay_components and salary_gap <= MAX_UNQUANTIFIED_COMPLEMENT_GAP_MONTHLY:
            if "variable_pay" in pay_components:
                reviews.append("variable_non_chiffre_a_verifier")
            if "profit_sharing" in pay_components:
                reviews.append("interessement_participation_non_chiffres_a_verifier")
        else:
            exclusions.append("remuneration_connue_inferieure_a_2500")

    title = searchable_text(row["title_normalized"] or "")
    if is_pure_accounting_title(title):
        exclusions.append("comptabilite_pure")
    if is_pure_admin_title(title):
        exclusions.append("administratif_pur")
    if is_grocery_management(row, title):
        exclusions.append("direction_ou_commercial_grande_distribution_alimentaire")
    if is_entrepreneurial_offer(row):
        exclusions.append("offre_entrepreneuriale_hors_perimetre_salarie")

    schedule_penalty = 0
    if row["works_at_night"] == 1:
        warnings.append("travail_de_nuit")
        schedule_penalty = 2
    if row["works_shifted_hours"] == 1:
        warnings.append("horaires_decales")
        schedule_penalty = max(schedule_penalty, 1)
    if row["travel_required"] == 1:
        warnings.append("deplacements_professionnels_declares")
    if row["employer_is_anonymous"] == 1:
        warnings.append("employeur_anonyme")
    if row["weekly_hours"] is None:
        warnings.append("duree_hebdomadaire_non_structuree")

    if exclusions:
        status = "EXCLUDE"
    elif reviews:
        status = "REVIEW"
    else:
        status = "KEEP"

    return {
        "offer_id": row["id"],
        "source_offer_id": row["source_offer_id"],
        "title": row["title_normalized"],
        "status": status,
        "exclusions": exclusions,
        "reviews": reviews,
        "warnings": warnings,
        "schedule_penalty": schedule_penalty,
    }


def check_database(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required = {"schema_meta", "captures", "offers"}
    missing = required - tables
    if missing:
        raise FilterError("Table(s) manquante(s) : " + ", ".join(sorted(missing)))


def select_capture_id(
    connection: sqlite3.Connection, requested_capture_id: int | None
) -> int:
    if requested_capture_id is None:
        row = connection.execute("SELECT MAX(id) FROM captures").fetchone()
        capture_id = row[0] if row else None
    else:
        row = connection.execute(
            "SELECT id FROM captures WHERE id = ?", (requested_capture_id,)
        ).fetchone()
        capture_id = row[0] if row else None
    if capture_id is None:
        raise FilterError("Aucune capture normalisée disponible.")
    return int(capture_id)


def save_results(
    connection: sqlite3.Connection,
    results: list[dict[str, Any]],
) -> None:
    evaluated_at = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        """
        INSERT INTO filter_results(
            offer_id, status, exclusion_reasons_json, review_reasons_json,
            warnings_json, schedule_penalty, salary_threshold_monthly,
            rules_version, evaluated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            status = excluded.status,
            exclusion_reasons_json = excluded.exclusion_reasons_json,
            review_reasons_json = excluded.review_reasons_json,
            warnings_json = excluded.warnings_json,
            schedule_penalty = excluded.schedule_penalty,
            salary_threshold_monthly = excluded.salary_threshold_monthly,
            rules_version = excluded.rules_version,
            evaluated_at_utc = excluded.evaluated_at_utc
        """,
        (
            (
                result["offer_id"],
                result["status"],
                json_text(result["exclusions"]),
                json_text(result["reviews"]),
                json_text(result["warnings"]),
                result["schedule_penalty"],
                SALARY_THRESHOLD_MONTHLY,
                RULES_VERSION,
                evaluated_at,
            )
            for result in results
        ),
    )
    connection.execute(
        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION,),
    )


def main() -> int:
    args = parse_args()
    database_path = args.database.resolve()
    if not database_path.is_file():
        print(f"Filtrage impossible : base introuvable : {database_path}", file=sys.stderr)
        return 1

    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            check_database(connection)
            connection.executescript(FILTER_SCHEMA_SQL)
            capture_id = select_capture_id(connection, args.capture_id)
            rows = connection.execute(
                "SELECT * FROM offers WHERE capture_id = ? ORDER BY id", (capture_id,)
            ).fetchall()
            if not rows:
                raise FilterError(f"La capture #{capture_id} ne contient aucune offre.")
            results = [evaluate_offer(row) for row in rows]
            save_results(connection, results)
    except (FilterError, sqlite3.Error) as exc:
        print(f"Filtrage impossible : {exc}", file=sys.stderr)
        return 1

    counts = Counter(result["status"] for result in results)
    print(f"Capture filtrée : #{capture_id} — {len(results)} offre(s).")
    print(f"KEEP : {counts['KEEP']}")
    print(f"REVIEW : {counts['REVIEW']}")
    print(f"EXCLUDE : {counts['EXCLUDE']}")
    print(f"Seuil salarial appliqué : {SALARY_THRESHOLD_MONTHLY:.0f} € brut/mois.")
    print("Les horaires décalés sont pénalisés mais non exclus.")
    print("Aucun verdict final, trajet ou score IA n'a été calculé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
