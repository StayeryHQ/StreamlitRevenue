# dash_app/pages/home.py
# Landing page: snapshot freshness + headline KPIs, navigation cards into the
# Revenue / Sales hubs and the System pages, plus the Standort-Verwaltung (read
# the locations.yaml table and generate a paste-ready YAML snippet for a new
# hotel). Port of the previous app Reads the parquet snapshot via
# dash_app.backend.data - never BigQuery. IDs: home-.

from __future__ import annotations

import dash
import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, callback, dcc, html

from dash_app.backend import data
from dash_app.components import ui
from revenueblindspots import helpers as H

dash.register_page(__name__, path="/", name="Home", order=0,
                   title="STAYERY · Revenue Analytics")

# ISO-3166-2 Bundesland codes (same set as configs/locations.yaml header).
_BL_OPTIONS = [
    {"value": "BE", "label": "BE · Berlin"},
    {"value": "BW", "label": "BW · Baden-Württemberg"},
    {"value": "BY", "label": "BY · Bayern"},
    {"value": "HB", "label": "HB · Bremen"},
    {"value": "HE", "label": "HE · Hessen"},
    {"value": "HH", "label": "HH · Hamburg"},
    {"value": "MV", "label": "MV · Mecklenburg-Vorpommern"},
    {"value": "NI", "label": "NI · Niedersachsen"},
    {"value": "NW", "label": "NW · Nordrhein-Westfalen"},
    {"value": "RP", "label": "RP · Rheinland-Pfalz"},
    {"value": "SH", "label": "SH · Schleswig-Holstein"},
    {"value": "SL", "label": "SL · Saarland"},
    {"value": "SN", "label": "SN · Sachsen"},
    {"value": "ST", "label": "ST · Sachsen-Anhalt"},
    {"value": "TH", "label": "TH · Thüringen"},
    {"value": "BB", "label": "BB · Brandenburg"},
]

# (icon, title, one-line desc, href) - grouped into Revenue / Sales / System.
_REVENUE_CARDS = [
    ("bi bi-bar-chart", "Global Report",
     "Standortübergreifender Recap: IST vs. PLAN vs. Vorjahr, Auto-Alerts, Heatmaps.",
     "/revenue?tab=global"),
    ("bi bi-graph-up-arrow", "Pickup / Vorlauf",
     "Stay × Creation: Pace by Month, Pickup-Anteil, Buchungskurve, YoY-Vorlauf.",
     "/revenue?tab=pickup"),
    ("bi bi-geo-alt", "Standort-Analyse",
     "Einzelstandort-Deep-Dive: KPIs, Channel-Mix, LOS, Wochentag, Herkunft.",
     "/revenue?tab=standort"),
]
_SALES_CARDS = [
    ("bi bi-building", "B2B Deep-Dive",
     "Firmenkunden & Vertragscodes über die Historie (fuzzy-geclustert), Excel-Export.",
     "/sales?tab=b2b"),
    ("bi bi-search", "Code Deep-Dive",
     "Eine Firma im 360°-Blick: Revenue-Verlauf, Channel-Mix, Stay-Pattern, Pipeline.",
     "/sales?tab=code"),
    ("bi bi-tags", "Promo-Codes",
     "Alle Promo-Codes mit Firmencode-Verdacht + Reklassifizierung zu Vertragscodes.",
     "/sales?tab=promo"),
]
_SYSTEM_CARDS = [
    ("bi bi-arrow-repeat", "Daten aktualisieren",
     "Snapshot + Planzahlen aus BigQuery ziehen. Voraussetzung für alle Analysen.",
     "/daten"),
    ("bi bi-book", "Dokumentation",
     "Datenbasis, Revenue-Logik, Filter, Channels und B2B - alle Kapitel.",
     "/doku"),
]


def _link_card(icon: str, title: str, desc: str, href: str):
    return dcc.Link(
        dmc.Card([
            dmc.Group([
                dmc.ThemeIcon(html.I(className=icon), size=38, radius="md",
                              variant="light", color="yellow"),
                dmc.Text(title, fw=700, size="md"),
            ], gap="sm", align="center"),
            dmc.Text(desc, c="dimmed", size="sm", mt="sm",
                     style={"minHeight": "3.4rem"}),
            dmc.Group([
                dmc.Text("Öffnen", size="sm", fw=600),
                html.I(className="bi bi-arrow-right"),
            ], gap=6, align="center"),
        ], withBorder=True, radius="lg", p="lg", shadow="xs",
            style={"height": "100%"}),
        href=href, style={"textDecoration": "none", "color": "inherit"})


def _card_group(label: str, cards: list):
    return dmc.Stack([
        dmc.Text(label, tt="uppercase", fw=700, size="xs", c="dimmed"),
        dmc.SimpleGrid([_link_card(*c) for c in cards],
                       cols={"base": 1, "sm": 2, "lg": 3}, spacing="md"),
    ], gap="xs")


def _kpi_row(meta: dict):
    refreshed = str(meta.get("refreshed_at", "?"))[:19].replace("T", " ")
    n_res = int(meta.get("reservations", {}).get("rows", 0) or 0)
    n_nig = int(meta.get("timeslices", {}).get("rows", 0) or 0)
    n_props = len(meta.get("properties", []) or [])
    return ui.kpi_strip([
        ui.kpi_card("Letzter Refresh", refreshed, accent=True,
                    tooltip="Zeitpunkt des letzten BigQuery-Snapshots (Europe/Berlin)."),
        ui.kpi_card("Reservierungen", f"{n_res:,}".replace(",", "."),
                    tooltip="Zeilen im reservations.parquet (eine je Buchung)."),
        ui.kpi_card("Übernachtungen", f"{n_nig:,}".replace(",", "."),
                    tooltip="Zeilen im timeslices.parquet (eine je genutzte Nacht)."),
        ui.kpi_card("Standorte", str(n_props),
                    tooltip="Anzahl Hotels im aktuellen Snapshot."),
    ])


def _locations_df() -> pd.DataFrame:
    rows = [{
        "Code": loc["hotel_code"],
        "Stadt": loc.get("city", ""),
        "Neighborhood": loc.get("neighborhood") or "-",
        "Bundesland": loc.get("bundesland", ""),
        "Units": loc.get("units_total", 0),
        "Eröffnet": str(loc.get("opening_date") or "TBD"),
    } for loc in H._locations()]
    return pd.DataFrame(rows)


def _add_location_form():
    inputs = dmc.SimpleGrid([
        dmc.TextInput(id="home-loc-code", label="Hotel-Code (6 Zeichen)",
                      placeholder="z.B. FTH_HA",
                      leftSection=html.I(className="bi bi-hash")),
        dmc.TextInput(id="home-loc-city", label="Stadt", placeholder="z.B. Fürth",
                      leftSection=html.I(className="bi bi-geo-alt")),
        dmc.TextInput(id="home-loc-neigh", label="Neighborhood (optional)",
                      placeholder="z.B. Innenstadt"),
        dmc.Select(id="home-loc-bl", label="Bundesland", data=_BL_OPTIONS,
                   value="BY", searchable=True,
                   comboboxProps={"withinPortal": True}),
        dmc.NumberInput(id="home-loc-units", label="Units (Apartments)",
                        value=60, min=1, max=999, step=1),
        dmc.DatePickerInput(id="home-loc-open", label="Eröffnungsdatum (leer = TBD)",
                            valueFormat="DD.MM.YYYY", clearable=True,
                            popoverProps={"withinPortal": True}),
    ], cols={"base": 1, "sm": 2, "md": 3}, spacing="md")

    body = dmc.Stack([
        dmc.Text("Felder ausfüllen - unten erscheint das YAML-Snippet zum Kopieren in "
                 "configs/locations.yaml. Danach einmal Daten aktualisieren ausführen, "
                 "damit BigQuery den neuen Code mitzieht. Diese Seite schreibt nichts.",
                 size="sm", c="dimmed"),
        inputs,
        html.Div(id="home-snippet"),
    ], gap="sm")

    return dmc.Accordion([
        dmc.AccordionItem([
            dmc.AccordionControl("Neuen Standort hinzufügen",
                                 icon=html.I(className="bi bi-plus-circle")),
            dmc.AccordionPanel(body),
        ], value="add")
    ], variant="contained", radius="md", chevronPosition="left")


def layout(**_kwargs):
    meta = data.get_metadata()

    hero = dmc.Stack([
        dmc.Group([
            dmc.Title("Revenue & Sales Analytics", order=2),
            dmc.Badge("Self-Service", color="yellow", variant="light", radius="sm"),
        ], gap="sm", align="center"),
        ui.freshness_badge(meta),
    ], gap="xs")

    if meta:
        earliest = str(meta.get("reservations", {}).get("earliest", "?"))[:10]
        latest = str(meta.get("reservations", {}).get("latest", "?"))[:10]
        status = dmc.Stack([
            _kpi_row(meta),
            dmc.Text(f"Anreise-Range: {earliest} bis {latest}", size="xs", c="dimmed"),
        ], gap="xs")
    else:
        status = ui.alert(
            "Kein Snapshot gefunden. Bitte einmal die Daten-Seite aufrufen und einen "
            "Refresh starten - bis dahin können die Analyse-Seiten keine Daten laden.",
            "warning", title="Kein Datenstand")

    nav = dmc.Stack([
        _card_group("Revenue", _REVENUE_CARDS),
        _card_group("Sales", _SALES_CARDS),
        _card_group("System", _SYSTEM_CARDS),
    ], gap="lg")

    loc_section = dmc.Stack([
        dmc.Title("Standorte", order=4),
        dmc.Text("Hotel-Metadaten (Stadt, Units, Bundesland, Eröffnung) liegen in "
                 "configs/locations.yaml.", size="sm", c="dimmed"),
        ui.df_grid(_locations_df(), "home-loc-grid", height=320),
        _add_location_form(),
    ], gap="sm")

    return dmc.Stack([
        hero,
        status,
        dmc.Divider(my="xs"),
        nav,
        dmc.Divider(my="xs"),
        loc_section,
    ], gap="md")


# ---------------------------------------------------------------------------
# YAML-Snippet generator: pure convenience, writes nothing. Fires live on every
# field change; a code-exists check warns before generating a duplicate.
# ---------------------------------------------------------------------------
@callback(
    Output("home-snippet", "children"),
    Input("home-loc-code", "value"),
    Input("home-loc-city", "value"),
    Input("home-loc-neigh", "value"),
    Input("home-loc-bl", "value"),
    Input("home-loc-units", "value"),
    Input("home-loc-open", "value"),
)
def _snippet(code, city, neigh, bl, units, open_date):
    code = (code or "").strip().upper()
    city = (city or "").strip()
    if not code or not city:
        return dmc.Text("Hotel-Code und Stadt ausfüllen, dann erscheint hier das Snippet.",
                        size="sm", c="dimmed")

    existing = {loc["hotel_code"] for loc in H._locations()}
    if code in existing:
        return ui.alert(f"Code {code} existiert bereits in configs/locations.yaml.",
                        "warning", title="Code schon vorhanden")

    neigh = (neigh or "").strip()
    neigh_line = f"    neighborhood: {neigh}" if neigh else "    neighborhood: null"
    if open_date:
        open_line = f"    opening_date: {str(open_date)[:10]}"
    else:
        open_line = "    opening_date: null   # TBD"
    snippet = (
        f"  - hotel_code: {code}\n"
        f"    city: {city}\n"
        f"{neigh_line}\n"
        f"    bundesland: {bl}\n"
        f"{open_line}\n"
        f"    units_total: {int(units or 0)}\n"
        f'    notes: ""\n'
    )
    return dmc.Stack([
        dmc.Text("YAML-Snippet - kopieren und ans Ende von locations: einfügen:",
                 size="sm", fw=600),
        dmc.CodeHighlight(code=snippet, language="yaml"),
        dmc.Text("Danach Daten aktualisieren ausführen, damit der neue Code aus BigQuery "
                 "gezogen wird.", size="xs", c="dimmed"),
    ], gap="xs")
