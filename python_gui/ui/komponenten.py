"""
WLAN Signal-Tester - UI-Komponenten (ui_komponenten.py)
Kapselt wiederverwendbare Oberflaechenelemente:
- StatusKartenWidget: 5 Metrik-Panels (Ziel, Signal, Kurzzeit, Modulation, Telemetrie)
- ZielKonfigWidget: Bedienleiste fuer Zielselektion, BSSID, Kanal und Abtastrate.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QLineEdit, QProgressBar, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.datenmodelle import (
    MODULATION_FARBEN, berechne_signal_qualitaet,
    berechne_snr_qualitaet, berechne_retry_qualitaet
)
from ui.sprachen import tr


class StatusKartenWidget(QFrame):
    """Visualisiert Signal-, Modulations- und Telemetriekennzahlen in 5 Panels."""

    def __init__(self, eltern=None):
        super().__init__(eltern)
        self.setProperty("class", "CardFrame")
        self._letzte_rssi_farbe = ""
        self._letzte_snr_farbe = ""
        self._letzte_retry_farbe = ""
        self._letzte_mod_style = ""
        self._erstelle_layout()

    def _linie(self) -> QFrame:
        linie = QFrame()
        linie.setFrameShape(QFrame.Shape.VLine)
        linie.setStyleSheet("background-color: #222222; max-width: 1px;")
        return linie

    def _erstelle_layout(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)

        # Panel 1: Zielnetzwerk & Kanal
        p1 = QVBoxLayout()
        self.lbl_titel_ziel = QLabel("MESSZIEL & KANAL")
        self.lbl_titel_ziel.setStyleSheet("color: #777777; font-size: 10px; font-weight: 700;")
        self.lbl_ziel_ssid = QLabel("Warte auf Ziel...")
        self.lbl_ziel_ssid.setStyleSheet("font-size: 14px; font-weight: 700; color: #ffffff;")
        self.lbl_ziel_bssid = QLabel("BSSID: --")
        self.lbl_ziel_bssid.setStyleSheet("font-size: 10px; color: #777777; font-family: monospace;")
        self.lbl_kanal_info = QLabel("Kanal: --")
        self.lbl_kanal_info.setStyleSheet("font-size: 10px; font-weight: 600; color: #38bdf8;")
        for w in (self.lbl_titel_ziel, self.lbl_ziel_ssid, self.lbl_ziel_bssid, self.lbl_kanal_info):
            p1.addWidget(w)
        layout.addLayout(p1, 2)
        layout.addWidget(self._linie())

        # Panel 2: Signalpegel & SNR
        p2 = QVBoxLayout()
        self.lbl_titel_signal = QLabel("SIGNALSTÄRKE & SNR")
        self.lbl_titel_signal.setStyleSheet("color: #777777; font-size: 10px; font-weight: 700;")
        rssi_zeile = QHBoxLayout()
        self.lbl_rssi_wert = QLabel("--")
        self.lbl_rssi_wert.setStyleSheet("font-size: 28px; font-weight: 800; color: #22c55e; font-family: monospace;")
        self.lbl_rssi_einheit = QLabel("dBm")
        self.lbl_rssi_einheit.setStyleSheet("font-size: 12px; font-weight: 600; color: #777777; margin-bottom: 3px;")
        self.lbl_rssi_einheit.setAlignment(Qt.AlignmentFlag.AlignBottom)
        rssi_zeile.addWidget(self.lbl_rssi_wert)
        rssi_zeile.addWidget(self.lbl_rssi_einheit)
        rssi_zeile.addStretch()

        self.lbl_rssi_roh = QLabel("Rohwert: -- dBm")
        self.lbl_rssi_roh.setStyleSheet("font-size: 10px; color: #777777;")
        self.lbl_snr_rauschen = QLabel("SNR: -- dB | Noise: -- dBm")
        self.lbl_snr_rauschen.setStyleSheet("font-size: 10px; font-weight: 600; color: #38bdf8;")
        self.signal_balken = QProgressBar()
        self.signal_balken.setRange(0, 100)
        self.signal_balken.setValue(0)
        self.signal_balken.setFixedHeight(8)
        p2.addWidget(self.lbl_titel_signal)
        p2.addLayout(rssi_zeile)
        p2.addWidget(self.lbl_rssi_roh)
        p2.addWidget(self.lbl_snr_rauschen)
        p2.addWidget(self.signal_balken)
        layout.addLayout(p2, 2)
        layout.addWidget(self._linie())

        # Panel 3: 10-Sekunden Statistik & Retry-Rate
        p3 = QVBoxLayout()
        self.lbl_titel_10s = QLabel("LETZTE 10 SEKUNDEN")
        self.lbl_titel_10s.setStyleSheet("color: #777777; font-size: 10px; font-weight: 700;")
        self.lbl_10s_minmax = QLabel("Min: -- | Max: --")
        self.lbl_10s_minmax.setStyleSheet("font-size: 12px; font-weight: 700; color: #38bdf8; font-family: monospace;")
        self.lbl_10s_delta = QLabel("Schwankung: 0.0 dB")
        self.lbl_10s_delta.setStyleSheet("font-size: 10px; font-weight: 600; color: #eab308; font-family: monospace;")
        self.lbl_retry_rate = QLabel("Retry-Rate: 0.0 %")
        self.lbl_retry_rate.setStyleSheet("font-size: 10px; font-weight: 600; color: #22c55e; font-family: monospace;")
        self.lbl_10s_status = QLabel("Warte auf Signal")
        self.lbl_10s_status.setStyleSheet("font-size: 9px; color: #666666;")
        for w in (self.lbl_titel_10s, self.lbl_10s_minmax, self.lbl_10s_delta, self.lbl_retry_rate, self.lbl_10s_status):
            p3.addWidget(w)
        layout.addLayout(p3, 2)
        layout.addWidget(self._linie())

        # Panel 4: Modulation & PHY
        p4 = QVBoxLayout()
        self.lbl_titel_mod = QLabel("MODULATION & PHY-MODUS")
        self.lbl_titel_mod.setStyleSheet("color: #777777; font-size: 10px; font-weight: 700;")
        self.lbl_mod_badge = QLabel("Warte auf Signal")
        self.lbl_mod_badge.setProperty("class", "ModBadge")
        self.lbl_mod_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_phy_info = QLabel("PHY: -- | MCS: --")
        self.lbl_phy_info.setStyleSheet("font-size: 10px; color: #777777; font-family: monospace;")
        for w in (self.lbl_titel_mod, self.lbl_mod_badge, self.lbl_phy_info):
            p4.addWidget(w)
        layout.addLayout(p4, 2)
        layout.addWidget(self._linie())

        # Panel 5: System-Telemetrie
        p5 = QVBoxLayout()
        self.lbl_titel_telem = QLabel("SYSTEM-TELEMETRIE (60s)")
        self.lbl_titel_telem.setStyleSheet("color: #777777; font-size: 10px; font-weight: 700;")
        self.lbl_telemetrie_rate = QLabel("Abtastrate: 0.0 Hz")
        self.lbl_telemetrie_rate.setStyleSheet("font-size: 10px; font-weight: 600; color: #38bdf8;")
        self.lbl_telemetrie_pakete = QLabel("Pakete gesamt: 0")
        self.lbl_telemetrie_pakete.setStyleSheet("font-size: 9px; color: #777777;")
        self.lbl_telemetrie_extrema = QLabel("Min: -- | Max: --")
        self.lbl_telemetrie_extrema.setStyleSheet("font-size: 9px; color: #777777; font-family: monospace;")
        for w in (self.lbl_titel_telem, self.lbl_telemetrie_rate, self.lbl_telemetrie_pakete, self.lbl_telemetrie_extrema):
            p5.addWidget(w)
        layout.addLayout(p5, 2)

    def aktualisiere_messung(self, ssid: str, bssid: str, kanal: int,
                             roh_rssi: float, ema_rssi: float,
                             mod: str, phy: str, mcs: int,
                             rate_hz: float, pakete_gesamt: int,
                             noise_floor: float = -95.0, snr: float = 0.0,
                             retry_rate: float = 0.0):
        """Aktualisiert alle Anzeigen mit den neuesten Messwerten."""
        # Panel 1
        self.lbl_ziel_ssid.setText(ssid if ssid else tr("waiting_data"))
        self.lbl_ziel_bssid.setText(tr("bssid_fmt", bssid=bssid))
        band = "5 GHz" if kanal > 14 else "2.4 GHz"
        self.lbl_kanal_info.setText(tr("channel_fmt", ch=kanal, band=band))

        # Panel 2
        farbe, status_text, pct = berechne_signal_qualitaet(ema_rssi)
        self.lbl_rssi_wert.setText(f"{ema_rssi:+.0f}" if ema_rssi > -99.0 else "--")
        if farbe != self._letzte_rssi_farbe:
            self.lbl_rssi_wert.setStyleSheet(f"font-size: 28px; font-weight: 800; color: {farbe}; font-family: monospace;")
            self._letzte_rssi_farbe = farbe
        self.lbl_rssi_roh.setText(f"{tr('raw_lbl')}: {roh_rssi:+.0f} dBm" if roh_rssi > -99.0 else f"{tr('raw_lbl')}: -- dBm")
        self.signal_balken.setValue(int(round(pct)))

        snr_farbe, _ = berechne_snr_qualitaet(snr)
        self.lbl_snr_rauschen.setText(f"SNR: {snr:.1f} dB | Noise: {noise_floor:.0f} dBm")
        if snr_farbe != self._letzte_snr_farbe:
            self.lbl_snr_rauschen.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {snr_farbe};")
            self._letzte_snr_farbe = snr_farbe

        # Panel 3: Retry-Rate
        retry_farbe, _ = berechne_retry_qualitaet(retry_rate)
        self.lbl_retry_rate.setText(f"Retry-Rate: {retry_rate:.1f} %")
        if retry_farbe != self._letzte_retry_farbe:
            self.lbl_retry_rate.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {retry_farbe}; font-family: monospace;")
            self._letzte_retry_farbe = retry_farbe

        # Panel 4: Modulation
        bg_col, rand_col, text_col = "#1c1c1c", "#3a3a3a", "#ffffff"
        for m_key, f_tupel in MODULATION_FARBEN.items():
            if m_key.lower() in mod.lower():
                bg_col, rand_col, text_col = f_tupel
                break
        self.lbl_mod_badge.setText(mod)
        mod_style = f"{bg_col}_{rand_col}_{text_col}"
        if mod_style != self._letzte_mod_style:
            self.lbl_mod_badge.setStyleSheet(
                f"background-color: {bg_col}; border: 1.5px solid {rand_col}; color: {text_col}; "
                f"border-radius: 4px; padding: 3px 8px; font-weight: 800; font-family: monospace; font-size: 11px;"
            )
            self._letzte_mod_style = mod_style
        self.lbl_phy_info.setText(f"PHY: {phy} | MCS: {mcs}")

        # Panel 5: Telemetrie
        self.lbl_telemetrie_rate.setText(tr("sample_rate", rate=rate_hz))
        self.lbl_telemetrie_pakete.setText(tr("total_packets", count=pakete_gesamt))

    def aktualisiere_kurzzeit_statistik(self, min_rssi: float, max_rssi: float, delta_rssi: float):
        """Aktualisiert die 10-Sekunden Min/Max- und Dynamikwerte."""
        if min_rssi > -99.0 and max_rssi > -99.0:
            self.lbl_10s_minmax.setText(tr("min_max_fmt", min=min_rssi, max=max_rssi))
            self.lbl_10s_delta.setText(tr("fluctuation", delta=delta_rssi))
            if delta_rssi < 3.0:
                self.lbl_10s_status.setText(tr("sig_stable"))
                self.lbl_10s_status.setStyleSheet("font-size: 9px; color: #22c55e;")
            elif delta_rssi <= 8.0:
                self.lbl_10s_status.setText(tr("sig_moderate"))
                self.lbl_10s_status.setStyleSheet("font-size: 9px; color: #eab308;")
            else:
                self.lbl_10s_status.setText(tr("sig_jitter"))
                self.lbl_10s_status.setStyleSheet("font-size: 9px; color: #ef4444;")
        else:
            self.lbl_10s_minmax.setText("Min: -- | Max: --")
            self.lbl_10s_delta.setText("Schwankung: 0.0 dB")
            self.lbl_10s_status.setText(tr("waiting_data"))

    def aktualisiere_telemetrie_extrema(self, min_val: float, max_val: float):
        if min_val > -99.0 and max_val > -99.0:
            self.lbl_telemetrie_extrema.setText(tr("min_max_fmt", min=min_val, max=max_val))
        else:
            self.lbl_telemetrie_extrema.setText("Min: -- | Max: --")

    def aktualisiere_sprache(self):
        """Aktualisiert Panel-Titel bei Sprachwechsel."""
        self.lbl_titel_ziel.setText(tr("card_target_title"))
        self.lbl_titel_signal.setText(tr("card_signal_title"))
        self.lbl_titel_10s.setText(tr("card_10s_title"))
        self.lbl_titel_mod.setText(tr("card_mod_title"))
        self.lbl_titel_telem.setText(tr("card_telem_title"))


class ZielKonfigWidget(QWidget):
    """Bedienleiste fuer Zielselektion, BSSID-Arretierung, Kanal und Abtastrate."""
    konfiguration_gesendet = pyqtSignal(str, str, int, int)
    scan_geklickt = pyqtSignal()

    def __init__(self, eltern=None):
        super().__init__(eltern)
        self._erstelle_layout()

    def _erstelle_layout(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        self.lbl_titel = QLabel()
        self.lbl_titel.setStyleSheet("font-weight: 700; color: #a0a0a0; font-size: 11px;")
        layout.addWidget(self.lbl_titel)

        self.lbl_ssid = QLabel()
        layout.addWidget(self.lbl_ssid)

        self.combo_ziel_ssid = QComboBox()
        self.combo_ziel_ssid.setEditable(True)
        self.combo_ziel_ssid.setMinimumWidth(180)
        self.combo_ziel_ssid.setProperty("class", "ProminentSSID")
        layout.addWidget(self.combo_ziel_ssid, 2)

        self.btn_scan = QPushButton()
        self.btn_scan.clicked.connect(self.scan_geklickt.emit)
        layout.addWidget(self.btn_scan)

        self.lbl_bssid = QLabel()
        layout.addWidget(self.lbl_bssid)

        self.txt_ziel_bssid = QLineEdit()
        self.txt_ziel_bssid.setMaximumWidth(135)
        self.txt_ziel_bssid.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout.addWidget(self.txt_ziel_bssid)

        self.lbl_kanal = QLabel()
        layout.addWidget(self.lbl_kanal)

        self.spin_ziel_kanal = QSpinBox()
        self.spin_ziel_kanal.setRange(1, 14)
        self.spin_ziel_kanal.setValue(6)
        self.spin_ziel_kanal.setFixedWidth(75)
        self.spin_ziel_kanal.editingFinished.connect(self._anwenden_geklickt)
        layout.addWidget(self.spin_ziel_kanal)

        self.lbl_rate = QLabel()
        layout.addWidget(self.lbl_rate)

        self.combo_ziel_rate = QComboBox()
        self.combo_ziel_rate.addItem("1 Hz", 1)
        self.combo_ziel_rate.addItem("5 Hz", 5)
        self.combo_ziel_rate.addItem("10 Hz", 10)
        self.combo_ziel_rate.setCurrentIndex(2)  # Standard: 10 Hz
        self.combo_ziel_rate.setFixedWidth(85)
        self.combo_ziel_rate.currentIndexChanged.connect(self._anwenden_geklickt)
        layout.addWidget(self.combo_ziel_rate)

        self.btn_anwenden = QPushButton()
        self.btn_anwenden.setProperty("class", "ApplyButton")
        self.btn_anwenden.clicked.connect(self._anwenden_geklickt)
        layout.addWidget(self.btn_anwenden)

    @property
    def abtastrate(self) -> int:
        """Gibt die aktuell gewaehlte Abtastrate als Ganzzahl (1, 5 oder 10) zurueck."""
        data = self.combo_ziel_rate.currentData()
        if data is not None:
            return int(data)
        txt = self.combo_ziel_rate.currentText()
        import re
        m = re.search(r"\d+", txt)
        return int(m.group(0)) if m else 10

    @property
    def spin_ziel_rate(self):
        """Rueckwaertskompatible Schnittstelle fuer externe Aufrufe."""
        class _RateProxy:
            def __init__(proxy_self, combo):
                proxy_self._combo = combo
            def value(proxy_self):
                return self.abtastrate
            def setValue(proxy_self, val):
                idx = self.combo_ziel_rate.findData(val)
                if idx >= 0:
                    self.combo_ziel_rate.setCurrentIndex(idx)
        return _RateProxy(self.combo_ziel_rate)

    def bereinigte_ssid(self) -> str:
        """Gibt die reine SSID ohne angehängte Signal- und Kanal-Metadaten zurück."""
        idx = self.combo_ziel_ssid.currentIndex()
        txt = self.combo_ziel_ssid.currentText().strip()
        daten = self.combo_ziel_ssid.itemData(idx)
        if daten and isinstance(daten, tuple) and len(daten) >= 1:
            echte_ssid = str(daten[0]).strip()
            if txt.startswith(echte_ssid):
                return echte_ssid
        import re
        txt = re.sub(r"\s*\([+-]?\d+\s*dBm,\s*Ch\s*\d+\)$", "", txt, flags=re.IGNORECASE)
        return txt.strip()

    def _anwenden_geklickt(self):
        self.konfiguration_gesendet.emit(
            self.bereinigte_ssid(),
            self.txt_ziel_bssid.text().strip(),
            self.spin_ziel_kanal.value(),
            self.abtastrate
        )

    def aktualisiere_sprache(self):
        self.lbl_titel.setText(tr("target_cfg_title"))
        self.lbl_ssid.setText(tr("ssid_lbl"))
        self.combo_ziel_ssid.lineEdit().setPlaceholderText(tr("ssid_placeholder"))
        self.btn_scan.setText(tr("scan_networks"))
        self.lbl_bssid.setText(tr("bssid_lbl"))
        self.txt_ziel_bssid.setPlaceholderText(tr("bssid_placeholder"))
        self.lbl_kanal.setText(tr("channel_lbl"))
        self.lbl_rate.setText(tr("rate_lbl"))
        self.btn_anwenden.setText(tr("apply_filter"))
