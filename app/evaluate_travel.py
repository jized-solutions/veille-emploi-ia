"""Évalue les trajets des offres KEEP/REVIEW depuis Baillargues.

Le calcul utilise TomTom Matrix Routing v2 avec des temps historiques,
adaptés à une estimation en conditions normales. Aucun verdict final n'est
créé ou modifié par ce script.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fetch_france_travail import load_env_file
from normalize_france_travail import json_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "veille_emploi.sqlite"

SCHEMA_VERSION = "3"
PROVIDER = "tomtom"
TRAFFIC_PROFILE = "historical"
TOMTOM_MATRIX_URL = "https://api.tomtom.com/routing/matrix/2"
REQUEST_TIMEOUT_SECONDS = 45

DEFAULT_ORIGIN_LABEL = "Baillargues centre"
DEFAULT_ORIGIN_LATITUDE = 43.660593
DEFAULT_ORIGIN_LONGITUDE = 4.013409

TRAVEL_SCHEMA_SQL = """
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


class TravelError(RuntimeError):
    """Configuration, base ou réponse TomTom invalide."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calcule les trajets TomTom des offres KEEP/REVIEW."
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


def parse_coordinate(name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value.replace(",", "."))
    except ValueError as exc:
        raise TravelError(f"{name} n'est pas un nombre valide.") from exc
    if not minimum <= value <= maximum:
        raise TravelError(f"{name} doit être compris entre {minimum} et {maximum}.")
    return value


def load_configuration() -> tuple[str, str, float, float]:
    load_env_file(PROJECT_ROOT / ".env")
    api_key = os.getenv("TOMTOM_API_KEY", "").strip()
    if not api_key:
        raise TravelError("TOMTOM_API_KEY est absent du fichier .env.")

    label = os.getenv("TRAVEL_ORIGIN_LABEL", DEFAULT_ORIGIN_LABEL).strip()
    latitude = parse_coordinate(
        "TRAVEL_ORIGIN_LATITUDE", DEFAULT_ORIGIN_LATITUDE, -90, 90
    )
    longitude = parse_coordinate(
        "TRAVEL_ORIGIN_LONGITUDE", DEFAULT_ORIGIN_LONGITUDE, -180, 180
    )
    return api_key, label or DEFAULT_ORIGIN_LABEL, latitude, longitude


def check_database(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required = {"schema_meta", "captures", "offers", "filter_results"}
    missing = required - tables
    if missing:
        raise TravelError("Table(s) manquante(s) : " + ", ".join(sorted(missing)))


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
        raise TravelError("Aucune capture normalisée disponible.")
    return int(row[0])


def select_candidates(
    connection: sqlite3.Connection, capture_id: int
) -> list[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT o.id, o.source_offer_id, o.title_normalized, o.location_label,
               o.latitude, o.longitude, f.status
        FROM offers AS o
        JOIN filter_results AS f ON f.offer_id = o.id
        WHERE o.capture_id = ? AND f.status IN ('KEEP', 'REVIEW')
        ORDER BY CASE f.status WHEN 'KEEP' THEN 0 ELSE 1 END, o.id
        """,
        (capture_id,),
    ).fetchall()
    if not rows:
        raise TravelError(
            f"La capture #{capture_id} ne contient aucune offre KEEP ou REVIEW."
        )
    return rows


def call_tomtom_matrix(
    api_key: str,
    origin_latitude: float,
    origin_longitude: float,
    candidates: list[sqlite3.Row],
) -> tuple[dict[str, Any], dict[str, Any]]:
    options = {
        "departAt": "any",
        "routeType": "fastest",
        "traffic": TRAFFIC_PROFILE,
        "travelMode": "car",
    }
    body = {
        "origins": [
            {
                "point": {
                    "latitude": origin_latitude,
                    "longitude": origin_longitude,
                }
            }
        ],
        "destinations": [
            {
                "point": {
                    "latitude": float(candidate["latitude"]),
                    "longitude": float(candidate["longitude"]),
                }
            }
            for candidate in candidates
        ],
        "options": options,
    }
    request = Request(
        f"{TOMTOM_MATRIX_URL}?{urlencode({'key': api_key})}",
        data=json_text(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")[:500]
        raise TravelError(f"TomTom HTTP {exc.code} : {error_body}") from exc
    except URLError as exc:
        raise TravelError(f"Connexion TomTom impossible : {exc.reason}") from exc

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise TravelError("TomTom a renvoyé un JSON invalide.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise TravelError("La réponse TomTom ne contient pas de matrice exploitable.")
    return payload, options


def build_missing_coordinate_results(
    candidates: list[sqlite3.Row],
    origin_label: str,
    origin_latitude: float,
    origin_longitude: float,
) -> list[dict[str, Any]]:
    """Conserve les offres non géolocalisées comme trajets à vérifier."""
    return [
        {
            "offer_id": candidate["id"],
            "source_offer_id": candidate["source_offer_id"],
            "title": candidate["title_normalized"],
            "filter_status": candidate["status"],
            "provider": PROVIDER,
            "traffic_profile": TRAFFIC_PROFILE,
            "origin_label": origin_label,
            "origin_latitude": origin_latitude,
            "origin_longitude": origin_longitude,
            "destination_latitude": candidate["latitude"],
            "destination_longitude": candidate["longitude"],
            "route_status": "ERROR",
            "distance_meters": None,
            "duration_seconds": None,
            "duration_minutes": None,
            "traffic_delay_seconds": None,
            "travel_band": "UNKNOWN",
            "provider_options_json": json_text({}),
            "provider_response_json": json_text(
                {
                    "detailedError": {
                        "code": "MISSING_DESTINATION_COORDINATES",
                        "message": "Coordonnées absentes dans l'offre France Travail",
                    }
                }
            ),
        }
        for candidate in candidates
    ]


def travel_band(duration_seconds: int | None) -> str:
    if duration_seconds is None:
        return "UNKNOWN"
    if duration_seconds <= 35 * 60:
        return "LE_35"
    if duration_seconds <= 60 * 60:
        return "BETWEEN_35_60"
    return "GT_60"


def build_results(
    candidates: list[sqlite3.Row],
    payload: dict[str, Any],
    options: dict[str, Any],
    origin_label: str,
    origin_latitude: float,
    origin_longitude: float,
) -> list[dict[str, Any]]:
    cells_by_destination: dict[int, dict[str, Any]] = {}
    for cell in payload.get("data", []):
        if not isinstance(cell, dict) or cell.get("originIndex") != 0:
            continue
        destination_index = cell.get("destinationIndex")
        if isinstance(destination_index, int):
            cells_by_destination[destination_index] = cell

    results: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        cell = cells_by_destination.get(
            index,
            {"detailedError": {"code": "MISSING_CELL", "message": "Cellule absente"}},
        )
        summary = cell.get("routeSummary") if isinstance(cell, dict) else None
        if isinstance(summary, dict) and isinstance(
            summary.get("travelTimeInSeconds"), int
        ):
            duration_seconds = int(summary["travelTimeInSeconds"])
            distance_meters = summary.get("lengthInMeters")
            delay_seconds = summary.get("trafficDelayInSeconds")
            route_status = "OK"
        else:
            duration_seconds = None
            distance_meters = None
            delay_seconds = None
            route_status = "ERROR"

        results.append(
            {
                "offer_id": candidate["id"],
                "source_offer_id": candidate["source_offer_id"],
                "title": candidate["title_normalized"],
                "filter_status": candidate["status"],
                "provider": PROVIDER,
                "traffic_profile": TRAFFIC_PROFILE,
                "origin_label": origin_label,
                "origin_latitude": origin_latitude,
                "origin_longitude": origin_longitude,
                "destination_latitude": candidate["latitude"],
                "destination_longitude": candidate["longitude"],
                "route_status": route_status,
                "distance_meters": distance_meters,
                "duration_seconds": duration_seconds,
                "duration_minutes": (
                    round(duration_seconds / 60, 1)
                    if duration_seconds is not None
                    else None
                ),
                "traffic_delay_seconds": delay_seconds,
                "travel_band": travel_band(duration_seconds),
                "provider_options_json": json_text(options),
                "provider_response_json": json_text(cell),
            }
        )
    return results


def save_results(
    connection: sqlite3.Connection, results: list[dict[str, Any]]
) -> None:
    evaluated_at = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        """
        INSERT INTO travel_results(
            offer_id, provider, traffic_profile, origin_label, origin_latitude,
            origin_longitude, destination_latitude, destination_longitude,
            route_status, distance_meters, duration_seconds, duration_minutes,
            traffic_delay_seconds, travel_band, provider_options_json,
            provider_response_json, evaluated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            provider = excluded.provider,
            traffic_profile = excluded.traffic_profile,
            origin_label = excluded.origin_label,
            origin_latitude = excluded.origin_latitude,
            origin_longitude = excluded.origin_longitude,
            destination_latitude = excluded.destination_latitude,
            destination_longitude = excluded.destination_longitude,
            route_status = excluded.route_status,
            distance_meters = excluded.distance_meters,
            duration_seconds = excluded.duration_seconds,
            duration_minutes = excluded.duration_minutes,
            traffic_delay_seconds = excluded.traffic_delay_seconds,
            travel_band = excluded.travel_band,
            provider_options_json = excluded.provider_options_json,
            provider_response_json = excluded.provider_response_json,
            evaluated_at_utc = excluded.evaluated_at_utc
        """,
        (
            (
                result["offer_id"],
                result["provider"],
                result["traffic_profile"],
                result["origin_label"],
                result["origin_latitude"],
                result["origin_longitude"],
                result["destination_latitude"],
                result["destination_longitude"],
                result["route_status"],
                result["distance_meters"],
                result["duration_seconds"],
                result["duration_minutes"],
                result["traffic_delay_seconds"],
                result["travel_band"],
                result["provider_options_json"],
                result["provider_response_json"],
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
        print(f"Trajets impossibles : base introuvable : {database_path}", file=sys.stderr)
        return 1

    try:
        api_key, origin_label, origin_latitude, origin_longitude = load_configuration()
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            check_database(connection)
            connection.executescript(TRAVEL_SCHEMA_SQL)
            capture_id = select_capture_id(connection, args.capture_id)
            candidates = select_candidates(connection, capture_id)

            missing_coordinates = [
                candidate
                for candidate in candidates
                if candidate["latitude"] is None or candidate["longitude"] is None
            ]
            routable_candidates = [
                candidate
                for candidate in candidates
                if candidate["latitude"] is not None
                and candidate["longitude"] is not None
            ]

            results: list[dict[str, Any]] = []
            if routable_candidates:
                payload, options = call_tomtom_matrix(
                    api_key,
                    origin_latitude,
                    origin_longitude,
                    routable_candidates,
                )
                results.extend(
                    build_results(
                        routable_candidates,
                        payload,
                        options,
                        origin_label,
                        origin_latitude,
                        origin_longitude,
                    )
                )
            results.extend(
                build_missing_coordinate_results(
                    missing_coordinates,
                    origin_label,
                    origin_latitude,
                    origin_longitude,
                )
            )
            save_results(connection, results)
    except (TravelError, sqlite3.Error) as exc:
        print(f"Trajets impossibles : {exc}", file=sys.stderr)
        return 1

    counts = Counter(result["travel_band"] for result in results)
    errors = sum(result["route_status"] == "ERROR" for result in results)
    print(f"Capture évaluée : #{capture_id} — {len(results)} trajet(s).")
    print(f"Origine : {origin_label} ({origin_latitude}, {origin_longitude}).")
    print(f"≤ 35 min : {counts['LE_35']}")
    print(f"35–60 min : {counts['BETWEEN_35_60']}")
    print(f"> 60 min : {counts['GT_60']}")
    print(f"Trajets inconnus ou en erreur : {counts['UNKNOWN']} (erreurs : {errors}).")
    print("Profil : temps historiques TomTom, voiture, itinéraire le plus rapide.")
    print("Aucun verdict final n'a été créé ou modifié.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
