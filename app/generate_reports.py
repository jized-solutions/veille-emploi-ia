"""Génère les rapports HTML et CSV depuis les résultats SQLite existants.

Étape 7 de la V1 : ce script lit uniquement la base. Il ne recalcule ni
filtre, ni trajet, ni verdict final, et ne modifie aucune table SQLite.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "veille_emploi.sqlite"
DEFAULT_HTML_DIR = PROJECT_ROOT / "reports" / "html"
DEFAULT_CSV_DIR = PROJECT_ROOT / "reports" / "csv"

STATUS_ORDER = {"KEEP": 0, "REVIEW": 1, "EXCLUDE": 2}
STATUS_LABELS = {
    "KEEP": "À conserver",
    "REVIEW": "À vérifier",
    "EXCLUDE": "Exclue",
}
STATUS_SECTION_TITLES = {
    "KEEP": "À conserver (KEEP)",
    "REVIEW": "À vérifier (REVIEW)",
    "EXCLUDE": "Exclues (EXCLUDE)",
}
REASON_LABELS = {
    "contrat_franchise_non_salarie": "Contrat de franchise / activité non salariée",
    "type_contrat_non_accepte": "Type de contrat non accepté",
    "remuneration_connue_inferieure_a_2500": (
        "Rémunération connue inférieure à 2 500 € brut/mois"
    ),
    "comptabilite_pure": "Comptabilité pure",
    "administratif_pur": "Administratif pur",
    "direction_ou_commercial_grande_distribution_alimentaire": (
        "Direction/commercial en grande distribution alimentaire"
    ),
    "remuneration_non_chiffree_a_verifier": "Rémunération non chiffrée à vérifier",
    "remuneration_structuree_incoherente_a_verifier": (
        "Rémunération structurée incohérente à vérifier"
    ),
    "variable_non_chiffre_a_verifier": "Variable ou primes non chiffrées à vérifier",
    "interessement_participation_non_chiffres_a_verifier": (
        "Intéressement ou participation non chiffrés à vérifier"
    ),
    "offre_entrepreneuriale_hors_perimetre_salarie": (
        "Offre entrepreneuriale hors du périmètre salarié"
    ),
    "travail_de_nuit": "Travail de nuit",
    "horaires_decales": "Horaires décalés",
    "deplacements_professionnels_declares": "Déplacements professionnels déclarés",
    "employeur_anonyme": "Employeur non indiqué",
    "duree_hebdomadaire_non_structuree": "Durée hebdomadaire non structurée",
}
TRAVEL_LABELS = {
    "LE_35": "≤ 35 min — cible",
    "BETWEEN_35_60": "35–60 min — offre forte seulement",
    "GT_60": "> 60 min — hors cible",
    "UNKNOWN": "Trajet inconnu ou en erreur",
}

CSV_FIELDS = (
    "capture_id",
    "id_offre",
    "groupe_quasi_doublon",
    "representant_quasi_doublon",
    "similarite_avec_representant",
    "statut_mecanique",
    "titre",
    "entreprise",
    "lieu",
    "contrat",
    "temps_travail",
    "heures_hebdomadaires",
    "salaire_mensuel_min_eur",
    "salaire_mensuel_max_eur",
    "salaire_original",
    "trajet_minutes",
    "trajet_km",
    "categorie_trajet",
    "penalite_horaires",
    "raisons_exclusion",
    "raisons_verification",
    "avertissements",
    "date_creation",
    "url_offre",
)


class ReportError(RuntimeError):
    """Base absente, incomplète ou résultats préalables manquants."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère les rapports HTML et CSV depuis SQLite."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="Base SQLite source (défaut : data/veille_emploi.sqlite).",
    )
    parser.add_argument(
        "--capture-id",
        type=int,
        help="Capture à publier. Par défaut : la plus récente.",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=DEFAULT_HTML_DIR,
        help="Dossier du rapport HTML.",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=DEFAULT_CSV_DIR,
        help="Dossier du rapport CSV.",
    )
    return parser.parse_args()


def parse_json_list(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def translated_reasons(value: Any) -> list[str]:
    return [REASON_LABELS.get(code, code.replace("_", " ")) for code in parse_json_list(value)]


def check_database(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required = {
        "captures", "offers", "filter_results", "travel_results",
        "duplicate_runs", "duplicate_results",
    }
    missing = required - tables
    if missing:
        raise ReportError("Table(s) manquante(s) : " + ", ".join(sorted(missing)))


def select_capture(
    connection: sqlite3.Connection, requested_capture_id: int | None
) -> sqlite3.Row:
    if requested_capture_id is None:
        row = connection.execute(
            "SELECT * FROM captures ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT * FROM captures WHERE id = ?", (requested_capture_id,)
        ).fetchone()
    if row is None:
        raise ReportError("Aucune capture normalisée disponible.")
    return row


def select_offers(
    connection: sqlite3.Connection, capture_id: int
) -> list[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT
            o.source_offer_id, o.title_normalized, o.created_at_utc,
            o.contract_label, o.contract_family, o.work_time_type,
            o.weekly_hours, o.work_schedule_text, o.salary_label_raw,
            o.salary_comment_raw, o.salary_monthly_gross_min,
            o.salary_monthly_gross_max, o.location_label, o.postal_code,
            o.employer_name, o.source_url, o.application_url,
            f.status, f.exclusion_reasons_json, f.review_reasons_json,
            f.warnings_json, f.schedule_penalty, f.salary_threshold_monthly,
            f.rules_version, f.evaluated_at_utc AS filter_evaluated_at_utc,
            t.provider, t.traffic_profile, t.origin_label,
            t.route_status, t.distance_meters, t.duration_minutes,
            t.travel_band, t.evaluated_at_utc AS travel_evaluated_at_utc,
            d.group_key AS duplicate_group_key,
            d.group_size AS duplicate_group_size,
            d.similarity_to_representative,
            representative.source_offer_id AS duplicate_representative_id
        FROM offers AS o
        LEFT JOIN filter_results AS f ON f.offer_id = o.id
        LEFT JOIN travel_results AS t ON t.offer_id = o.id
        LEFT JOIN duplicate_results AS d ON d.offer_id = o.id
        LEFT JOIN offers AS representative ON representative.id = d.representative_offer_id
        WHERE o.capture_id = ?
        """,
        (capture_id,),
    ).fetchall()
    if not rows:
        raise ReportError(f"La capture #{capture_id} ne contient aucune offre.")

    missing_filters = [row["source_offer_id"] for row in rows if row["status"] is None]
    if missing_filters:
        raise ReportError(
            "Filtres absents pour la capture. Lancez d'abord filter_offers.py."
        )

    missing_travel = [
        row["source_offer_id"]
        for row in rows
        if row["status"] in {"KEEP", "REVIEW"} and row["travel_band"] is None
    ]
    if missing_travel:
        raise ReportError(
            "Trajets absents pour une ou plusieurs offres KEEP/REVIEW. "
            "Lancez d'abord evaluate_travel.py."
        )

    return sorted(
        rows,
        key=lambda row: (
            STATUS_ORDER[row["status"]],
            {"LE_35": 0, "BETWEEN_35_60": 1, "GT_60": 2, "UNKNOWN": 3}.get(
                row["travel_band"], 4
            ),
            row["schedule_penalty"],
            -(row["salary_monthly_gross_max"] or 0),
            row["title_normalized"].casefold(),
        ),
    )


def check_duplicate_run(connection: sqlite3.Connection, capture_id: int) -> None:
    row = connection.execute(
        "SELECT capture_id FROM duplicate_runs WHERE capture_id = ?", (capture_id,)
    ).fetchone()
    if row is None:
        raise ReportError(
            "Détection des quasi-doublons absente. "
            "Lancez d'abord detect_duplicates.py."
        )


def offer_url(row: sqlite3.Row) -> str:
    return (
        row["source_url"]
        or row["application_url"]
        or "https://candidat.francetravail.fr/offres/recherche/detail/"
        + row["source_offer_id"]
    )


def salary_source(row: sqlite3.Row) -> str:
    parts = [row["salary_label_raw"], row["salary_comment_raw"]]
    return " — ".join(str(part).strip() for part in parts if part)


def csv_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def joined_reasons(value: Any) -> str:
    return " | ".join(translated_reasons(value))


def csv_record(capture_id: int, row: sqlite3.Row) -> dict[str, Any]:
    distance_km = (
        round(row["distance_meters"] / 1000, 1)
        if row["distance_meters"] is not None
        else None
    )
    return {
        "capture_id": capture_id,
        "id_offre": row["source_offer_id"],
        "groupe_quasi_doublon": row["duplicate_group_key"],
        "representant_quasi_doublon": row["duplicate_representative_id"],
        "similarite_avec_representant": (
            round(row["similarity_to_representative"], 3)
            if row["similarity_to_representative"] is not None
            else None
        ),
        "statut_mecanique": row["status"],
        "titre": row["title_normalized"],
        "entreprise": row["employer_name"] or "Non indiquée",
        "lieu": row["location_label"] or row["postal_code"] or "Non indiqué",
        "contrat": row["contract_label"] or row["contract_family"],
        "temps_travail": row["work_time_type"] or row["work_schedule_text"],
        "heures_hebdomadaires": row["weekly_hours"],
        "salaire_mensuel_min_eur": row["salary_monthly_gross_min"],
        "salaire_mensuel_max_eur": row["salary_monthly_gross_max"],
        "salaire_original": salary_source(row),
        "trajet_minutes": (
            row["duration_minutes"] if row["status"] != "EXCLUDE" else None
        ),
        "trajet_km": distance_km if row["status"] != "EXCLUDE" else None,
        "categorie_trajet": (
            "Non calculé (offre exclue)"
            if row["status"] == "EXCLUDE"
            else (
                TRAVEL_LABELS.get(row["travel_band"], row["travel_band"])
                if row["travel_band"]
                else "Non calculé"
            )
        ),
        "penalite_horaires": row["schedule_penalty"],
        "raisons_exclusion": joined_reasons(row["exclusion_reasons_json"]),
        "raisons_verification": joined_reasons(row["review_reasons_json"]),
        "avertissements": joined_reasons(row["warnings_json"]),
        "date_creation": row["created_at_utc"],
        "url_offre": offer_url(row),
    }


def write_csv(path: Path, capture_id: int, rows: list[sqlite3.Row]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: csv_safe(value) for key, value in csv_record(capture_id, row).items()}
            )


def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def format_number(value: Any, decimals: int = 0) -> str:
    if value is None:
        return ""
    formatted = f"{float(value):,.{decimals}f}"
    return formatted.replace(",", " ").replace(".", ",")


def salary_html(row: sqlite3.Row) -> str:
    minimum = row["salary_monthly_gross_min"]
    maximum = row["salary_monthly_gross_max"]
    if minimum is None or maximum is None:
        equivalent = "<strong>À vérifier</strong>"
    elif abs(float(minimum) - float(maximum)) < 0.01:
        equivalent = f"<strong>{format_number(minimum)} € brut/mois</strong>"
    else:
        equivalent = (
            f"<strong>{format_number(minimum)}–{format_number(maximum)} € "
            "brut/mois</strong>"
        )
    source = salary_source(row)
    return equivalent + (f"<small>{escape(source)}</small>" if source else "")


def travel_html(row: sqlite3.Row) -> str:
    if row["status"] == "EXCLUDE":
        return '<span class="muted">Non calculé (offre exclue)</span>'
    if row["travel_band"] is None:
        return '<span class="muted">Non calculé</span>'
    label = TRAVEL_LABELS.get(row["travel_band"], row["travel_band"])
    details: list[str] = []
    if row["duration_minutes"] is not None:
        details.append(f"{format_number(row['duration_minutes'], 1)} min")
    if row["distance_meters"] is not None:
        details.append(f"{format_number(row['distance_meters'] / 1000, 1)} km")
    result = f"<strong>{escape(label)}</strong>"
    if details:
        result += f"<small>{escape(' · '.join(details))}</small>"
    return result


def reasons_html(row: sqlite3.Row) -> str:
    groups = (
        ("Exclusion", translated_reasons(row["exclusion_reasons_json"])),
        ("Vérification", translated_reasons(row["review_reasons_json"])),
        ("Attention", translated_reasons(row["warnings_json"])),
    )
    parts = []
    for label, reasons in groups:
        if reasons:
            parts.append(
                f"<strong>{escape(label)} :</strong> {escape(' · '.join(reasons))}"
            )
    return "<br>".join(parts) or '<span class="muted">Aucun motif mécanique</span>'


def duplicate_html(row: sqlite3.Row) -> str:
    if not row["duplicate_group_key"]:
        return ""
    role = (
        "représentant"
        if row["source_offer_id"] == row["duplicate_representative_id"]
        else f"proche de {row['duplicate_representative_id']}"
    )
    return (
        '<small class="duplicate">Quasi-doublon · '
        f"{escape(row['duplicate_group_key'])} · {escape(role)} · "
        f"{row['duplicate_group_size']} offres</small>"
    )


def offer_row_html(row: sqlite3.Row) -> str:
    employer = row["employer_name"] or "Employeur non indiqué"
    location = row["location_label"] or row["postal_code"] or "Lieu non indiqué"
    contract = row["contract_label"] or row["contract_family"]
    work_time = row["work_time_type"] or "Temps de travail non indiqué"
    if row["weekly_hours"] is not None:
        work_time += f" · {format_number(row['weekly_hours'], 1)} h/semaine"
    url = escape(offer_url(row))
    return f"""
        <tr>
          <td><span class="status {escape(row['status'].lower())}">{escape(row['status'])}</span></td>
          <td><strong>{escape(row['title_normalized'])}</strong><small>{escape(row['source_offer_id'])}</small>{duplicate_html(row)}</td>
          <td>{escape(employer)}<small>{escape(location)}</small></td>
          <td>{escape(contract)}<small>{escape(work_time)}</small></td>
          <td>{salary_html(row)}</td>
          <td>{travel_html(row)}</td>
          <td>{reasons_html(row)}</td>
          <td><a href="{url}" target="_blank" rel="noopener noreferrer">Voir l’offre</a></td>
        </tr>"""


def summary_card(label: str, value: int, css_class: str = "") -> str:
    return (
        f'<div class="summary {escape(css_class)}"><span>{escape(label)}</span>'
        f"<strong>{value}</strong></div>"
    )


def build_html(
    capture: sqlite3.Row, rows: list[sqlite3.Row], generated_at: str
) -> str:
    status_counts = Counter(row["status"] for row in rows)
    travel_counts = Counter(
        row["travel_band"]
        for row in rows
        if row["status"] in {"KEEP", "REVIEW"}
        and row["travel_band"] is not None
    )
    origin = next((row["origin_label"] for row in rows if row["origin_label"]), None)
    provider = next((row["provider"] for row in rows if row["provider"]), None)
    traffic_profile = next(
        (row["traffic_profile"] for row in rows if row["traffic_profile"]), None
    )
    threshold = next(
        (row["salary_threshold_monthly"] for row in rows if row["salary_threshold_monthly"]),
        2500,
    )
    duplicate_groups = {
        row["duplicate_group_key"] for row in rows if row["duplicate_group_key"]
    }
    duplicate_members = sum(bool(row["duplicate_group_key"]) for row in rows)

    cards = "".join(
        (
            summary_card("Offres", len(rows)),
            summary_card("KEEP", status_counts["KEEP"], "keep"),
            summary_card("REVIEW", status_counts["REVIEW"], "review"),
            summary_card("EXCLUDE", status_counts["EXCLUDE"], "exclude"),
        )
    )
    travel_cards = "".join(
        (
            summary_card("≤ 35 min", travel_counts["LE_35"], "keep"),
            summary_card("35–60 min", travel_counts["BETWEEN_35_60"], "review"),
            summary_card("> 60 min", travel_counts["GT_60"], "exclude"),
            summary_card("Inconnu", travel_counts["UNKNOWN"]),
        )
    )

    sections = []
    for status in ("KEEP", "REVIEW", "EXCLUDE"):
        selected = [row for row in rows if row["status"] == status]
        body = "".join(offer_row_html(row) for row in selected)
        if not body:
            body = '<tr><td colspan="8" class="empty">Aucune offre.</td></tr>'
        sections.append(
            f"""
      <section>
        <h2>{escape(STATUS_SECTION_TITLES[status])} <span>{len(selected)}</span></h2>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Statut</th><th>Offre</th><th>Employeur / lieu</th>
              <th>Contrat</th><th>Salaire</th><th>Trajet</th>
              <th>Motifs</th><th>Lien</th>
            </tr></thead>
            <tbody>{body}</tbody>
          </table>
        </div>
      </section>"""
        )

    source_info = f"{capture['source']} · {capture['source_file']}"
    route_info = " · ".join(
        value for value in (origin, provider, traffic_profile) if value
    ) or "Aucun trajet disponible"
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Veille emploi IA — capture #{capture['id']}</title>
  <style>
    :root {{ color-scheme: light; --ink:#172033; --muted:#667085; --line:#e5e7eb;
      --blue:#2563eb; --green:#067647; --green-bg:#ecfdf3; --amber:#b54708;
      --amber-bg:#fffaeb; --red:#b42318; --red-bg:#fef3f2; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:#f6f7f9; color:var(--ink); font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
    main {{ max-width:1500px; margin:0 auto; padding:32px 24px 56px; }}
    header {{ margin-bottom:24px; }}
    h1 {{ margin:0 0 6px; font-size:30px; letter-spacing:-.02em; }}
    h2 {{ display:flex; align-items:center; gap:8px; margin:32px 0 12px; font-size:20px; }}
    h2 span {{ min-width:28px; padding:2px 8px; border-radius:999px; background:#e8ecf3; text-align:center; font-size:13px; }}
    p {{ margin:5px 0; }} .muted, small {{ color:var(--muted); }}
    .notice {{ margin:20px 0; padding:14px 16px; border-left:4px solid var(--blue); border-radius:8px; background:#eff6ff; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(130px,1fr)); gap:12px; margin:12px 0; }}
    .summary {{ padding:14px 16px; border:1px solid var(--line); border-radius:10px; background:white; }}
    .summary span {{ display:block; color:var(--muted); font-size:12px; font-weight:650; text-transform:uppercase; letter-spacing:.04em; }}
    .summary strong {{ display:block; margin-top:3px; font-size:25px; }}
    .summary.keep {{ background:var(--green-bg); }} .summary.review {{ background:var(--amber-bg); }}
    .summary.exclude {{ background:var(--red-bg); }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:white; }}
    table {{ width:100%; min-width:1250px; border-collapse:collapse; }}
    th,td {{ padding:12px 11px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ position:sticky; top:0; background:#f9fafb; color:#475467; font-size:12px; text-transform:uppercase; letter-spacing:.03em; }}
    tbody tr:last-child td {{ border-bottom:0; }} tbody tr:hover {{ background:#fafcff; }}
    td small {{ display:block; margin-top:4px; }}
    .status {{ display:inline-block; padding:4px 7px; border-radius:999px; font-size:11px; font-weight:750; }}
    .status.keep {{ color:var(--green); background:var(--green-bg); }}
    .status.review {{ color:var(--amber); background:var(--amber-bg); }}
    .status.exclude {{ color:var(--red); background:var(--red-bg); }}
    .duplicate {{ color:#6941c6; font-weight:650; }}
    a {{ color:var(--blue); font-weight:650; white-space:nowrap; }} .empty {{ text-align:center; color:var(--muted); }}
    footer {{ margin-top:30px; color:var(--muted); font-size:12px; }}
    @media (max-width:760px) {{ main {{ padding:22px 14px 40px; }} .grid {{ grid-template-columns:repeat(2,1fr); }} h1 {{ font-size:25px; }} }}
  </style>
</head>
<body><main>
  <header>
    <h1>Veille emploi IA</h1>
    <p>Rapport France Travail · capture #{capture['id']} · {escape(capture['captured_at_utc'])}</p>
    <p class="muted">{escape(source_info)}</p>
  </header>
  <div class="notice"><strong>Lecture mécanique, pas verdict final.</strong>
    KEEP / REVIEW / EXCLUDE proviennent des filtres validés. Ce rapport ne signifie pas qu’une candidature a été envoyée.</div>
  <h2>Synthèse des filtres</h2><div class="grid">{cards}</div>
  <p class="muted">Quasi-doublons : {len(duplicate_groups)} groupe(s), {duplicate_members} offre(s) annotée(s). Aucune offre supprimée.</p>
  <h2>Trajets des offres KEEP / REVIEW</h2><div class="grid">{travel_cards}</div>
  <p class="muted">Origine et profil : {escape(route_info)}. Seuil salarial : {format_number(threshold)} € brut/mois.</p>
  {''.join(sections)}
  <footer>Rapport généré le {escape(generated_at)}. Source en lecture seule : SQLite locale.</footer>
</main></body></html>
"""


def main() -> int:
    args = parse_args()
    database_path = args.database.resolve()
    if not database_path.is_file():
        print(f"Rapport impossible : base introuvable : {database_path}", file=sys.stderr)
        return 1

    try:
        connection_uri = database_path.as_uri() + "?mode=ro"
        with sqlite3.connect(connection_uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            check_database(connection)
            capture = select_capture(connection, args.capture_id)
            check_duplicate_run(connection, int(capture["id"]))
            rows = select_offers(connection, int(capture["id"]))

        html_dir = args.html_dir.resolve()
        csv_dir = args.csv_dir.resolve()
        html_dir.mkdir(parents=True, exist_ok=True)
        csv_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        generated_at = now.isoformat()
        stem = f"rapport_capture_{capture['id']}_{now.strftime('%Y-%m-%d_%H%M%SZ')}"
        html_path = html_dir / f"{stem}.html"
        csv_path = csv_dir / f"{stem}.csv"

        write_csv(csv_path, int(capture["id"]), rows)
        html_path.write_text(
            build_html(capture, rows, generated_at), encoding="utf-8", newline=""
        )
    except (OSError, ReportError, sqlite3.Error) as exc:
        print(f"Rapport impossible : {exc}", file=sys.stderr)
        return 1

    counts = Counter(row["status"] for row in rows)
    print(f"Rapports générés : capture #{capture['id']} — {len(rows)} offre(s).")
    print(
        f"KEEP : {counts['KEEP']} · REVIEW : {counts['REVIEW']} · "
        f"EXCLUDE : {counts['EXCLUDE']}"
    )
    print(f"HTML : {html_path}")
    print(f"CSV : {csv_path}")
    print("Aucun filtre, trajet, verdict final ou statut de candidature n'a été modifié.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
