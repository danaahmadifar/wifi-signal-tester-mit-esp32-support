"""
WLAN Signal-Tester - Datenmodelle und Bewertungsmetriken (core/datenmodelle.py)
Definiert Datenstrukturen fuer Signalmessungen, Netzwerkdiagnosen und Bewertungsfunktionen.
"""

from dataclasses import dataclass


# Farbwerte fuer 802.11 Modulationsschemata: (Hintergrund, Rahmen, Text)
MODULATION_FARBEN = {
    "1024-QAM": ("#1e1329", "#9333ea", "#e9d5ff"),  # 802.11ax (10 Bit/Symbol)
    "256-QAM":  ("#1e1329", "#7c3aed", "#c4b5fd"),  # 802.11ac/ax (8 Bit/Symbol)
    "64-QAM":   ("#1e1329", "#6366f1", "#c7d2fe"),  # 802.11n/ac (6 Bit/Symbol)
    "16-QAM":   ("#272108", "#ca8a04", "#fde047"),  # 802.11a/g/n (4 Bit/Symbol)
    "QPSK":     ("#0b2034", "#0284c7", "#7dd3fc"),  # 802.11a/g/n (2 Bit/Symbol)
    "BPSK":     ("#261608", "#ea580c", "#fdba74"),  # 802.11a/g/n (1 Bit/Symbol)
}

# 5-stufige Farbskala fuer Signalpegel und Heatmap-Darstellung
HEATMAP_FARBEN = [
    {"grenze": -80.0, "farbe": "#dc2626", "name": "Kritisch (< -80 dBm)"},
    {"grenze": -70.0, "farbe": "#f97316", "name": "Schwach (-80 bis -70 dBm)"},
    {"grenze": -60.0, "farbe": "#eab308", "name": "Ausreichend (-70 bis -60 dBm)"},
    {"grenze": -50.0, "farbe": "#84cc16", "name": "Gut (-60 bis -50 dBm)"},
    {"grenze": 0.0,   "farbe": "#16a34a", "name": "Sehr gut (> -50 dBm)"}
]


@dataclass
class SignalMessung:
    """Datensatz einer einzelnen Signalmessung."""
    zeitstempel_ms: int = 0
    ziel_ssid: str = "Unbekannt"
    bssid: str = "--"
    kanal: int = 1
    rssi: float = -100.0
    modulation: str = "N/A"
    phy_standard: str = "802.11"
    mcs_index: int = 0
    noise_floor: float = -95.0
    snr_db: float = 0.0
    retry_rate_pct: float = 0.0


@dataclass
class DiagnoseErgebnis:
    """Ergebnis des Verbindungs-, DHCP-, DNS- und Ping-Benchmarks."""
    verbindung_erfolgreich: bool = False
    verbindungsdauer_ms: int = 0
    lokale_ip: str = "--"
    gateway_ip: str = "--"
    subnetz_maske: str = "--"
    dns_server: str = "--"
    dns_ok: bool = False
    dns_latenz_ms: float = 0.0
    gateway_ping_ms: float = 0.0
    internet_ping_ms: float = 0.0
    internet_ziel: str = "1.1.1.1"
    status_nachricht: str = ""


def berechne_signal_qualitaet(rssi: float) -> tuple[str, str, float]:
    """
    Bewertet den Signalpegel (dBm).
    Rueckgabe: (Farbcode, Textbeschreibung, Prozentwert 0-100)
    """
    if rssi <= -95.0:
        return "#ef4444", "Kritisch / Kein Signal", 0.0
    if rssi >= -40.0:
        return "#22c55e", "Ausgezeichnet", 100.0

    prozent = max(0.0, min(100.0, ((rssi - (-95.0)) / 55.0) * 100.0))
    if rssi > -60.0:
        return "#22c55e", "Sehr gut", prozent
    elif rssi > -70.0:
        return "#eab308", "Gut / Stabil", prozent
    elif rssi > -80.0:
        return "#f97316", "Gedaempft", prozent
    else:
        return "#ef4444", "Schwach", prozent


def berechne_snr_qualitaet(snr: float) -> tuple[str, str]:
    """
    Bewertet den Signal-Rausch-Abstand (SNR in dB).
    Rueckgabe: (Farbcode, Textbeschreibung)
    """
    if snr >= 25.0:
        return "#22c55e", "Sehr gut (>= 25 dB)"
    elif snr >= 15.0:
        return "#eab308", "Gut (15-25 dB)"
    elif snr >= 10.0:
        return "#f97316", "Mäßig (10-15 dB)"
    else:
        return "#ef4444", "Schwach (< 10 dB)"


def berechne_retry_qualitaet(retry_rate: float) -> tuple[str, str]:
    """
    Bewertet die Paket-Wiederholungsrate (%).
    Rueckgabe: (Farbcode, Textbeschreibung)
    """
    if retry_rate <= 5.0:
        return "#22c55e", "Optimal (< 5%)"
    elif retry_rate <= 12.0:
        return "#eab308", "Normal (5-12%)"
    elif retry_rate <= 20.0:
        return "#f97316", "Erhöht (12-20%)"
    else:
        return "#ef4444", "Kritisch (> 20%)"
