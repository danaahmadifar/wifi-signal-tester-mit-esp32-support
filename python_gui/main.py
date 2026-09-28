"""
WLAN Signal-Tester - Hauptprogramm (main.py)
Desktop-Anwendung zur Echtzeit-Analyse von WLAN-Signalen, Netzwerk-Diagnose und Grundriss-Heatmaps.
Unterstuetzt die ESP32-Hardware-Messsonde (USB-UART) und native PC-WLAN-Karten.
"""

import sys
import os

# Hauptverzeichnis fuer Modulimporte registrieren
basis_dir = os.path.dirname(os.path.abspath(__file__))
if basis_dir not in sys.path:
    sys.path.insert(0, basis_dir)

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QStackedWidget, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg

from ui.design import DUNKLES_DESIGN
from ui.sprachen import tr, set_language, is_rtl, LANGUAGES
from core.serieller_worker import SeriellerWorker
from core.wlan_scanner import WlanScanner, NetzwerkScanThread
from ui.views.analyzer_ansicht import SignalAnalyzerWidget
from ui.views.diagnose_ansicht import NetzwerkDiagnoseWidget
from ui.views.grundriss_ansicht import GrundrissWidget


class WLANSignalTesterApp(QMainWindow):
    """Hauptfenster des WLAN Signal-Testers mit 3 integrierten Arbeitsbereichen."""

    def __init__(self):
        super().__init__()
        self.resize(1340, 840)
        self.setMinimumSize(1020, 660)

        # Farb- und Diagrammeinstellungen
        self.setStyleSheet(DUNKLES_DESIGN)
        pg.setConfigOption("background", "#060606")
        pg.setConfigOption("foreground", "#808080")
        pg.setConfigOption("antialias", True)

        # Hardware-Schnittstellen
        self._initialisiere_hardware()

        # Benutzeroberflaeche aufbauen
        self._erstelle_oberflaeche()
        self.aktualisiere_sprache()
        self.aktualisiere_ports()

        # Initialer Umgebungsscan
        QTimer.singleShot(600, self.starte_netzwerk_scan)

    def _initialisiere_hardware(self):
        """Initialisiert serielle Schnittstelle und internen WLAN-Scanner."""
        self.seriell_worker = SeriellerWorker()
        self.seriell_worker.daten_empfangen.connect(self._daten_weiterleiten)
        self.seriell_worker.netzwerke_gefunden.connect(self._netzwerke_weiterleiten)
        self.seriell_worker.verbindung_geandert.connect(self.verbindung_geaendert)
        self.seriell_worker.fehler_aufgetreten.connect(lambda e: self.statusBar().showMessage(f"ESP32: {e}", 5000))
        self.seriell_worker.befehl_antwort.connect(lambda r: self.statusBar().showMessage(f"ESP32: {r}", 4000))

        self.wlan_worker = WlanScanner()
        self.wlan_worker.daten_empfangen.connect(self._daten_weiterleiten)
        self.wlan_worker.netzwerke_gefunden.connect(self._netzwerke_weiterleiten)
        self.wlan_worker.verbindung_geandert.connect(self.verbindung_geaendert)

        self.scan_thread = NetzwerkScanThread()
        self.scan_thread.netzwerke_gefunden.connect(self._netzwerke_weiterleiten)

    def _erstelle_oberflaeche(self):
        """Erstellt die Kopfleiste und bindet die 3 Hauptansichten ein."""
        zentral = QWidget()
        self.setCentralWidget(zentral)
        layout = QVBoxLayout(zentral)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)

        # 1. Kopfleiste: Ansicht, Schnittstelle, Sprache und Verbindungsstatus
        kopf = QHBoxLayout()

        self.combo_ansicht = QComboBox()
        self.combo_ansicht.setStyleSheet("""
            QComboBox {
                background-color: #0284c7;
                color: #ffffff;
                font-weight: 700;
                font-size: 11px;
                border: 1px solid #38bdf8;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 170px;
            }
            QComboBox::drop-down { border: none; width: 18px; }
            QComboBox QAbstractItemView {
                background-color: #141414;
                color: #ffffff;
                selection-background-color: #0284c7;
                border: 1px solid #2a2a2a;
            }
        """)
        self.combo_ansicht.addItem(tr("view_analyzer"), 0)
        self.combo_ansicht.addItem(tr("view_diagnostics"), 1)
        self.combo_ansicht.addItem(tr("view_heatmap"), 2)
        self.combo_ansicht.currentIndexChanged.connect(self.ansicht_gewaehlt)
        kopf.addWidget(self.combo_ansicht)

        kopf.addWidget(QLabel("|"))

        self.lbl_schnittstelle = QLabel()
        self.lbl_schnittstelle.setStyleSheet("color: #888888; font-size: 11px;")
        kopf.addWidget(self.lbl_schnittstelle)

        self.combo_ports = QComboBox()
        self.combo_ports.setMinimumWidth(240)
        kopf.addWidget(self.combo_ports)

        self.btn_ports_aktualisieren = QPushButton()
        self.btn_ports_aktualisieren.clicked.connect(self.aktualisiere_ports)
        kopf.addWidget(self.btn_ports_aktualisieren)

        self.btn_verbinden = QPushButton()
        self.btn_verbinden.setProperty("class", "PrimaryButton")
        self.btn_verbinden.clicked.connect(self.verbindung_umschalten)
        kopf.addWidget(self.btn_verbinden)

        kopf.addStretch()

        self.combo_sprache = QComboBox()
        self.combo_sprache.setMinimumWidth(120)
        for code, name in LANGUAGES:
            self.combo_sprache.addItem(name, code)
        self.combo_sprache.currentIndexChanged.connect(self.sprache_wechseln)
        kopf.addWidget(self.combo_sprache)

        self.lbl_status = QLabel()
        self.lbl_status.setProperty("class", "StatusDisconnected")
        kopf.addWidget(self.lbl_status)
        layout.addLayout(kopf)

        # 2. QStackedWidget fuer die 3 Hauptbereiche
        self.stacked_widget = QStackedWidget()

        # Seite 0: Signal-Analyzer
        self.seite_analyzer = SignalAnalyzerWidget(self)
        self.seite_analyzer.ziel_geaendert.connect(self._ziel_parameter_geaendert)
        self.seite_analyzer.scan_angefordert.connect(self.starte_netzwerk_scan)
        self.seite_analyzer.live_signal_aktualisiert.connect(self._live_signal_an_grundriss)
        self.seite_analyzer.status_meldung.connect(lambda msg, ms: self.statusBar().showMessage(msg, ms))
        self.stacked_widget.addWidget(self.seite_analyzer)

        # Seite 1: Netzwerk-Diagnose
        self.seite_diagnose = NetzwerkDiagnoseWidget(
            serial_worker=self.seriell_worker,
            standard_ssid="",
            eltern=self
        )
        self.stacked_widget.addWidget(self.seite_diagnose)

        # Seite 2: Grundriss-Heatmap
        self.seite_grundriss = GrundrissWidget(self)
        self.grundriss_fenster = self.seite_grundriss
        self.stacked_widget.addWidget(self.seite_grundriss)

        layout.addWidget(self.stacked_widget, stretch=1)

    def ansicht_gewaehlt(self, index: int):
        """Wechselt zwischen Signal-Analyzer, Netzwerk-Diagnose und Grundriss."""
        self.stacked_widget.setCurrentIndex(index)
        if index == 0:
            if self.seite_diagnose.ist_aktiv:
                self.seite_diagnose.stoppen()
            self._synchronisiere_filter()
        elif index == 1:
            self.seite_diagnose.setze_ziel_ssid(self.seite_analyzer.ziel_ssid)
            if self.seriell_worker.isRunning():
                self.seite_diagnose.setze_pruefer("esp32")
            else:
                self.seite_diagnose.setze_pruefer("host")
        elif index == 2:
            if self.seite_diagnose.ist_aktiv:
                self.seite_diagnose.stoppen()
            if self.seite_analyzer.aktueller_ema is not None:
                self.seite_grundriss.aktualisiere_live_signal(self.seite_analyzer.aktueller_ema)

    def aktualisiere_ports(self):
        """Liest verfuegbare COM-Ports und die interne WLAN-Karte ein."""
        self.combo_ports.clear()
        self.combo_ports.addItem(tr("internal_wifi_card"), "INTERNAL_WIFI")
        for dev, desc in SeriellerWorker.verfuegbare_ports():
            self.combo_ports.addItem(desc, dev)

    def verbindung_umschalten(self):
        """Startet oder stoppt die Datenerfassung ueber die gewaehlte Schnittstelle."""
        aktiv = self.seriell_worker.isRunning() or self.wlan_worker.isRunning()
        if aktiv:
            if self.seriell_worker.isRunning():
                self.seriell_worker.stoppen()
            if self.wlan_worker.isRunning():
                self.wlan_worker.stoppen()
        else:
            auswahl = self.combo_ports.currentData()
            if not auswahl:
                QMessageBox.warning(self, "Schnittstelle", "Bitte eine Schnittstelle auswählen.")
                return

            if auswahl == "INTERNAL_WIFI":
                self.wlan_worker.start()
                self._synchronisiere_filter()
            else:
                self.seriell_worker.konfigurieren(port=auswahl, baudrate=115200)
                self.seriell_worker.start()
                QTimer.singleShot(350, self._synchronisiere_filter)

    def verbindung_geaendert(self, verbunden: bool, meldung: str):
        """Aktualisiert visuelle Status- und Verbindungsindikatoren."""
        self.lbl_status.setText(tr("status_connected") if verbunden else tr("status_disconnected"))
        self.lbl_status.setProperty("class", "StatusConnected" if verbunden else "StatusDisconnected")
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)
        self.combo_ports.setEnabled(not verbunden)
        self.btn_ports_aktualisieren.setEnabled(not verbunden)
        self.btn_verbinden.setText(tr("disconnect") if verbunden else tr("connect"))
        self.btn_verbinden.setProperty("class", "DangerButton" if verbunden else "PrimaryButton")
        self.btn_verbinden.style().unpolish(self.btn_verbinden)
        self.btn_verbinden.style().polish(self.btn_verbinden)
        self.statusBar().showMessage(meldung, 4000)

    def starte_netzwerk_scan(self):
        """Startet den Umgebungsscan auf ESP32 oder Host-PC."""
        if self.seriell_worker.isRunning():
            self.statusBar().showMessage("ESP32 scannt Frequenzen...", 3000)
            self.seriell_worker.starte_scan()
        elif not self.scan_thread.isRunning():
            self.statusBar().showMessage("Host-WLAN sucht Netzwerke...", 3000)
            self.scan_thread.start()

    def _daten_weiterleiten(self, d: dict):
        self.seite_analyzer.daten_verarbeiten(d)

    def _netzwerke_weiterleiten(self, netzwerke: list):
        self.seite_analyzer.netzwerke_empfangen(netzwerke)
        ssids = {n.get("ssid", "").strip() for n in netzwerke if n.get("ssid", "").strip()}
        self.seite_grundriss.setze_verfuegbare_netze(sorted(list(ssids)))

    def _live_signal_an_grundriss(self, rssi: float):
        self.seite_grundriss.aktualisiere_live_signal(rssi)

    def _ziel_parameter_geaendert(self, ssid: str, bssid: str, kanal: int, rate: int):
        self._synchronisiere_filter()

    def _synchronisiere_filter(self):
        """Uebertraegt Filterparameter an den aktiven Worker."""
        if self.seriell_worker.isRunning():
            self.seriell_worker.sende_konfiguration(
                self.seite_analyzer.ziel_ssid,
                self.seite_analyzer.ziel_bssid,
                self.seite_analyzer.ziel_kanal,
                self.seite_analyzer.ziel_rate
            )
        if self.wlan_worker.isRunning():
            self.wlan_worker.setze_ziel(
                self.seite_analyzer.ziel_ssid,
                self.seite_analyzer.ziel_bssid
            )

    def sprache_wechseln(self, index: int):
        code = self.combo_sprache.itemData(index)
        if code:
            set_language(code)
            self.aktualisiere_sprache()

    def aktualisiere_sprache(self):
        """Aktualisiert alle UI-Texte im gesamten Fenster."""
        self.setWindowTitle(tr("app_title"))
        self.lbl_schnittstelle.setText(tr("port_lbl"))
        self.btn_ports_aktualisieren.setText(tr("refresh"))
        aktiv = self.seriell_worker.isRunning() or self.wlan_worker.isRunning()
        self.btn_verbinden.setText(tr("disconnect") if aktiv else tr("connect"))
        self.lbl_status.setText(tr("status_connected") if aktiv else tr("status_disconnected"))

        # Ansichtsauswahl Dropdown
        self.combo_ansicht.blockSignals(True)
        self.combo_ansicht.setItemText(0, tr("view_analyzer"))
        self.combo_ansicht.setItemText(1, tr("view_diagnostics"))
        self.combo_ansicht.setItemText(2, tr("view_heatmap"))
        self.combo_ansicht.blockSignals(False)

        # Untergeordnete Ansichten aktualisieren
        self.seite_analyzer.aktualisiere_sprache()
        self.seite_diagnose.aktualisiere_sprache()
        self.seite_grundriss.aktualisiere_sprache()

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)


def main():
    app = QApplication(sys.argv)
    fenster = WLANSignalTesterApp()
    fenster.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
