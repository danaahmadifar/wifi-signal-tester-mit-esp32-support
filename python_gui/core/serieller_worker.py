"""
WLAN Signal-Tester - Serieller Worker (core/serieller_worker.py)
Verwaltet die serielle USB-Kommunikation mit dem ESP32 in einem separaten Hintergrund-Thread.
"""

import json
import time
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
import serial
import serial.tools.list_ports


class SeriellerWorker(QThread):
    """Worker-Thread fuer den seriellen Datenaustausch mit der ESP32-Messhardware."""

    # Qt-Signale zur Uebertragung von Messwerten und Ereignissen an die GUI
    daten_empfangen = pyqtSignal(dict)
    netzwerke_gefunden = pyqtSignal(list)
    verbindung_geandert = pyqtSignal(bool, str)
    fehler_aufgetreten = pyqtSignal(str)
    befehl_antwort = pyqtSignal(str)
    diagnose_status = pyqtSignal(dict)
    diagnose_ergebnis = pyqtSignal(dict)
    diagnose_ping = pyqtSignal(dict)

    def __init__(self, eltern=None):
        super().__init__(eltern)
        self._sperre = QMutex()
        self.laeuft = False
        self.port = ""
        self.baudrate = 115200
        self.seriell = None
        self.befehls_warteschlange = []
        self.gescannte_netze = []

    @staticmethod
    def verfuegbare_ports() -> list[tuple[str, str]]:
        """Ermittelt alle verfuegbaren seriellen COM-Ports des Systems."""
        ports = []
        for info in serial.tools.list_ports.comports():
            beschreibung = info.description if info.description else "Serieller Port"
            ports.append((info.device, f"{info.device} ({beschreibung})"))
        return ports

    def konfigurieren(self, port: str, baudrate: int = 115200):
        """Setzt Port und Übertragungsrate fest."""
        with QMutexLocker(self._sperre):
            self.port = port
            self.baudrate = baudrate

    def sende_befehl(self, befehl: str):
        """Reiht einen Steuerbefehl in die Sendeliste ein."""
        with QMutexLocker(self._sperre):
            if not befehl.endswith("\n"):
                befehl += "\n"
            self.befehls_warteschlange.append(befehl)

    def sende_konfiguration(self, ssid: str, bssid: str, kanal: int, abtastrate: int):
        """Sendet Filterparameter (SSID, BSSID, Kanal, Rate) als JSON an den ESP32."""
        daten = {
            "cmd": "set_filter",
            "ssid": ssid.strip(),
            "bssid": bssid.strip().upper(),
            "channel": int(kanal),
            "rate_hz": int(abtastrate)
        }
        self.sende_befehl(json.dumps(daten, separators=(',', ':')))

    def starte_scan(self):
        """Initiiert einen WLAN-Umgebungsscan auf dem ESP32."""
        self.gescannte_netze.clear()
        self.sende_befehl('{"cmd":"scan"}')

    def starte_diagnose(self, ssid: str, passwort: str = "", ziel_ip: str = "1.1.1.1"):
        """Startet den Verbindungs- und Latenz-Benchmark auf dem ESP32."""
        daten = {
            "cmd": "start_diag",
            "ssid": ssid.strip(),
            "password": passwort.strip(),
            "target_ip": ziel_ip.strip() if ziel_ip.strip() else "1.1.1.1"
        }
        self.sende_befehl(json.dumps(daten, separators=(',', ':')))

    def stoppe_diagnose(self):
        """Beendet die Diagnose und schaltet den ESP32 zurueck in den Sniffer-Modus."""
        self.sende_befehl('{"cmd":"stop_diag"}')

    def stoppen(self):
        """Beendet den Thread sicher."""
        with QMutexLocker(self._sperre):
            self.laeuft = False
        self.wait(1500)

    def run(self):
        """Laufzeitschleife: Oeffnet den Port und liest/schreibt Daten."""
        self.laeuft = True

        if not self.port:
            self.fehler_aufgetreten.emit("Keine serielle Schnittstelle ausgewaehlt.")
            self.verbindung_geandert.emit(False, "Kein Port")
            return

        try:
            self.seriell = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.05,
                write_timeout=0.5
            )
            try:
                self.seriell.set_buffer_size(rx_size=8192, tx_size=1024)
            except Exception:
                pass
            self.seriell.reset_input_buffer()
            self.verbindung_geandert.emit(True, f"Verbunden ({self.port})")
        except Exception as e:
            self.fehler_aufgetreten.emit(f"Verbindungsfehler: {e}")
            self.verbindung_geandert.emit(False, str(e))
            return

        puffer = ""
        while self.laeuft:
            # 1. Befehle aus der Warteschlange senden
            anstehend = []
            with QMutexLocker(self._sperre):
                if self.befehls_warteschlange:
                    anstehend = list(self.befehls_warteschlange)
                    self.befehls_warteschlange.clear()

            for cmd in anstehend:
                try:
                    self.seriell.write(cmd.encode("utf-8"))
                    self.seriell.flush()
                    if len(anstehend) > 1:
                        time.sleep(0.01)
                except Exception as e:
                    self.fehler_aufgetreten.emit(f"Sendefehler: {e}")

            # 2. Eintreffende Zeilen vom ESP32 einlesen
            try:
                anzahl = self.seriell.in_waiting
                if anzahl > 0:
                    text = self.seriell.read(anzahl).decode("utf-8", errors="replace")
                    puffer += text

                    while "\n" in puffer:
                        zeile, puffer = puffer.split("\n", 1)
                        zeile = zeile.strip()
                        if not zeile:
                            continue

                        if zeile.startswith("{") and zeile.endswith("}"):
                            try:
                                obj = json.loads(zeile)
                                if "scan_item" in obj:
                                    self.gescannte_netze.append(obj["scan_item"])
                                elif "scan_complete" in obj:
                                    if self.gescannte_netze:
                                        self.netzwerke_gefunden.emit(list(self.gescannte_netze))
                                        self.gescannte_netze.clear()
                                elif "diag_result" in obj:
                                    self.diagnose_ergebnis.emit(obj["diag_result"])
                                elif "diag_status" in obj:
                                    self.diagnose_status.emit(obj["diag_status"])
                                elif "diag_ping" in obj:
                                    self.diagnose_ping.emit(obj["diag_ping"])
                                elif "rssi" in obj:
                                    self.daten_empfangen.emit(obj)
                                elif "status" in obj:
                                    self.befehl_antwort.emit(zeile)
                            except json.JSONDecodeError:
                                pass
                        elif zeile.startswith("["):
                            self.befehl_antwort.emit(zeile)
                else:
                    time.sleep(0.001)

            except (serial.SerialException, OSError) as e:
                self.fehler_aufgetreten.emit(f"Schnittstellenabbruch: {e}")
                break

        # Port schliessen beim Beenden
        if self.seriell and self.seriell.is_open:
            try:
                self.seriell.close()
            except Exception:
                pass
        self.seriell = None
        self.verbindung_geandert.emit(False, "Getrennt")
