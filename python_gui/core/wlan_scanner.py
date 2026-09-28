"""
WLAN Signal-Tester - WLAN Scanner (core/wlan_scanner.py)
Erfasst Signalstaerke und verfuegbare WLAN-Netze ueber die Windows-WLAN-Schnittstelle (netsh).
"""

import subprocess
import re
import time
from PyQt6.QtCore import QThread, pyqtSignal


def _fuehre_netsh_aus(argumente: list[str], timeout: float = 3.0) -> str:
    """Fuehrt einen netsh-Befehl verdeckt im Hintergrund aus."""
    try:
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        ergebnis = subprocess.run(
            ["netsh", "wlan"] + argumente,
            capture_output=True,
            text=True,
            startupinfo=info,
            timeout=timeout
        )
        return ergebnis.stdout if ergebnis.returncode == 0 else ""
    except Exception:
        return ""


def lese_wlan_netzwerke() -> list[dict]:
    """Liest alle sichtbaren WLAN-Netzwerke und deren BSSIDs aus."""
    ausgabe = _fuehre_netsh_aus(["show", "networks", "mode=bssid"], timeout=3.5)
    if not ausgabe:
        return []

    netzwerke = []
    aktuelle_ssid = ""
    aktueller_eintrag = None

    for zeile in ausgabe.splitlines():
        z = zeile.strip()
        if not z:
            continue

        # SSID-Zeile
        m_ssid = re.match(r"^SSID\s+\d+\s*:\s*(.*)$", z, re.IGNORECASE)
        if m_ssid:
            aktuelle_ssid = m_ssid.group(1).strip() or "<Verstecktes Netz>"
            aktueller_eintrag = None
            continue

        # BSSID-Zeile
        m_bssid = re.match(r"^BSSID\s+\d+\s*:\s*([0-9a-fA-F:-]+)", z, re.IGNORECASE)
        if m_bssid:
            aktueller_eintrag = {
                "ssid": aktuelle_ssid,
                "bssid": m_bssid.group(1).upper(),
                "signal_pct": 50,
                "rssi": -75.0,
                "channel": 1,
                "band": "2.4 GHz",
                "phy": "802.11n",
                "mod": "QPSK (MCS 2)"
            }
            netzwerke.append(aktueller_eintrag)
            continue

        if not aktueller_eintrag:
            continue

        # Signal in Prozent -> RSSI umrechnen
        m_sig = re.match(r"^Signal\s*:\s*(\d+)%", z, re.IGNORECASE)
        if m_sig:
            pct = int(m_sig.group(1))
            aktueller_eintrag["signal_pct"] = pct
            aktueller_eintrag["rssi"] = round((pct / 2.0) - 100.0, 1)

        # Funkkanal
        m_ch = re.match(r"^(?:Kanal|Channel)\s*:\s*(\d+)", z, re.IGNORECASE)
        if m_ch:
            ch = int(m_ch.group(1))
            aktueller_eintrag["channel"] = ch
            if ch > 14:
                aktueller_eintrag["band"] = "5 GHz"

        # Funktyp (PHY & Modulation abschaetzen)
        m_phy = re.match(r"^(?:Funktyp|Radio type)\s*:\s*(.*)$", z, re.IGNORECASE)
        if m_phy:
            phy = m_phy.group(1).strip()
            aktueller_eintrag["phy"] = phy
            pct = aktueller_eintrag.get("signal_pct", 50)
            if "ax" in phy.lower() or "be" in phy.lower():
                aktueller_eintrag["mod"] = "1024-QAM" if pct > 75 else "256-QAM"
            elif "ac" in phy.lower():
                aktueller_eintrag["mod"] = "256-QAM" if pct > 70 else "64-QAM"
            else:
                aktueller_eintrag["mod"] = "64-QAM" if pct > 60 else "QPSK"

    return netzwerke


def lese_aktuelle_schnittstelle() -> dict:
    """Liest den aktuellen Verbindungsstatus der internen WLAN-Karte."""
    ausgabe = _fuehre_netsh_aus(["show", "interfaces"], timeout=2.0)
    daten = {}
    for zeile in ausgabe.splitlines():
        if ":" in zeile:
            k, v = zeile.split(":", 1)
            daten[k.strip().lower()] = v.strip()
    return daten


class NetzwerkScanThread(QThread):
    """Scannt im Hintergrund einmalig sichtbare Netzwerke."""
    netzwerke_gefunden = pyqtSignal(list)

    def run(self):
        netze = lese_wlan_netzwerke()
        if netze:
            self.netzwerke_gefunden.emit(netze)


class WlanScanner(QThread):
    """Liest kontinuierlich die Signalwerte der internen WLAN-Karte aus."""
    daten_empfangen = pyqtSignal(dict)
    netzwerke_gefunden = pyqtSignal(list)
    verbindung_geandert = pyqtSignal(bool, str)
    fehler_aufgetreten = pyqtSignal(str)

    def __init__(self, eltern=None):
        super().__init__(eltern)
        self.laeuft = False
        self.ziel_ssid = ""
        self.ziel_bssid = ""
        self.abfrage_intervall = 0.5
        self.letzter_umgebungs_scan = 0.0

    def setze_ziel(self, ssid: str, bssid: str = ""):
        self.ziel_ssid = ssid.strip()
        self.ziel_bssid = bssid.strip().upper()

    def stoppen(self):
        self.laeuft = False
        self.wait(1500)

    def run(self):
        self.laeuft = True
        self.verbindung_geandert.emit(True, "Interne Wi-Fi-Karte aktiv")

        while self.laeuft:
            try:
                jetzt = time.time()
                passendes_netz = None

                # 1. Aktive Verbindung pruefen
                status_daten = lese_aktuelle_schnittstelle()
                status = status_daten.get("state", status_daten.get("status", "")).lower()
                verbundene_ssid = status_daten.get("ssid", "")
                verbundene_bssid = status_daten.get("ap bssid", status_daten.get("bssid", "--")).upper()

                treffer = False
                if not self.ziel_ssid:
                    treffer = True
                elif verbundene_ssid.lower() == self.ziel_ssid.lower():
                    if not self.ziel_bssid or verbundene_bssid == self.ziel_bssid:
                        treffer = True

                if status == "connected" and treffer and verbundene_ssid:
                    sig_str = status_daten.get("signal", "50%").replace("%", "").strip()
                    sig_pct = int(sig_str) if sig_str.isdigit() else 50
                    rssi_wert = round((sig_pct / 2.0) - 100.0, 1)

                    ch_str = status_daten.get("channel", status_daten.get("kanal", "1"))
                    kanal = int(ch_str) if ch_str.isdigit() else 1
                    phy = status_daten.get("radio type", status_daten.get("funktyp", "802.11ax"))
                    band = "5 GHz" if kanal > 14 else "2.4 GHz"

                    passendes_netz = {
                        "ssid": verbundene_ssid,
                        "bssid": verbundene_bssid,
                        "rssi": rssi_wert,
                        "channel": kanal,
                        "band": band,
                        "phy": phy,
                        "mod": "1024-QAM" if sig_pct > 75 else "256-QAM" if sig_pct > 50 else "64-QAM"
                    }

                # 2. Umgebungs-Scan (alle 2.5 Sekunden)
                if jetzt - self.letzter_umgebungs_scan >= 2.5 or not passendes_netz:
                    self.letzter_umgebungs_scan = jetzt
                    alle_netze = lese_wlan_netzwerke()
                    if alle_netze:
                        self.netzwerke_gefunden.emit(alle_netze)

                        if not passendes_netz and self.ziel_ssid:
                            for netz in alle_netze:
                                if netz["ssid"].lower() == self.ziel_ssid.lower():
                                    if not self.ziel_bssid or netz["bssid"] == self.ziel_bssid:
                                        passendes_netz = netz
                                        break

                        if not passendes_netz and alle_netze:
                            passendes_netz = max(alle_netze, key=lambda n: n.get("signal_pct", 0))

                # 3. Telemetrie absenden
                if passendes_netz:
                    rssi_val = float(passendes_netz["rssi"])
                    noise_val = -95.0
                    telemetrie = {
                        "timestamp_ms": int(jetzt * 1000),
                        "target_ssid": passendes_netz["ssid"],
                        "bssid": passendes_netz["bssid"],
                        "channel": passendes_netz["channel"],
                        "rssi": rssi_val,
                        "noise_floor": noise_val,
                        "snr": max(0.0, round(rssi_val - noise_val, 1)),
                        "retry_rate": 0.0,
                        "mod": passendes_netz.get("mod", "64-QAM"),
                        "phy": passendes_netz.get("phy", "802.11"),
                        "mcs": 7
                    }
                    self.daten_empfangen.emit(telemetrie)

            except Exception:
                pass

            vergangen = 0.0
            while self.laeuft and vergangen < self.abfrage_intervall:
                time.sleep(0.05)
                vergangen += 0.05

        self.verbindung_geandert.emit(False, "Interne Wi-Fi-Karte getrennt")


# Kompatibilitaets-Alias
InternerWlanWorker = WlanScanner
