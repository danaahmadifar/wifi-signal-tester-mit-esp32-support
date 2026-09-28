"""
WLAN Signal-Tester - Signal-Analyzer Ansicht (ui/views/analyzer_ansicht.py)
Arbeitsbereich zur Echtzeit-Analyse von Signalstaerke, Modulationsparametern und SNR.
Enthaelt Zielkonfiguration, Statuskarten, Echtzeit-Diagramm, Grenzwert-Alarm und CSV-Logger.
"""

import csv
import time
from collections import deque
from datetime import datetime

import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QGroupBox, QFrame,
    QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
import pyqtgraph as pg

from core.datenmodelle import berechne_signal_qualitaet
from ui.sprachen import tr
from ui.komponenten import StatusKartenWidget, ZielKonfigWidget


class SignalAnalyzerWidget(QWidget):
    """Kapselt den vollstaendigen Signal-Analyzer Arbeitsbereich."""

    # Signale an das Hauptfenster
    ziel_geaendert = pyqtSignal(str, str, int, int)      # ssid, bssid, kanal, rate
    scan_angefordert = pyqtSignal()
    live_signal_aktualisiert = pyqtSignal(float)          # aktueller geglaetteter RSSI
    status_meldung = pyqtSignal(str, int)                 # text, timeout_ms

    def __init__(self, eltern=None):
        super().__init__(eltern)

        # Zeitreihe & Glaettung (60 Sekunden Zeitfenster)
        self.zeit_fenster_sekunden = 60.0
        self.glaettungs_faktor = 0.65
        self.daten_zeitpunkte = deque()
        self.daten_roh_werte = deque()
        self.daten_geklaettet = deque()

        # Aktuelle Signalparameter
        self.ziel_ssid = ""
        self.ziel_bssid = ""
        self.ziel_kanal = 6
        self.ziel_rate = 10
        self.aktueller_ema = None
        self.aktueller_roh_rssi = -100.0
        self.aktuelle_mod = "Warte auf Signal"
        self.aktuelle_phy = "802.11"
        self.aktuelle_mcs = 0
        self.pakete_gesamt = 0
        self.letzter_paket_empfang = 0.0

        # Abtastraten-Ermittlung
        self.raten_zaehler = 0
        self.letzte_raten_zeit = time.time()
        self.aktuelle_rate_hz = 0.0

        # CSV-Aufzeichnung
        self.aufnahme_aktiv = False
        self.log_datei = None
        self.csv_schreiber = None
        self.aufgezeichnete_zeilen = 0
        self.aktueller_log_pfad = ""

        # Grenzwert-Alarm
        self.alarm_aktiv = False
        self.alarm_blink_an = False
        self.alarm_timer = QTimer(self)
        self.alarm_timer.timeout.connect(self._alarm_blinken)

        self._erstelle_oberflaeche()

        # Diagramm-Aktualisierung (30 ms ~ 33 FPS)
        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self.aktualisiere_diagramm)
        self.render_timer.start(30)

    def _erstelle_oberflaeche(self):
        """Baut das Layout fuer die Signal-Analyzer Ansicht auf."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 1. Zielkonfiguration
        self.ziel_konfig_widget = ZielKonfigWidget()
        self.ziel_konfig_widget.konfiguration_gesendet.connect(self.ziel_konfiguration_anwenden)
        self.ziel_konfig_widget.scan_geklickt.connect(self._scan_mit_popup_anfordern)
        self.ziel_konfig_widget.combo_ziel_ssid.currentIndexChanged.connect(self._on_ziel_ssid_ausgewaehlt)
        self.ziel_konfig_widget.combo_ziel_ssid.activated.connect(self._on_ziel_ssid_ausgewaehlt)
        layout.addWidget(self.ziel_konfig_widget)

        # 2. Statuskarten-Leiste
        self.status_karten_widget = StatusKartenWidget()
        layout.addWidget(self.status_karten_widget)

        # 3. Alarm-Banner
        self.alarm_banner = QLabel()
        self.alarm_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.alarm_banner.setFixedHeight(24)
        self.alarm_banner.setStyleSheet(
            "background-color: #0d1610; color: #22c55e; font-weight: 600; font-size: 10px; "
            "border-radius: 3px; border: 1px solid #14351e;"
        )
        self.alarm_banner.setText(tr("alarm_normal"))
        layout.addWidget(self.alarm_banner)

        # 4. Echtzeit-Pegeldiagramm
        p_frame = QFrame()
        p_frame.setStyleSheet("background-color: #121212; border: 1px solid #262626; border-radius: 4px;")
        p_lay = QVBoxLayout(p_frame)
        p_lay.setContentsMargins(8, 6, 8, 6)

        p_kopf = QHBoxLayout()
        self.lbl_plot_titel = QLabel()
        self.lbl_plot_titel.setStyleSheet("font-weight: 700; color: #a0a0a0; font-size: 11px;")
        p_kopf.addWidget(self.lbl_plot_titel)
        p_kopf.addSpacing(16)

        self.lbl_filter = QLabel()
        self.lbl_filter.setStyleSheet("color: #777777; font-size: 11px;")
        p_kopf.addWidget(self.lbl_filter)

        self.combo_filter = QComboBox()
        self.combo_filter.currentIndexChanged.connect(self._filter_geaendert)
        p_kopf.addWidget(self.combo_filter)

        self.chk_rohdaten = QCheckBox()
        self.chk_rohdaten.setChecked(True)
        self.chk_rohdaten.setStyleSheet("font-size: 11px; color: #f97316; font-weight: 600;")
        self.chk_rohdaten.toggled.connect(self._rohdaten_anzeige_umschalten)
        p_kopf.addWidget(self.chk_rohdaten)

        self.chk_mittelwert = QCheckBox()
        self.chk_mittelwert.setChecked(False)
        self.chk_mittelwert.setStyleSheet("font-size: 11px; color: #eab308; font-weight: 600;")
        self.chk_mittelwert.toggled.connect(self._mittelwert_anzeige_umschalten)
        p_kopf.addWidget(self.chk_mittelwert)

        p_kopf.addStretch()

        self.lbl_stats = QLabel("Min: -- | Max: -- | Avg: --")
        self.lbl_stats.setStyleSheet("color: #777777; font-weight: 500; font-size: 10px; font-family: monospace;")
        p_kopf.addWidget(self.lbl_stats)
        p_lay.addLayout(p_kopf)

        self.diagramm_widget = pg.PlotWidget()
        self.diagramm_widget.setBackground("#070707")
        self.diagramm_widget.showGrid(x=True, y=True, alpha=0.15)
        self.diagramm_widget.setYRange(-100, -20, padding=0.02)
        self.diagramm_widget.setXRange(-self.zeit_fenster_sekunden, 0, padding=0.01)

        self.kurve_geklaettet = self.diagramm_widget.plot(pen=pg.mkPen(color="#00e5ff", width=2.4))
        self.kurve_rohdaten = self.diagramm_widget.plot(pen=pg.mkPen(color=QColor(249, 115, 22, 220), width=1.4, style=Qt.PenStyle.DashLine))

        self.linie_mittelwert = pg.InfiniteLine(angle=0, pen=pg.mkPen(color="#eab308", width=1.4, style=Qt.PenStyle.DashLine))
        self.diagramm_widget.addItem(self.linie_mittelwert)
        self.linie_mittelwert.hide()

        self.linie_alarm = pg.InfiniteLine(angle=0, pen=pg.mkPen(color="#dc2626", width=1.6, style=Qt.PenStyle.DotLine))
        self.linie_alarm.setPos(-75)
        self.diagramm_widget.addItem(self.linie_alarm)

        p_lay.addWidget(self.diagramm_widget)
        layout.addWidget(p_frame, stretch=1)

        # 5. Alarm & Logging Leiste
        u_leiste = QHBoxLayout()
        self.gruppe_alarm = QGroupBox()
        al_lay = QHBoxLayout(self.gruppe_alarm)
        self.chk_alarm_aktiv = QCheckBox()
        self.chk_alarm_aktiv.setChecked(True)
        self.chk_alarm_aktiv.toggled.connect(self.aktualisiere_alarm_einstellungen)
        al_lay.addWidget(self.chk_alarm_aktiv)

        self.lbl_schwelle = QLabel()
        al_lay.addWidget(self.lbl_schwelle)
        self.spin_schwelle = QSpinBox()
        self.spin_schwelle.setRange(-95, -30)
        self.spin_schwelle.setValue(-75)
        self.spin_schwelle.setSuffix(" dBm")
        self.spin_schwelle.valueChanged.connect(self.aktualisiere_alarm_einstellungen)
        al_lay.addWidget(self.spin_schwelle)
        u_leiste.addWidget(self.gruppe_alarm, 1)

        self.gruppe_logger = QGroupBox()
        lg_lay = QHBoxLayout(self.gruppe_logger)
        self.btn_aufnahme = QPushButton()
        self.btn_aufnahme.clicked.connect(self.aufnahme_umschalten)
        lg_lay.addWidget(self.btn_aufnahme)

        self.lbl_zeilen = QLabel(tr("records_count", count=0))
        self.lbl_zeilen.setStyleSheet("color: #777777; font-size: 11px;")
        lg_lay.addWidget(self.lbl_zeilen)

        self.btn_export = QPushButton()
        self.btn_export.clicked.connect(self.exportiere_csv_manuell)
        lg_lay.addWidget(self.btn_export)
        u_leiste.addWidget(self.gruppe_logger, 2)

        layout.addLayout(u_leiste)

    def _scan_mit_popup_anfordern(self):
        self.scan_angefordert.emit()
        QTimer.singleShot(400, self.ziel_konfig_widget.combo_ziel_ssid.showPopup)

    def netzwerke_empfangen(self, netzwerke: list):
        """Aktualisiert die Netzwerk-Auswahlliste."""
        combo = self.ziel_konfig_widget.combo_ziel_ssid
        text_alt = combo.currentText().strip()
        combo.blockSignals(True)
        combo.clear()

        ssids = set()
        for n in netzwerke:
            ssid = n.get("ssid", "").strip()
            if not ssid or ssid in ssids:
                continue
            ssids.add(ssid)
            rssi = n.get("rssi", -100)
            ch = n.get("channel", 1)
            bssid = n.get("bssid", "")
            combo.addItem(f"{ssid}  ({rssi:+.0f} dBm, Ch {ch})", (ssid, bssid, ch))

        if text_alt:
            idx = combo.findText(text_alt, Qt.MatchFlag.MatchStartsWith)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(text_alt)
        elif combo.count() > 0:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

        if combo.currentIndex() >= 0:
            self._on_ziel_ssid_ausgewaehlt(combo.currentIndex())

    def _on_ziel_ssid_ausgewaehlt(self, index: int):
        daten = self.ziel_konfig_widget.combo_ziel_ssid.itemData(index)
        if daten and isinstance(daten, tuple) and len(daten) >= 3:
            ssid, bssid, ch = daten
            if bssid:
                self.ziel_konfig_widget.txt_ziel_bssid.setText(bssid)
            if ch and 1 <= ch <= 14:
                self.ziel_konfig_widget.spin_ziel_kanal.setValue(ch)
        else:
            txt = self.ziel_konfig_widget.combo_ziel_ssid.currentText().strip()
            import re
            m = re.search(r"Ch\s*(\d+)", txt, re.IGNORECASE)
            if m:
                ch = int(m.group(1))
                if 1 <= ch <= 14:
                    self.ziel_konfig_widget.spin_ziel_kanal.setValue(ch)

    def ziel_konfiguration_anwenden(self, ssid: str, bssid: str, kanal: int, rate: int):
        """Wendet geaenderte Zielparameter an."""
        import re
        sauber = re.sub(r"\s*\([+-]?\d+\s*dBm,\s*Ch\s*\d+\)$", "", ssid.strip(), flags=re.IGNORECASE)
        self.ziel_ssid = sauber.strip()
        self.ziel_bssid = bssid.strip().upper()
        self.ziel_kanal = kanal
        self.ziel_rate = rate
        self.aktueller_ema = None
        self.ziel_geaendert.emit(self.ziel_ssid, self.ziel_bssid, self.ziel_kanal, self.ziel_rate)
        self.status_meldung.emit(f"Ziel gesetzt: {self.ziel_ssid or 'Alle Netze'} (Kanal {self.ziel_kanal})", 3000)

    def daten_verarbeiten(self, d: dict):
        """Verarbeitet eingehende Telemetriedatensaetze (ESP32 oder WLAN-Karte)."""
        jetzt = time.time()
        self.letzter_paket_empfang = jetzt

        roh_rssi = float(d.get("rssi", -100.0))
        if roh_rssi < -110.0 or roh_rssi > 0.0:
            return

        self.aktueller_roh_rssi = roh_rssi
        if self.aktueller_ema is None:
            self.aktueller_ema = roh_rssi
        else:
            # Reaktionsschnelle adaptive Glaettung (Near-Realtime):
            delta = abs(roh_rssi - self.aktueller_ema)
            if self.glaettungs_faktor >= 0.99:
                effektives_alpha = 1.0
            elif delta > 2.0:
                boost = min(0.65, (delta - 2.0) * 0.15)
                effektives_alpha = min(1.0, self.glaettungs_faktor + boost)
            else:
                effektives_alpha = self.glaettungs_faktor

            self.aktueller_ema = effektives_alpha * roh_rssi + (1.0 - effektives_alpha) * self.aktueller_ema

        # Zeitreihe fuer Diagramm aktualisieren
        self.daten_zeitpunkte.append(jetzt)
        self.daten_roh_werte.append(roh_rssi)
        self.daten_geklaettet.append(self.aktueller_ema)

        grenze = jetzt - self.zeit_fenster_sekunden
        while self.daten_zeitpunkte and self.daten_zeitpunkte[0] < grenze:
            self.daten_zeitpunkte.popleft()
            self.daten_roh_werte.popleft()
            self.daten_geklaettet.popleft()

        # Telemetriezaehler
        self.raten_zaehler += 1
        delta_zeit = jetzt - self.letzte_raten_zeit
        if delta_zeit >= 1.0:
            self.aktuelle_rate_hz = self.raten_zaehler / delta_zeit
            self.raten_zaehler = 0
            self.letzte_raten_zeit = jetzt

        self.aktuelle_mod = d.get("mod", self.aktuelle_mod)
        self.aktuelle_phy = d.get("phy", self.aktuelle_phy)
        self.aktuelle_mcs = int(d.get("mcs", self.aktuelle_mcs))
        self.pakete_gesamt = int(d.get("packet_count", self.pakete_gesamt + 1))
        noise_floor = float(d.get("noise_floor", -95.0))
        snr = float(d.get("snr", max(0.0, roh_rssi - noise_floor)))
        retry_rate = float(d.get("retry_rate", 0.0))

        # Statuskarten aktualisieren
        self.status_karten_widget.aktualisiere_messung(
            ssid=self.ziel_ssid if self.ziel_ssid else d.get("target_ssid", ""),
            bssid=d.get("bssid", self.ziel_bssid or "--"),
            kanal=int(d.get("channel", self.ziel_kanal)),
            roh_rssi=roh_rssi,
            ema_rssi=self.aktueller_ema,
            mod=self.aktuelle_mod,
            phy=self.aktuelle_phy,
            mcs=self.aktuelle_mcs,
            rate_hz=self.aktuelle_rate_hz,
            pakete_gesamt=self.pakete_gesamt,
            noise_floor=noise_floor,
            snr=snr,
            retry_rate=retry_rate
        )

        # 10s Kurzzeit-Statistik
        grenze_10s = jetzt - 10.0
        werte_10s = [r for t, r in zip(self.daten_zeitpunkte, self.daten_roh_werte) if t >= grenze_10s]
        if werte_10s:
            min_10s, max_10s = min(werte_10s), max(werte_10s)
            self.status_karten_widget.aktualisiere_kurzzeit_statistik(min_10s, max_10s, max_10s - min_10s)

        # 60s Extrema
        if self.daten_geklaettet:
            self.status_karten_widget.aktualisiere_telemetrie_extrema(min(self.daten_geklaettet), max(self.daten_geklaettet))

        # Signal nach aussen melden (z. B. fuer Heatmap)
        self.live_signal_aktualisiert.emit(self.aktueller_ema)

        # Schwellenwert-Alarm pruefen
        if self.chk_alarm_aktiv.isChecked() and self.aktueller_ema < self.spin_schwelle.value():
            if not self.alarm_aktiv:
                self.alarm_aktiv = True
                self.alarm_timer.start(400)
        else:
            if self.alarm_aktiv:
                self.alarm_aktiv = False
                self.alarm_timer.stop()
                self.alarm_banner.setStyleSheet(
                    "background-color: #0d1610; color: #22c55e; font-weight: 600; font-size: 10px; "
                    "border-radius: 3px; border: 1px solid #14351e;"
                )
                self.alarm_banner.setText(tr("alarm_normal"))

        # CSV protokollieren
        if self.aufnahme_aktiv and self.csv_schreiber:
            iso_zeit = datetime.now().isoformat(timespec="milliseconds")
            self.csv_schreiber.writerow([
                iso_zeit,
                d.get("target_ssid", self.ziel_ssid),
                d.get("bssid", "--"),
                d.get("channel", self.ziel_kanal),
                f"{roh_rssi:.1f}",
                f"{self.aktueller_ema:.1f}",
                self.aktuelle_mod,
                self.aktuelle_phy,
                self.aktuelle_mcs
            ])
            self.aufgezeichnete_zeilen += 1
            self.lbl_zeilen.setText(tr("records_count", count=self.aufgezeichnete_zeilen))

    def aktualisiere_diagramm(self):
        """Zeichnet die Signalverlaufskurven im Diagramm neu."""
        if not self.daten_zeitpunkte:
            return

        jetzt = time.time()
        xs = [t - jetzt for t in self.daten_zeitpunkte]

        if self.chk_rohdaten.isChecked():
            self.kurve_rohdaten.setData(xs, list(self.daten_roh_werte))
        else:
            self.kurve_rohdaten.setData([], [])

        self.kurve_geklaettet.setData(xs, list(self.daten_geklaettet))

        if self.daten_geklaettet:
            avg_val = float(np.mean(self.daten_geklaettet))
            self.linie_mittelwert.setPos(avg_val)
            self.lbl_stats.setText(tr("stat_overlay", min=min(self.daten_geklaettet), max=max(self.daten_geklaettet), avg=avg_val))

    def _alarm_blinken(self):
        self.alarm_blink_an = not self.alarm_blink_an
        bg = "#7f1d1d" if self.alarm_blink_an else "#450a0a"
        self.alarm_banner.setStyleSheet(f"background-color: {bg}; color: #ffffff; font-weight: 700; font-size: 10px; border-radius: 3px;")
        self.alarm_banner.setText(tr("alarm_banner"))

    def _filter_geaendert(self, index: int):
        faktoren = [0.65, 0.15, 0.40, 1.0]
        if 0 <= index < len(faktoren):
            self.glaettungs_faktor = faktoren[index]

    def _rohdaten_anzeige_umschalten(self, sichtbar: bool):
        if not sichtbar:
            self.kurve_rohdaten.setData([], [])

    def _mittelwert_anzeige_umschalten(self, sichtbar: bool):
        if sichtbar:
            self.linie_mittelwert.show()
        else:
            self.linie_mittelwert.hide()

    def aktualisiere_alarm_einstellungen(self):
        self.linie_alarm.setPos(self.spin_schwelle.value())

    def aufnahme_umschalten(self):
        """Startet oder beendet das Schreiben der CSV-Logdatei."""
        if not self.aufnahme_aktiv:
            zeitstempel = datetime.now().strftime("%Y%m%d_%H%M%S")
            pfad, _ = QFileDialog.getSaveFileName(self, tr("start_recording"), f"wlan_messung_{zeitstempel}.csv", "CSV (*.csv)")
            if not pfad:
                return

            try:
                self.log_datei = open(pfad, "w", newline="", encoding="utf-8")
                self.csv_schreiber = csv.writer(self.log_datei, delimiter=";")
                self.csv_schreiber.writerow(["Timestamp_ISO", "SSID", "BSSID", "Kanal", "Roh_RSSI_dBm", "Geglaettet_RSSI_dBm", "Modulation", "PHY", "MCS"])
                self.aufnahme_aktiv = True
                self.aufgezeichnete_zeilen = 0
                self.aktueller_log_pfad = pfad
                self.btn_aufnahme.setText(tr("stop_recording"))
                self.btn_aufnahme.setProperty("class", "DangerButton")
                self.btn_aufnahme.style().unpolish(self.btn_aufnahme)
                self.btn_aufnahme.style().polish(self.btn_aufnahme)
            except Exception as e:
                QMessageBox.critical(self, "CSV", f"Fehler beim Erstellen der Logdatei: {e}")
        else:
            self.aufnahme_aktiv = False
            if self.log_datei:
                try:
                    self.log_datei.close()
                except Exception:
                    pass
                self.log_datei = None
                self.csv_schreiber = None
            self.btn_aufnahme.setText(tr("start_recording"))
            self.btn_aufnahme.setProperty("class", "")
            self.btn_aufnahme.style().unpolish(self.btn_aufnahme)
            self.btn_aufnahme.style().polish(self.btn_aufnahme)
            QMessageBox.information(self, "CSV", f"Aufzeichnung beendet. {self.aufgezeichnete_zeilen} Datensätze gespeichert.")

    def exportiere_csv_manuell(self):
        """Exportiert die aktuellen Pufferdaten als CSV-Datei."""
        if not self.daten_zeitpunkte:
            QMessageBox.information(self, "Export", "Keine Messdaten zum Exportieren vorhanden.")
            return

        pfad, _ = QFileDialog.getSaveFileName(self, tr("export_btn"), "signal_export.csv", "CSV (*.csv)")
        if not pfad:
            return

        try:
            with open(pfad, "w", newline="", encoding="utf-8") as f:
                schreiber = csv.writer(f, delimiter=";")
                schreiber.writerow(["Zeitpunkt_Sekunden", "Roh_RSSI_dBm", "Glaettung_dBm"])
                jetzt = time.time()
                for t, r, g in zip(self.daten_zeitpunkte, self.daten_roh_werte, self.daten_geklaettet):
                    schreiber.writerow([f"{t - jetzt:.3f}", f"{r:.1f}", f"{g:.1f}"])
            QMessageBox.information(self, "Export", "Messdaten erfolgreich exportiert.")
        except Exception as e:
            QMessageBox.critical(self, "Export", f"Fehler beim Export: {e}")

    def aktualisiere_sprache(self):
        """Aktualisiert alle UI-Texte im Signal-Analyzer."""
        self.lbl_plot_titel.setText(tr("plot_title"))
        self.lbl_filter.setText(tr("filter_lbl"))
        self.combo_filter.blockSignals(True)
        self.combo_filter.clear()
        self.combo_filter.addItem(tr("filter_medium"))
        self.combo_filter.addItem(tr("filter_strong"))
        self.combo_filter.addItem(tr("filter_light"))
        self.combo_filter.addItem(tr("filter_off"))
        self.combo_filter.blockSignals(False)

        self.chk_rohdaten.setText(tr("show_raw"))
        self.chk_mittelwert.setText(tr("show_mean"))
        self.diagramm_widget.setLabel("left", tr("plot_y_label"), units="dBm")
        self.diagramm_widget.setLabel("bottom", tr("plot_x_label"), units="s")

        self.gruppe_alarm.setTitle(tr("alarm_title"))
        self.chk_alarm_aktiv.setText(tr("alarm_active"))
        self.lbl_schwelle.setText(tr("threshold_lbl"))
        self.gruppe_logger.setTitle(tr("logger_title"))
        self.btn_aufnahme.setText(tr("stop_recording") if self.aufnahme_aktiv else tr("start_recording"))
        self.btn_export.setText(tr("export_btn"))

        self.ziel_konfig_widget.aktualisiere_sprache()
        self.status_karten_widget.aktualisiere_sprache()
