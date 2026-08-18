"""Détecte les quasi-doublons d'une capture sans supprimer aucune offre.

La détection V1 est déterministe et locale : même employeur, même intitulé,
puis forte similarité de description. Les groupes restent séparés des offres
sources et peuvent être recalculés sans modifier filtres, trajets ou verdicts.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from normalize_france_travail import searchable_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "veille_emploi.sqlite"

DETECTION_VERSION = "same-employer-title-description-v1"
MIN_DESCRIPTION_LENGTH = 200
MIN_SEQUENCE_SIMILARITY = 0.55
MIN_TOKEN_JACCARD = 0.25

DUPLICATE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS duplicate_runs (
    capture_id INTEGER PRIMARY KEY REFERENCES captures(id) ON DELETE CASCADE,
    detection_version TEXT NOT NULL,
    group_count INTEGER NOT NULL CHECK (group_count >= 0),
    member_count INTEGER NOT NULL CHECK (member_count >= 0),
    evaluated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS duplicate_results (
    offer_id INTEGER PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
    capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
    group_key TEXT NOT NULL,
    representative_offer_id INTEGER NOT NULL REFERENCES offers(id),
    group_size INTEGER NOT NULL CHECK (group_size >= 2),
    similarity_to_representative REAL NOT NULL CHECK (
        similarity_to_representative >= 0 AND similarity_to_representative <= 1
    ),
    detection_method TEXT NOT NULL,
    evaluated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_duplicate_results_capture
    ON duplicate_results(capture_id);
CREATE INDEX IF NOT EXISTS idx_duplicate_results_group
    ON duplicate_results(group_key);
"""


class DuplicateError(RuntimeError):
    """Base absente, incomplète ou capture inconnue."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Détecte les quasi-doublons d'une capture normalisée."
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


def normalized_text(value: Any) -> str:
    text = searchable_text(str(value or ""))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def token_jaccard(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def description_similarity(left: str, right: str) -> tuple[float, float]:
    sequence = SequenceMatcher(None, left, right, autojunk=False).ratio()
    return sequence, token_jaccard(left, right)


def are_duplicates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if not left["employer_key"] or left["employer_key"] != right["employer_key"]:
        return False
    if not left["title_key"] or left["title_key"] != right["title_key"]:
        return False
    if min(len(left["description_key"]), len(right["description_key"])) < MIN_DESCRIPTION_LENGTH:
        return False
    if left["description_key"] == right["description_key"]:
        return True
    sequence, jaccard = description_similarity(
        left["description_key"], right["description_key"]
    )
    return sequence >= MIN_SEQUENCE_SIMILARITY and jaccard >= MIN_TOKEN_JACCARD


def check_database(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required = {"captures", "offers", "filter_results", "travel_results"}
    missing = required - tables
    if missing:
        raise DuplicateError("Table(s) manquante(s) : " + ", ".join(sorted(missing)))


def select_capture_id(
    connection: sqlite3.Connection, requested_capture_id: int | None
) -> int:
    if requested_capture_id is None:
        row = connection.execute("SELECT MAX(id) FROM captures").fetchone()
    else:
        row = connection.execute(
            "SELECT id FROM captures WHERE id = ?", (requested_capture_id,)
        ).fetchone()
    if not row or row[0] is None:
        raise DuplicateError("Aucune capture normalisée disponible.")
    return int(row[0])


def select_offers(
    connection: sqlite3.Connection, capture_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT o.id, o.source_offer_id, o.title_normalized, o.description_raw,
               o.employer_name, o.salary_monthly_gross_max,
               f.status, t.travel_band, t.duration_minutes
        FROM offers AS o
        LEFT JOIN filter_results AS f ON f.offer_id = o.id
        LEFT JOIN travel_results AS t ON t.offer_id = o.id
        WHERE o.capture_id = ?
        ORDER BY o.id
        """,
        (capture_id,),
    ).fetchall()
    if not rows:
        raise DuplicateError(f"La capture #{capture_id} ne contient aucune offre.")
    if any(row["status"] is None for row in rows):
        raise DuplicateError("Filtres absents. Lancez d'abord filter_offers.py.")

    return [
        {
            **dict(row),
            "employer_key": normalized_text(row["employer_name"]),
            "title_key": normalized_text(row["title_normalized"]),
            "description_key": normalized_text(row["description_raw"]),
        }
        for row in rows
    ]


def duplicate_groups(offers: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    parents = list(range(len(offers)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    candidates: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, offer in enumerate(offers):
        candidates[(offer["employer_key"], offer["title_key"])].append(index)

    for (employer_key, title_key), indices in candidates.items():
        if not employer_key or not title_key or len(indices) < 2:
            continue
        for position, left_index in enumerate(indices):
            for right_index in indices[position + 1 :]:
                if are_duplicates(offers[left_index], offers[right_index]):
                    union(left_index, right_index)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, offer in enumerate(offers):
        grouped[find(index)].append(offer)
    return [group for group in grouped.values() if len(group) >= 2]


def representative_rank(offer: dict[str, Any]) -> tuple[Any, ...]:
    return (
        {"KEEP": 0, "REVIEW": 1, "EXCLUDE": 2}.get(offer["status"], 3),
        {"LE_35": 0, "BETWEEN_35_60": 1, "GT_60": 2, "UNKNOWN": 3}.get(
            offer["travel_band"], 4
        ),
        offer["duration_minutes"] if offer["duration_minutes"] is not None else 10**9,
        0 if offer["salary_monthly_gross_max"] is not None else 1,
        offer["source_offer_id"],
    )


def group_key(group: list[dict[str, Any]]) -> str:
    identifiers = "|".join(sorted(offer["source_offer_id"] for offer in group))
    digest = hashlib.sha256(identifiers.encode("utf-8")).hexdigest()[:12]
    return f"DUP-{digest}"


def save_groups(
    connection: sqlite3.Connection,
    capture_id: int,
    groups: list[list[dict[str, Any]]],
) -> None:
    evaluated_at = datetime.now(timezone.utc).isoformat()
    connection.execute("DELETE FROM duplicate_results WHERE capture_id = ?", (capture_id,))

    records = []
    for group in groups:
        representative = min(group, key=representative_rank)
        key = group_key(group)
        for offer in group:
            sequence, _ = description_similarity(
                representative["description_key"], offer["description_key"]
            )
            records.append(
                (
                    offer["id"],
                    capture_id,
                    key,
                    representative["id"],
                    len(group),
                    round(sequence, 6),
                    DETECTION_VERSION,
                    evaluated_at,
                )
            )

    connection.executemany(
        """
        INSERT INTO duplicate_results(
            offer_id, capture_id, group_key, representative_offer_id,
            group_size, similarity_to_representative, detection_method,
            evaluated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )
    connection.execute(
        """
        INSERT INTO duplicate_runs(
            capture_id, detection_version, group_count, member_count,
            evaluated_at_utc
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(capture_id) DO UPDATE SET
            detection_version = excluded.detection_version,
            group_count = excluded.group_count,
            member_count = excluded.member_count,
            evaluated_at_utc = excluded.evaluated_at_utc
        """,
        (capture_id, DETECTION_VERSION, len(groups), len(records), evaluated_at),
    )


def main() -> int:
    args = parse_args()
    database_path = args.database.resolve()
    if not database_path.is_file():
        print(f"Doublons impossibles : base introuvable : {database_path}", file=sys.stderr)
        return 1

    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            check_database(connection)
            connection.executescript(DUPLICATE_SCHEMA_SQL)
            capture_id = select_capture_id(connection, args.capture_id)
            offers = select_offers(connection, capture_id)
            groups = duplicate_groups(offers)
            save_groups(connection, capture_id, groups)
    except (DuplicateError, sqlite3.Error) as exc:
        print(f"Doublons impossibles : {exc}", file=sys.stderr)
        return 1

    member_count = sum(len(group) for group in groups)
    print(f"Capture analysée : #{capture_id} — {len(offers)} offre(s).")
    print(f"Groupes de quasi-doublons : {len(groups)}.")
    print(f"Offres regroupées : {member_count}.")
    for group in groups:
        representative = min(group, key=representative_rank)
        members = ", ".join(sorted(offer["source_offer_id"] for offer in group))
        print(
            f"- {group_key(group)} : représentant {representative['source_offer_id']} "
            f"— membres {members}."
        )
    print("Aucune offre n'a été supprimée et aucun filtre ou trajet n'a été modifié.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
