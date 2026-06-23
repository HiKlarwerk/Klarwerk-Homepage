#!/usr/bin/env python3
"""
preismonitor.py
================
Automatische Wettbewerbsbeobachtung: liest die Produktliste einer Shopseite aus,
vergleicht sie mit dem letzten gespeicherten Stand und meldet, was sich geändert hat
(neue Produkte, ausgelistete Produkte, Preiserhöhungen, Preissenkungen).

Gedacht zum regelmäßigen Ausführen (z.B. 1x pro Woche per Cronjob / Task Scheduler) –
dann läuft die Beobachtung im Hintergrund und man bekommt nur die Veränderungen
als Report, statt selbst jede Woche manuell auf der Konkurrenzseite nachzuschauen.

ANPASSUNG FÜR ECHTEN EINSATZ:
- QUELLE auf die echte Shop-URL setzen (z.B. "https://www.beispiel-shop.de/sortiment")
- Die drei CSS-Selektoren unten an die HTML-Struktur der Zielseite anpassen
  (jede Seite ist anders aufgebaut – das ist der Teil, der pro Kunde individuell ist)

© 2026 Marcel Schorb (Klarwerk) — Demo-/Portfolio-Code, nicht zur freien
Weiterverwendung oder Veröffentlichung bestimmt. Kontakt: kontakt.klarwerk@gmail.com
"""

import csv
import sys
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# KONFIGURATION – das ist der Teil, der pro Kunde/Zielseite angepasst wird
# ---------------------------------------------------------------------------
CONFIG = {
    "quelle_name": "OutdoorBasis Shop",
    # Für die Demo: lokale HTML-Datei. Im Echtbetrieb hier die Shop-URL eintragen,
    # z.B. "https://www.konkurrenz-shop.de/outdoor-ausruestung"
    "quelle": None,  # wird beim Aufruf übergeben
    "produkt_selector": "div.product",
    "name_selector": "h3.name",
    "preis_selector": "span.price",
}

SNAPSHOT_ORDNER = Path(__file__).parent / "snapshots"
REPORT_ORDNER = Path(__file__).parent / "reports"


def html_laden(quelle: str) -> str:
    """Lädt HTML entweder von einer URL oder einer lokalen Datei."""
    if quelle.startswith("http://") or quelle.startswith("https://"):
        antwort = requests.get(quelle, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        antwort.raise_for_status()
        return antwort.text
    return Path(quelle).read_text(encoding="utf-8")


def preis_parsen(text: str) -> float:
    """Wandelt '79,99 €' in 79.99 um."""
    bereinigt = text.replace("€", "").replace(".", "").replace(",", ".").strip()
    return round(float(bereinigt), 2)


def produkte_extrahieren(html: str) -> dict:
    """Extrahiert {produktname: preis} aus dem HTML anhand der konfigurierten Selektoren."""
    soup = BeautifulSoup(html, "html.parser")
    produkte = {}
    for block in soup.select(CONFIG["produkt_selector"]):
        name_tag = block.select_one(CONFIG["name_selector"])
        preis_tag = block.select_one(CONFIG["preis_selector"])
        if not name_tag or not preis_tag:
            continue
        name = name_tag.get_text(strip=True)
        preis = preis_parsen(preis_tag.get_text())
        produkte[name] = preis
    return produkte


def letzten_snapshot_laden() -> dict | None:
    """Gibt den zuletzt gespeicherten Snapshot zurück (oder None, falls es noch keinen gibt)."""
    dateien = sorted(SNAPSHOT_ORDNER.glob("snapshot_*.csv"))
    if not dateien:
        return None
    letzte_datei = dateien[-1]
    produkte = {}
    with letzte_datei.open(encoding="utf-8") as f:
        for zeile in csv.DictReader(f):
            produkte[zeile["name"]] = float(zeile["preis"])
    return produkte


def snapshot_speichern(produkte: dict, label: str) -> Path:
    SNAPSHOT_ORDNER.mkdir(exist_ok=True)
    pfad = SNAPSHOT_ORDNER / f"snapshot_{label}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "preis"])
        for name, preis in produkte.items():
            writer.writerow([name, preis])
    return pfad


def vergleichen(aktuell: dict, vorherig: dict | None) -> dict:
    if vorherig is None:
        return {"erstlauf": True, "anzahl": len(aktuell)}

    neu = [n for n in aktuell if n not in vorherig]
    entfernt = [n for n in vorherig if n not in aktuell]
    erhoeht, gesenkt, unveraendert = [], [], []

    for name, preis in aktuell.items():
        if name not in vorherig:
            continue
        alt = vorherig[name]
        if preis > alt:
            erhoeht.append((name, alt, preis))
        elif preis < alt:
            gesenkt.append((name, alt, preis))
        else:
            unveraendert.append(name)

    return {
        "erstlauf": False,
        "neu": neu,
        "entfernt": entfernt,
        "erhoeht": erhoeht,
        "gesenkt": gesenkt,
        "unveraendert": unveraendert,
    }


def report_text(vergleich: dict, quelle_name: str, label: str) -> str:
    zeilen = [f"Preisüberwachung · {quelle_name} · {label}", "=" * 50]

    if vergleich["erstlauf"]:
        zeilen.append(f"Erste Erfassung: {vergleich['anzahl']} Produkte als Ausgangsstand gespeichert.")
        return "\n".join(zeilen)

    if vergleich["gesenkt"]:
        zeilen.append("\nPREISSENKUNGEN:")
        for name, alt, neu in vergleich["gesenkt"]:
            zeilen.append(f"  ↓ {name}: {alt:.2f} € → {neu:.2f} € ({neu-alt:+.2f} €)")

    if vergleich["erhoeht"]:
        zeilen.append("\nPREISERHÖHUNGEN:")
        for name, alt, neu in vergleich["erhoeht"]:
            zeilen.append(f"  ↑ {name}: {alt:.2f} € → {neu:.2f} € ({neu-alt:+.2f} €)")

    if vergleich["neu"]:
        zeilen.append("\nNEUE PRODUKTE:")
        for name in vergleich["neu"]:
            zeilen.append(f"  + {name}")

    if vergleich["entfernt"]:
        zeilen.append("\nAUSGELISTETE PRODUKTE:")
        for name in vergleich["entfernt"]:
            zeilen.append(f"  − {name}")

    zeilen.append(f"\nUnverändert: {len(vergleich['unveraendert'])} Produkte.")
    return "\n".join(zeilen)


def report_html(vergleich: dict, quelle_name: str, label: str) -> str:
    def zeile(symbol, text, farbe):
        return f'<li style="color:{farbe};margin:4px 0;">{symbol} {text}</li>'

    body = ""
    if vergleich["erstlauf"]:
        body = f"<p>Erste Erfassung: <b>{vergleich['anzahl']}</b> Produkte als Ausgangsstand gespeichert.</p>"
    else:
        if vergleich["gesenkt"]:
            items = "".join(zeile("↓", f"{n}: {a:.2f}&nbsp;€ → {p:.2f}&nbsp;€", "#3F7A4A") for n, a, p in vergleich["gesenkt"])
            body += f"<h3>Preissenkungen</h3><ul>{items}</ul>"
        if vergleich["erhoeht"]:
            items = "".join(zeile("↑", f"{n}: {a:.2f}&nbsp;€ → {p:.2f}&nbsp;€", "#B6543C") for n, a, p in vergleich["erhoeht"])
            body += f"<h3>Preiserhöhungen</h3><ul>{items}</ul>"
        if vergleich["neu"]:
            items = "".join(zeile("+", n, "#2B6CB0") for n in vergleich["neu"])
            body += f"<h3>Neue Produkte</h3><ul>{items}</ul>"
        if vergleich["entfernt"]:
            items = "".join(zeile("−", n, "#7A6C60") for n in vergleich["entfernt"])
            body += f"<h3>Ausgelistete Produkte</h3><ul>{items}</ul>"
        body += f"<p style='color:#7A6C60;font-size:13px;'>Unverändert: {len(vergleich['unveraendert'])} Produkte.</p>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Preisreport {label}</title></head>
<body style="font-family:Arial,sans-serif;max-width:560px;margin:30px auto;color:#2A211C;">
<h2 style="margin-bottom:0;">Preisüberwachung</h2>
<p style="color:#7A6C60;margin-top:4px;">{quelle_name} · {label}</p>
<hr style="border:none;border-top:1px solid #eee;">
{body}
</body></html>"""


def main(quelle: str, label: str | None = None):
    label = label or datetime.now().strftime("%Y-%m-%d_%H%M")
    CONFIG["quelle"] = quelle

    html = html_laden(quelle)
    aktuell = produkte_extrahieren(html)
    vorherig = letzten_snapshot_laden()
    vergleich = vergleichen(aktuell, vorherig)

    print(report_text(vergleich, CONFIG["quelle_name"], label))

    REPORT_ORDNER.mkdir(exist_ok=True)
    report_pfad = REPORT_ORDNER / f"report_{label}.html"
    report_pfad.write_text(report_html(vergleich, CONFIG["quelle_name"], label), encoding="utf-8")
    print(f"\n[HTML-Report gespeichert: {report_pfad}]")

    snapshot_speichern(aktuell, label)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Nutzung: python3 preismonitor.py <quelle (Datei oder URL)> [label]")
        sys.exit(1)
    quelle_arg = sys.argv[1]
    label_arg = sys.argv[2] if len(sys.argv) > 2 else None
    main(quelle_arg, label_arg)
