"""Récupère un petit lot brut d'offres depuis l'API France Travail.

V1.0, étape d'acquisition uniquement : recherche large manuelle ou profils
métiers ciblés. Aucun filtre salarial, IA, trajet ou candidature.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_PROFILES_FILE = PROJECT_ROOT / "config" / "search_profiles.json"

TOKEN_URL = (
    "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    "?realm=/partenaire"
)
SEARCH_URL = (
    "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
)

DEFAULT_COMMUNE = "34022"  # Baillargues (code INSEE)
DEFAULT_DISTANCE_KM = 50
DEFAULT_LIMIT = 20
DEFAULT_LIMIT_PER_QUERY = 5
MAX_LIMIT = 150
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_INTERVAL_SECONDS = 0.4


class ConfigurationError(RuntimeError):
    """Configuration locale absente ou invalide."""


class ApiRequestError(RuntimeError):
    """Échec d'un appel à l'API France Travail."""


class ProfileError(RuntimeError):
    """Fichier de profils ciblés absent ou invalide."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Télécharge un petit lot brut d'offres France Travail."
    )
    parser.add_argument(
        "--commune",
        default=DEFAULT_COMMUNE,
        help="Code INSEE de la commune de départ (défaut : 34022, Baillargues).",
    )
    parser.add_argument(
        "--distance",
        type=int,
        default=DEFAULT_DISTANCE_KM,
        help="Rayon de recherche en kilomètres (défaut : 50).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Nombre d'offres à récupérer, entre 1 et 150 (défaut : 20).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--mots-cles",
        help="Mots-clés facultatifs. Sans cette option, la recherche reste large.",
    )
    mode.add_argument(
        "--profiles",
        action="store_true",
        help="Lance les profils métiers définis dans config/search_profiles.json.",
    )
    parser.add_argument(
        "--profiles-file",
        type=Path,
        default=DEFAULT_PROFILES_FILE,
        help="Fichier JSON des profils ciblés.",
    )
    parser.add_argument(
        "--limit-per-query",
        type=int,
        default=DEFAULT_LIMIT_PER_QUERY,
        help="Offres demandées par requête ciblée, entre 1 et 20 (défaut : 5).",
    )
    return parser.parse_args()


def compact_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def load_profiles(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileError(f"fichier de profils introuvable : {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"lecture impossible : {exc}") from exc

    if not isinstance(document, dict):
        raise ProfileError("la racine du fichier doit être un objet JSON")
    version = compact_text(document.get("version"))
    profiles = document.get("profiles")
    if not version or not isinstance(profiles, list) or not profiles:
        raise ProfileError("version et profiles non vides sont obligatoires")

    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []
    for index, profile in enumerate(profiles, start=1):
        if not isinstance(profile, dict):
            raise ProfileError(f"profil #{index} invalide")
        profile_id = compact_text(profile.get("id"))
        label = compact_text(profile.get("label"))
        horizon = compact_text(profile.get("horizon"))
        raw_queries = profile.get("queries")
        queries = (
            [compact_text(query) for query in raw_queries]
            if isinstance(raw_queries, list)
            else []
        )
        queries = [query for query in queries if query]
        if not profile_id or not label or not horizon or not queries:
            raise ProfileError(
                f"profil #{index} : id, label, horizon et queries sont obligatoires"
            )
        if profile_id in seen_ids:
            raise ProfileError(f"identifiant de profil dupliqué : {profile_id}")
        if horizon not in {"accessible_maintenant", "evolution"}:
            raise ProfileError(
                f"profil {profile_id} : horizon doit valoir "
                "accessible_maintenant ou evolution"
            )
        seen_ids.add(profile_id)
        validated.append(
            {
                "id": profile_id,
                "label": label,
                "horizon": horizon,
                "queries": queries,
            }
        )

    return {"version": version, "profiles": validated}


def load_env_file(path: Path) -> None:
    """Charge un petit fichier .env sans écraser l'environnement existant."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if name:
            os.environ.setdefault(name, value)


def load_credentials() -> tuple[str, str, str]:
    load_env_file(PROJECT_ROOT / ".env")

    client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "").strip()
    client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "").strip()
    scope = os.getenv(
        "FRANCE_TRAVAIL_SCOPE", "api_offresdemploiv2 o2dsoffre"
    ).strip()

    missing = [
        name
        for name, value in (
            ("FRANCE_TRAVAIL_CLIENT_ID", client_id),
            ("FRANCE_TRAVAIL_CLIENT_SECRET", client_secret),
            ("FRANCE_TRAVAIL_SCOPE", scope),
        )
        if not value
    ]
    if missing:
        raise ConfigurationError(
            "Paramètre(s) manquant(s) dans le fichier .env : " + ", ".join(missing)
        )

    return client_id, client_secret, scope


def request_json(request: Request) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw_body = response.read().decode("utf-8")
            headers = dict(response.headers.items())
            status = int(response.getcode())
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise ApiRequestError(f"HTTP {exc.code} : {body}") from exc
    except URLError as exc:
        raise ApiRequestError(f"connexion impossible : {exc.reason}") from exc

    if not raw_body.strip():
        if status == 204:
            return {}, headers
        raise ApiRequestError(f"réponse vide (HTTP {status})")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        content_type = next(
            (
                value
                for name, value in headers.items()
                if name.lower() == "content-type"
            ),
            "type inconnu",
        )
        preview = " ".join(raw_body.split())[:160]
        raise ApiRequestError(
            f"réponse JSON invalide (HTTP {status}, {content_type}) : {preview}"
        ) from exc
    if not isinstance(payload, dict):
        raise ApiRequestError("la réponse JSON n'est pas un objet")
    return payload, headers


def get_access_token(client_id: str, client_secret: str, scope: str) -> str:
    body = urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        }
    ).encode("utf-8")
    request = Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    payload, _ = request_json(request)

    token = payload.get("access_token")
    if not token:
        raise RuntimeError("La réponse d'authentification ne contient aucun jeton.")
    return str(token)


def fetch_offers(
    token: str,
    commune: str,
    distance: int,
    limit: int,
    mots_cles: str | None,
) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    params: dict[str, Any] = {
        "commune": commune,
        "distance": distance,
        "range": f"0-{limit - 1}",
    }
    if mots_cles:
        params["motsCles"] = mots_cles

    request = Request(
        f"{SEARCH_URL}?{urlencode(params)}",
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    payload, headers = request_json(request)
    content_range = next(
        (value for name, value in headers.items() if name.lower() == "content-range"),
        None,
    )
    return payload, content_range, params


def merge_targeted_offer(
    offers_by_id: dict[str, dict[str, Any]],
    source_offer: dict[str, Any],
    profile: dict[str, Any],
    query: str,
) -> bool:
    offer_id = compact_text(source_offer.get("id"))
    if not offer_id:
        raise ApiRequestError("une offre ciblée ne contient aucun identifiant")

    match = {
        "profile_id": profile["id"],
        "profile_label": profile["label"],
        "horizon": profile["horizon"],
        "query": query,
    }
    if offer_id in offers_by_id:
        matches = offers_by_id[offer_id]["_veille_emploi_search"]["matches"]
        if match not in matches:
            matches.append(match)
        return False

    local_offer = copy.deepcopy(source_offer)
    local_offer["_veille_emploi_search"] = {
        "mode": "targeted_profiles",
        "matches": [match],
    }
    offers_by_id[offer_id] = local_offer
    return True


def fetch_targeted_offers(
    token: str,
    commune: str,
    distance: int,
    limit_per_query: int,
    profiles_document: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any], list[dict[str, Any]]]:
    offers_by_id: dict[str, dict[str, Any]] = {}
    call_results: list[dict[str, Any]] = []
    profiles = profiles_document["profiles"]
    call_count = sum(len(profile["queries"]) for profile in profiles)
    current_call = 0

    for profile in profiles:
        for query in profile["queries"]:
            if current_call:
                time.sleep(REQUEST_INTERVAL_SECONDS)
            current_call += 1
            try:
                payload, content_range, params = fetch_offers(
                    token=token,
                    commune=commune,
                    distance=distance,
                    limit=limit_per_query,
                    mots_cles=query,
                )
            except ApiRequestError as exc:
                raise ApiRequestError(
                    f"profil « {profile['label']} », requête « {query} » : {exc}"
                ) from exc
            results = payload.get("resultats", [])
            if not isinstance(results, list):
                raise ApiRequestError(
                    f"résultats invalides pour le profil {profile['id']}"
                )
            unique_added = 0
            for offer in results:
                if not isinstance(offer, dict):
                    raise ApiRequestError(
                        f"offre invalide pour le profil {profile['id']}"
                    )
                unique_added += int(
                    merge_targeted_offer(offers_by_id, offer, profile, query)
                )
            call_results.append(
                {
                    "profile_id": profile["id"],
                    "profile_label": profile["label"],
                    "horizon": profile["horizon"],
                    "query": query,
                    "request_params": params,
                    "content_range": content_range,
                    "returned_count": len(results),
                    "unique_added": unique_added,
                    "call_number": current_call,
                    "call_count": call_count,
                }
            )

    range_summary = " | ".join(
        f"{result['profile_id']} / {result['query']}: "
        f"{result['content_range'] or 'pagination non indiquée'}"
        for result in call_results
    )
    request_summary = {
        "mode": "targeted_profiles",
        "profiles_version": profiles_document["version"],
        "commune": commune,
        "distance": distance,
        "limit_per_query": limit_per_query,
        "profiles": profiles,
    }
    payload = {"resultats": list(offers_by_id.values())}
    return payload, range_summary, request_summary, call_results


def save_capture(
    payload: dict[str, Any],
    content_range: str | None,
    params: dict[str, Any],
    acquisition_details: list[dict[str, Any]] | None = None,
) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    output_path = DATA_DIR / f"france_travail_brut_{now:%Y-%m-%d_%H%M%SZ}.json"

    capture = {
        "_capture": {
            "source": "France Travail - API Offres d'emploi v2",
            "captured_at_utc": now.isoformat(),
            "request_params": params,
            "content_range": content_range,
            "acquisition_details": acquisition_details or [],
            "note": "Réponse conservée avant normalisation, filtrage ou analyse.",
        },
        "response": payload,
    }
    output_path.write_text(
        json.dumps(capture, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    args = parse_args()
    if not 1 <= args.limit <= MAX_LIMIT:
        print("Erreur : --limit doit être compris entre 1 et 150.", file=sys.stderr)
        return 2
    if not 0 <= args.distance <= 100:
        print("Erreur : --distance doit être compris entre 0 et 100 km.", file=sys.stderr)
        return 2
    if not 1 <= args.limit_per_query <= 20:
        print(
            "Erreur : --limit-per-query doit être compris entre 1 et 20.",
            file=sys.stderr,
        )
        return 2

    try:
        client_id, client_secret, scope = load_credentials()
        token = get_access_token(client_id, client_secret, scope)
        if args.profiles:
            profiles_document = load_profiles(args.profiles_file.resolve())
            payload, content_range, params, acquisition_details = (
                fetch_targeted_offers(
                    token=token,
                    commune=args.commune,
                    distance=args.distance,
                    limit_per_query=args.limit_per_query,
                    profiles_document=profiles_document,
                )
            )
        else:
            payload, content_range, params = fetch_offers(
                token=token,
                commune=args.commune,
                distance=args.distance,
                limit=args.limit,
                mots_cles=args.mots_cles,
            )
            acquisition_details = None
        output_path = save_capture(
            payload, content_range, params, acquisition_details=acquisition_details
        )
    except (ConfigurationError, ProfileError) as exc:
        print(f"Configuration incomplète : {exc}", file=sys.stderr)
        return 2
    except ApiRequestError as exc:
        print(f"Échec de l'appel France Travail : {exc}", file=sys.stderr)
        return 1
    except (ValueError, RuntimeError) as exc:
        print(f"Réponse France Travail inexploitable : {exc}", file=sys.stderr)
        return 1

    resultats = payload.get("resultats", [])
    if args.profiles:
        print(f"Capture ciblée terminée : {len(resultats)} offre(s) unique(s).")
        for profile in profiles_document["profiles"]:
            calls = [
                result
                for result in acquisition_details
                if result["profile_id"] == profile["id"]
            ]
            returned = sum(result["returned_count"] for result in calls)
            matching_ids = {
                offer["id"]
                for offer in resultats
                if any(
                    match["profile_id"] == profile["id"]
                    for match in offer["_veille_emploi_search"]["matches"]
                )
            }
            print(
                f"- {profile['label']} : {len(matching_ids)} offre(s) unique(s) "
                f"sur {returned} résultat(s) reçu(s)."
            )
        received = sum(
            result["returned_count"] for result in acquisition_details
        )
        print(f"Doublons exacts regroupés dans cette capture : {received - len(resultats)}.")
    else:
        print(f"Capture terminée : {len(resultats)} offre(s).")
    print(f"Fichier créé : {output_path}")
    if content_range and not args.profiles:
        print(f"Pagination API : {content_range}")
    if args.profiles:
        print("Mode : profils métiers ciblés, sans filtre salarial ni verdict.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
