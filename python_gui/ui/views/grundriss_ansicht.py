"""
WLAN Signal-Tester - Grundriss & Signal-Heatmap (grundriss_ansicht.py)
Visualisiert Signalstaerken raeumlich auf Grundrissen (SVG/PNG) mit IDW-Interpolation.
Optimiert fuer maximale Flaechenausnutzung mit schlanker rechter Steuerungsleiste.
"""

import os
import csv
import math
import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QSlider, QFrame, QMessageBox, QSplitter, QInputDialog,
    QComboBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QImage, QPixmap

try:
    from PyQt6.QtSvg import QSvgRenderer
    SVG_VERFUEGBAR = True
except ImportError:
    SVG_VERFUEGBAR = False

from ui.sprachen import tr, is_rtl


# Farbstufen fuer die Signalstaerke
FARBSTUFEN = [
    {"grenze": -80.0, "farbe": QColor(220, 38, 38)},   # Rot (< -80 dBm)
    {"grenze": -70.0, "farbe": QColor(249, 115, 22)},  # Orange (-80..-70)
    {"grenze": -60.0, "farbe": QColor(234, 179, 8)},   # Gelb (-70..-60)
    {"grenze": -50.0, "farbe": QColor(132, 204, 22)},  # Hellgruen (-60..-50)
    {"grenze": 0.0,   "farbe": QColor(22, 163, 74)}    # Dunkelgruen (> -50)
]


def farbe_fuer_signal(rssi: float) -> QColor:
    """Ermittelt den passenden Farbwert fuer einen RSSI-Pegel."""
    if rssi is None:
        return QColor(80, 80, 80)
    for stufe in FARBSTUFEN:
        if rssi < stufe["grenze"]:
            return stufe["farbe"]
    return FARBSTUFEN[-1]["farbe"]


class Messpunkt:
    """Repraesentiert einen Messpunkt auf dem Grundriss."""
    def __init__(self, punkt_id: int, x: float, y: float, ssid: str = ""):
        self.id = punkt_id
        self.rel_x = x
        self.rel_y = y
        self.rssi = None
        self.ssid = ssid.strip()

    @property
    def name(self) -> str:
        return tr("fp_point_name", id=self.id)


class GrundrissFlaeche(QWidget):
    """Zeichenflaeche fuer Grundriss, Messpunkte und interpolierte Heatmap."""
    punkt_ausgewaehlt = pyqtSignal(int)
    punkt_hinzugefuegt = pyqtSignal(int)

    def __init__(self, eltern=None):
        super().__init__(eltern)
        self.setMinimumSize(300, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.svg_zeichner = None
        self.hintergrund_bild = None
        self.punkte = []
        self.ausgewaehlter_index = -1
        self.heatmap_bild = None
        self.zeige_heatmap = True
        self.transparenz = 0.55
        self.aktives_filter_netz = ""

    def bild_bereich(self) -> QRectF:
        """Berechnet die zentrierte Darstellungsflaeche unter Wahrung der Proportionen."""
        breite, hoehe = float(self.width()), float(self.height())
        if breite <= 10 or hoehe <= 10:
            return QRectF(0, 0, 100, 100)

        bw, bh = breite, hoehe
        if self.svg_zeichner and self.svg_zeichner.isValid():
            groesse = self.svg_zeichner.defaultSize()
            if groesse.width() > 0 and groesse.height() > 0:
                bw, bh = float(groesse.width()), float(groesse.height())
        elif self.hintergrund_bild and not self.hintergrund_bild.isNull():
            bw, bh = float(self.hintergrund_bild.width()), float(self.hintergrund_bild.height())

        faktor = min(breite / bw, hoehe / bh)
        ziel_w, ziel_h = bw * faktor, bh * faktor
        return QRectF((breite - ziel_w) / 2.0, (hoehe - ziel_h) / 2.0, ziel_w, ziel_h)

    def lade_grundriss(self, pfad: str):
        """Laedt eine SVG- oder Bilddatei als Grundriss."""
        self.svg_zeichner = None
        self.hintergrund_bild = None
        if pfad.lower().endswith(".svg") and SVG_VERFUEGBAR:
            self.svg_zeichner = QSvgRenderer(pfad)
        else:
            self.hintergrund_bild = QPixmap(pfad)
        self.berechne_heatmap()
        self.update()

    def punkt_hinzufuegen(self, x: float, y: float, ssid: str = ""):
        """Fuegt einen neuen Messpunkt mit relativen Koordinaten (0.0 bis 1.0) hinzu."""
        neuer = Messpunkt(len(self.punkte) + 1, max(0.0, min(1.0, x)), max(0.0, min(1.0, y)), ssid=ssid)
        self.punkte.append(neuer)
        self.ausgewaehlter_index = len(self.punkte) - 1
        self.punkt_hinzugefuegt.emit(neuer.id)
        self.update()

    def gewaehlten_punkt_loeschen(self):
        """Loescht den aktuell ausgewaehlten Messpunkt."""
        if 0 <= self.ausgewaehlter_index < len(self.punkte):
            self.punkte.pop(self.ausgewaehlter_index)
            for i, p in enumerate(self.punkte):
                p.id = i + 1
            self.ausgewaehlter_index = min(self.ausgewaehlter_index, len(self.punkte) - 1)
            self.berechne_heatmap()
            self.update()

    def alle_punkte_loeschen(self):
        """Loescht alle Messpunkte."""
        self.punkte.clear()
        self.ausgewaehlter_index = -1
        self.heatmap_bild = None
        self.update()

    def berechne_heatmap(self, ziel_ssid: str = None):
        """Interpoliert die Signalstaerke auf einem 200x200 Raster mittels IDW."""
        if ziel_ssid is not None:
            self.aktives_filter_netz = ziel_ssid.strip()

        gemessen = [
            p for p in self.punkte
            if p.rssi is not None and (
                not self.aktives_filter_netz or
                not getattr(p, "ssid", "") or
                p.ssid.lower() == self.aktives_filter_netz.lower()
            )
        ]

        if not gemessen:
            self.heatmap_bild = None
            self.update()
            return

        gw, gh = 200, 200
        xs = np.linspace(0.0, 1.0, gw, dtype=np.float32)
        ys = np.linspace(0.0, 1.0, gh, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)

        if len(gemessen) == 1:
            p = gemessen[0]
            dist = np.sqrt((gx - p.rel_x)**2 + (gy - p.rel_y)**2)
            raster_rssi = p.rssi - 25.0 * dist
        else:
            zaehler = np.zeros((gh, gw), dtype=np.float32)
            nenner = np.zeros((gh, gw), dtype=np.float32)
            for p in gemessen:
                dist = np.sqrt((gx - p.rel_x)**2 + (gy - p.rel_y)**2)
                gew = 1.0 / (dist**2.0 + 0.001)
                zaehler += gew * p.rssi
                nenner += gew
            raster_rssi = zaehler / nenner

        alpha = int(round(self.transparenz * 255))
        rgba = np.zeros((gh, gw, 4), dtype=np.uint8)
        rgba[:] = [220, 38, 38, alpha]                                                 # < -80
        rgba[(raster_rssi >= -80.0) & (raster_rssi < -70.0)] = [249, 115, 22, alpha]  # -80..-70
        rgba[(raster_rssi >= -70.0) & (raster_rssi < -60.0)] = [234, 179, 8, alpha]   # -70..-60
        rgba[(raster_rssi >= -60.0) & (raster_rssi < -50.0)] = [132, 204, 22, alpha] # -60..-50
        rgba[raster_rssi >= -50.0] = [22, 163, 74, alpha]                             # > -50

        self.heatmap_bild = QImage(rgba.data, gw, gh, gw * 4, QImage.Format.Format_RGBA8888).copy()
        self.update()

    def mousePressEvent(self, ereignis):
        if ereignis.button() != Qt.MouseButton.LeftButton:
            return
        bereich = self.bild_bereich()
        pos = ereignis.position()
        if not bereich.contains(pos):
            return

        x_rel = (pos.x() - bereich.left()) / bereich.width()
        y_rel = (pos.y() - bereich.top()) / bereich.height()

        for i, pt in enumerate(self.punkte):
            px = bereich.left() + pt.rel_x * bereich.width()
            py = bereich.top() + pt.rel_y * bereich.height()
            if math.hypot(pos.x() - px, pos.y() - py) <= 18.0:
                self.ausgewaehlter_index = i
                self.punkt_ausgewaehlt.emit(i)
                self.update()
                return

        self.punkt_hinzufuegen(x_rel, y_rel, ssid=self.aktives_filter_netz)

    def paintEvent(self, _):
        maler = QPainter(self)
        maler.setRenderHint(QPainter.RenderHint.Antialiasing)
        maler.fillRect(self.rect(), QColor("#080808"))

        bereich = self.bild_bereich()
        if self.svg_zeichner and self.svg_zeichner.isValid():
            self.svg_zeichner.render(maler, bereich)
        elif self.hintergrund_bild and not self.hintergrund_bild.isNull():
            maler.drawPixmap(bereich.toRect(), self.hintergrund_bild)
        else:
            maler.setPen(QColor("#555555"))
            maler.setFont(QFont("Segoe UI", 11))
            maler.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("fp_no_file"))

        if self.zeige_heatmap and self.heatmap_bild:
            maler.drawImage(bereich, self.heatmap_bild)

        schrift = QFont("Segoe UI", 9, QFont.Weight.Bold)
        maler.setFont(schrift)
        for i, pt in enumerate(self.punkte):
            px = bereich.left() + pt.rel_x * bereich.width()
            py = bereich.top() + pt.rel_y * bereich.height()
            ausgewaehlt = (i == self.ausgewaehlter_index)

            farbe = farbe_fuer_signal(pt.rssi)
            text_rssi = f"{pt.rssi:.0f} dBm" if pt.rssi is not None else tr("fp_open")
            radius = 13 if ausgewaehlt else 11

            maler.setBrush(QBrush(farbe))
            maler.setPen(QPen(QColor("#00e5ff") if ausgewaehlt else QColor("#ffffff"), 2.0 if ausgewaehlt else 1.5))
            maler.drawEllipse(QPointF(px, py), radius, radius)

            maler.setPen(QColor("#ffffff"))
            maler.drawText(QRectF(px - 15, py - 9, 30, 18), Qt.AlignmentFlag.AlignCenter, str(pt.id))
            maler.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            maler.drawText(QRectF(px - 40, py + radius + 2, 80, 16), Qt.AlignmentFlag.AlignCenter, text_rssi)
            maler.setFont(schrift)


class GrundrissWidget(QWidget):
    """
    Haupt-Widget fuer Grundriss & Heatmap mit extragroßer Karte
    und schlanker rechter Bedienleiste.
    """

    def __init__(self, eltern=None):
        super().__init__(eltern)
        self.aktuelles_live_signal = None
        self.aktueller_dateipfad = ""
        self._erstelle_oberflaeche()
        self.aktualisiere_sprache()

        # Standard-Grundriss laden wenn vorhanden
        basis_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        such_pfade = [
            os.path.join(basis_dir, "sample_floorplan.svg"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_floorplan.svg"),
            os.path.join(os.getcwd(), "sample_floorplan.svg"),
        ]
        standard_svg = next((p for p in such_pfade if os.path.exists(p)), "")
        if standard_svg:
            self.flaeche.lade_grundriss(standard_svg)
            self.aktueller_dateipfad = standard_svg
            self.lbl_datei_info.setText(tr("fp_loaded", file=os.path.basename(standard_svg)))

    def _erstelle_oberflaeche(self):
        haupt_layout = QVBoxLayout(self)
        haupt_layout.setContentsMargins(6, 4, 6, 4)
        haupt_layout.setSpacing(6)

        # 1. Obere Werkzeugleiste
        werkzeug = QFrame()
        werkzeug.setStyleSheet("background-color: #121212; border: 1px solid #242424; border-radius: 4px;")
        leiste = QHBoxLayout(werkzeug)
        leiste.setContentsMargins(8, 4, 8, 4)
        leiste.setSpacing(8)

        self.btn_laden = QPushButton()
        self.btn_laden.setProperty("class", "PrimaryButton")
        self.btn_laden.clicked.connect(self.datei_auswaehlen)
        leiste.addWidget(self.btn_laden)

        self.lbl_datei_info = QLabel()
        self.lbl_datei_info.setStyleSheet("color: #777777; font-size: 11px;")
        leiste.addWidget(self.lbl_datei_info)

        leiste.addSpacing(16)

        self.lbl_netz_auswahl = QLabel("WLAN für Heatmap:")
        self.lbl_netz_auswahl.setStyleSheet("color: #999999; font-size: 11px; font-weight: 600;")
        leiste.addWidget(self.lbl_netz_auswahl)

        self.combo_heatmap_netz = QComboBox()
        self.combo_heatmap_netz.setStyleSheet(
            "background-color: #141414; color: #00e5ff; font-weight: 700; "
            "border: 1px solid #2e2e2e; padding: 2px 8px; border-radius: 4px; min-width: 140px; font-size: 11px;"
        )
        self.combo_heatmap_netz.currentTextChanged.connect(self._netzwerk_ausgewaehlt)
        leiste.addWidget(self.combo_heatmap_netz)

        leiste.addStretch()

        self.lbl_live_signal = QLabel()
        self.lbl_live_signal.setFixedHeight(26)
        self.lbl_live_signal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_live_signal.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #00e5ff; font-family: monospace; "
            "padding: 2px 10px; background-color: #141414; border: 1px solid #2b2b2b; border-radius: 4px;"
        )
        leiste.addWidget(self.lbl_live_signal)
        haupt_layout.addWidget(werkzeug)

        # 2. Splitter: Grundrissflaeche links (riesig), schlanke Steuerungsleiste rechts
        self.teiler = QSplitter(Qt.Orientation.Horizontal)
        self.flaeche = GrundrissFlaeche()
        self.flaeche.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.teiler.addWidget(self.flaeche)

        # Schlanker rechter Rahmen (Kompakte Breite von ~280px)
        self.rahmen = QFrame()
        self.rahmen.setMinimumWidth(250)
        self.rahmen.setMaximumWidth(290)
        self.rahmen.setStyleSheet("background-color: #121212; border: 1px solid #242424; border-radius: 4px;")

        r_lay = QVBoxLayout(self.rahmen)
        r_lay.setContentsMargins(6, 6, 6, 6)
        r_lay.setSpacing(5)

        self.lbl_titel = QLabel()
        self.lbl_titel.setStyleSheet("font-weight: 700; color: #a0a0a0; font-size: 11px;")
        r_lay.addWidget(self.lbl_titel)

        self.lbl_hinweis = QLabel()
        self.lbl_hinweis.setStyleSheet("color: #777777; font-size: 10px;")
        self.lbl_hinweis.setWordWrap(True)
        r_lay.addWidget(self.lbl_hinweis)

        # Messpunkt-Tabelle
        self.tabelle = QTableWidget(0, 4)
        self.tabelle.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabelle.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tabelle.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tabelle.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tabelle.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabelle.cellClicked.connect(lambda z, s: setattr(self.flaeche, "ausgewaehlter_index", z) or self.flaeche.update())
        self.tabelle.cellDoubleClicked.connect(self.tabelle_doppelklick)
        r_lay.addWidget(self.tabelle, stretch=1)

        self.flaeche.punkt_ausgewaehlt.connect(self.tabelle.selectRow)
        self.flaeche.punkt_hinzugefuegt.connect(lambda _: self.aktualisiere_tabelle())

        # Aktion 1: Messwert erfassen
        self.btn_erfassen = QPushButton()
        self.btn_erfassen.setProperty("class", "PrimaryButton")
        self.btn_erfassen.clicked.connect(self.erfasse_aktuellen_punkt)
        r_lay.addWidget(self.btn_erfassen)

        # Aktion 2: Heatmap berechnen
        self.btn_neu_berechnen = QPushButton()
        self.btn_neu_berechnen.clicked.connect(lambda: self.flaeche.berechne_heatmap(self.flaeche.aktives_filter_netz))
        r_lay.addWidget(self.btn_neu_berechnen)

        # Aktion 3: Punkt löschen
        self.btn_punkt_loeschen = QPushButton()
        self.btn_punkt_loeschen.clicked.connect(lambda: self.flaeche.gewaehlten_punkt_loeschen() or self.aktualisiere_tabelle())
        r_lay.addWidget(self.btn_punkt_loeschen)

        # Aktion 4: Alle Punkte löschen
        self.btn_alle_loeschen = QPushButton()
        self.btn_alle_loeschen.clicked.connect(lambda: self.flaeche.alle_punkte_loeschen() or self.aktualisiere_tabelle())
        r_lay.addWidget(self.btn_alle_loeschen)

        # Aktion 5: Heatmap ein/ausblenden
        self.btn_toggle_hm = QPushButton()
        self.btn_toggle_hm.setCheckable(True)
        self.btn_toggle_hm.setChecked(True)
        self.btn_toggle_hm.clicked.connect(lambda aktiv: setattr(self.flaeche, "zeige_heatmap", aktiv) or self.flaeche.update())
        r_lay.addWidget(self.btn_toggle_hm)

        # Aktion 6: Deckkraft-Zeile (Beschriftung + Schieberegler)
        zeile_transparenz = QHBoxLayout()
        zeile_transparenz.setSpacing(6)
        self.lbl_transparenz = QLabel()
        self.lbl_transparenz.setStyleSheet("font-size: 11px; color: #888888;")
        zeile_transparenz.addWidget(self.lbl_transparenz)

        self.regler_alpha = QSlider(Qt.Orientation.Horizontal)
        self.regler_alpha.setRange(20, 90)
        self.regler_alpha.setValue(55)
        self.regler_alpha.valueChanged.connect(lambda v: setattr(self.flaeche, "transparenz", v / 100.0) or self.flaeche.berechne_heatmap())
        zeile_transparenz.addWidget(self.regler_alpha, 1)
        r_lay.addLayout(zeile_transparenz)

        # Aktion 7: Farbleiste der Signalstufen
        zeile_legende = QHBoxLayout()
        zeile_legende.setSpacing(2)
        self.legende_labels = []
        farben = ["#dc2626", "#f97316", "#eab308", "#84cc16", "#16a34a"]
        for col in farben:
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"background-color: {col}; color: #ffffff; padding: 2px 2px; font-size: 9px; font-weight: 700; border-radius: 2px;")
            zeile_legende.addWidget(lbl)
            self.legende_labels.append(lbl)
        r_lay.addLayout(zeile_legende)

        # Aktion 8 & 9: Export-Buttons untereinander
        self.btn_export_bild = QPushButton()
        self.btn_export_bild.clicked.connect(self.exportiere_bild)
        r_lay.addWidget(self.btn_export_bild)

        self.btn_export_csv = QPushButton()
        self.btn_export_csv.clicked.connect(self.exportiere_csv)
        r_lay.addWidget(self.btn_export_csv)

        self.teiler.addWidget(self.rahmen)

        # Splitter-Gewichtung: 100% des dynamischen Platzes fuer die Karte!
        self.teiler.setCollapsible(0, False)
        self.teiler.setCollapsible(1, False)
        self.teiler.setStretchFactor(0, 1)  # Grundrissflaeche dehnt sich maximal aus
        self.teiler.setStretchFactor(1, 0)  # Rechte Leiste bleibt schlank
        self.teiler.setSizes([1000, 275])

        haupt_layout.addWidget(self.teiler, stretch=1)

    def aktualisiere_sprache(self):
        """Aktualisiert alle Beschriftungen bei Sprachwechsel."""
        self.btn_laden.setText(tr("fp_load"))
        if not self.aktueller_dateipfad:
            self.lbl_datei_info.setText(tr("fp_no_file"))
        else:
            self.lbl_datei_info.setText(tr("fp_loaded", file=self.aktueller_dateipfad))

        sig_text = f"{self.aktuelles_live_signal:.1f} dBm" if self.aktuelles_live_signal and self.aktuelles_live_signal > -99.0 else "-- dBm"
        self.lbl_live_signal.setText(tr("fp_live", val=sig_text))

        self.lbl_titel.setText(tr("fp_points_title"))
        self.lbl_hinweis.setText(tr("fp_hint"))
        self.tabelle.setHorizontalHeaderLabels([tr("fp_col_pt"), "WLAN", tr("fp_col_val"), tr("fp_col_status")])
        self.btn_erfassen.setText(tr("fp_capture"))
        self.btn_neu_berechnen.setText(tr("fp_recompute"))
        self.btn_punkt_loeschen.setText(tr("fp_del_pt"))
        self.btn_alle_loeschen.setText(tr("fp_del_all"))
        self.btn_toggle_hm.setText(tr("fp_toggle_hm"))
        self.lbl_transparenz.setText(tr("fp_opacity"))

        texte = ["< -80", "-80..-70", "-70..-60", "-60..-50", "> -50"]
        for lbl, txt in zip(self.legende_labels, texte):
            lbl.setText(txt)

        self.btn_export_bild.setText(tr("fp_export_img"))
        self.btn_export_csv.setText(tr("fp_export_csv"))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        self.aktualisiere_tabelle()
        self.flaeche.update()

    def setze_verfuegbare_netze(self, netze: list[str]):
        """Aktualisiert die Auswahlliste der fuer die Kartierung verfuegbaren WLAN-Netze."""
        aktuell = self.combo_heatmap_netz.currentText()
        self.combo_heatmap_netz.blockSignals(True)
        self.combo_heatmap_netz.clear()

        ignoriert = {"", "warte auf ziel", "suche signal...", "suche signal", "unbekannt", "-- kein netz --", "--"}
        gueltig = [n for n in netze if n and n.strip() and n.strip().lower() not in ignoriert]

        if not gueltig:
            self.combo_heatmap_netz.addItem("-- Kein Netz --")
        else:
            for n in gueltig:
                self.combo_heatmap_netz.addItem(n)
            if aktuell in gueltig:
                self.combo_heatmap_netz.setCurrentText(aktuell)
            else:
                self.combo_heatmap_netz.setCurrentIndex(0)

        self.combo_heatmap_netz.blockSignals(False)
        self._netzwerk_ausgewaehlt(self.combo_heatmap_netz.currentText())

    def _netzwerk_ausgewaehlt(self, netz_name: str):
        ziel = "" if netz_name == "-- Kein Netz --" else netz_name.strip()
        self.flaeche.berechne_heatmap(ziel)
        self.aktualisiere_tabelle()

    def aktualisiere_live_signal(self, rssi: float):
        """Uebergibt das aktuelle Live-Signal des Signal-Analyzers an den Grundriss."""
        self.aktuelles_live_signal = rssi
        sig_str = f"{rssi:.1f} dBm" if rssi is not None and rssi > -99.0 else "-- dBm"
        self.lbl_live_signal.setText(tr("fp_live", val=sig_str))

    def erfasse_aktuellen_punkt(self):
        """Schreibt das aktuelle Live-Signal in den selektierten Messpunkt."""
        if not (0 <= self.flaeche.ausgewaehlter_index < len(self.flaeche.punkte)):
            QMessageBox.information(self, "Messpunkt", tr("fp_err_no_selection"))
            return

        if self.aktuelles_live_signal is None or self.aktuelles_live_signal <= -99.0:
            QMessageBox.warning(self, "Messung", tr("fp_err_no_signal"))
            return

        pt = self.flaeche.punkte[self.flaeche.ausgewaehlter_index]
        pt.rssi = round(self.aktuelles_live_signal, 1)

        netz = self.combo_heatmap_netz.currentText()
        if netz and netz != "-- Kein Netz --":
            pt.ssid = netz

        self.flaeche.berechne_heatmap(self.flaeche.aktives_filter_netz)
        self.aktualisiere_tabelle()
        self.flaeche.update()

        # Automatisch zum naechsten offenen Messpunkt springen
        if self.flaeche.ausgewaehlter_index + 1 < len(self.flaeche.punkte):
            self.flaeche.ausgewaehlter_index += 1
            self.tabelle.selectRow(self.flaeche.ausgewaehlter_index)
            self.flaeche.update()

    def aktualisiere_tabelle(self):
        """Aktualisiert Zeilen und Werte der Messpunkttabelle."""
        self.tabelle.setRowCount(len(self.flaeche.punkte))
        for i, pt in enumerate(self.flaeche.punkte):
            it_id = QTableWidgetItem(str(pt.id))
            it_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabelle.setItem(i, 0, it_id)

            it_ssid = QTableWidgetItem(pt.ssid if getattr(pt, "ssid", "") else "-")
            self.tabelle.setItem(i, 1, it_ssid)

            val_str = f"{pt.rssi:+.0f} dBm" if pt.rssi is not None else tr("fp_open")
            it_val = QTableWidgetItem(val_str)
            it_val.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if pt.rssi is not None:
                it_val.setForeground(QBrush(farbe_fuer_signal(pt.rssi)))
            self.tabelle.setItem(i, 2, it_val)

            stat_str = "OK" if pt.rssi is not None else tr("fp_open")
            it_stat = QTableWidgetItem(stat_str)
            it_stat.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tabelle.setItem(i, 3, it_stat)

        if 0 <= self.flaeche.ausgewaehlter_index < len(self.flaeche.punkte):
            self.tabelle.selectRow(self.flaeche.ausgewaehlter_index)

    def tabelle_doppelklick(self, zeile: int, spalte: int):
        """Erlaubt manuelle Eingabe eines RSSI-Werts per Doppelklick."""
        if 0 <= zeile < len(self.flaeche.punkte):
            pt = self.flaeche.punkte[zeile]
            v, ok = QInputDialog.getDouble(self, tr("fp_title"), f"RSSI (dBm) für Punkt {pt.id}:",
                                           pt.rssi if pt.rssi is not None else -65.0, -100.0, -10.0, 1)
            if ok:
                pt.rssi = round(v, 1)
                self.flaeche.berechne_heatmap(self.flaeche.aktives_filter_netz)
                self.aktualisiere_tabelle()
                self.flaeche.update()

    def datei_auswaehlen(self):
        """Oeffnet Dateidialog zum Laden eines Grundrisses."""
        filter_str = "Grundriss (*.svg *.png *.jpg *.jpeg);;SVG (*.svg);;Bilder (*.png *.jpg *.jpeg)"
        pfad, _ = QFileDialog.getOpenFileName(self, tr("fp_load"), "", filter_str)
        if pfad:
            self.flaeche.lade_grundriss(pfad)
            self.aktueller_dateipfad = os.path.basename(pfad)
            self.lbl_datei_info.setText(tr("fp_loaded", file=self.aktueller_dateipfad))

    def exportiere_bild(self):
        """Exportiert die aktuelle Grundrissflaeche inklusive Heatmap als PNG."""
        pfad, _ = QFileDialog.getSaveFileName(self, tr("fp_export_img"), "heatmap.png", "PNG-Bild (*.png)")
        if not pfad:
            return
        pixmap = QPixmap(self.flaeche.size())
        self.flaeche.render(pixmap)
        if pixmap.save(pfad, "PNG"):
            QMessageBox.information(self, tr("fp_export_img"), "Heatmap erfolgreich exportiert.")

    def exportiere_csv(self):
        """Exportiert alle Messpunkte als CSV-Datei."""
        pfad, _ = QFileDialog.getSaveFileName(self, tr("fp_export_csv"), "messpunkte.csv", "CSV-Datei (*.csv)")
        if not pfad:
            return
        try:
            with open(pfad, "w", newline="", encoding="utf-8") as f:
                schreiber = csv.writer(f, delimiter=";")
                schreiber.writerow(["Punkt_ID", "WLAN_SSID", "Rel_X", "Rel_Y", "RSSI_dBm"])
                for pt in self.flaeche.punkte:
                    schreiber.writerow([pt.id, getattr(pt, "ssid", ""), f"{pt.rel_x:.4f}", f"{pt.rel_y:.4f}", pt.rssi if pt.rssi is not None else ""])
            QMessageBox.information(self, tr("fp_export_csv"), "Messpunkte erfolgreich als CSV gespeichert.")
        except Exception as e:
            QMessageBox.critical(self, tr("fp_export_csv"), f"Fehler beim Speichern: {e}")

    def keyPressEvent(self, ereignis):
        if ereignis.key() == Qt.Key.Key_Space:
            self.erfasse_aktuellen_punkt()
            ereignis.accept()
        else:
            super().keyPressEvent(ereignis)


class GrundrissFenster(QMainWindow):
    """Eigenstaendiges Fenster (fuer Abwaertskompatibilitaet)."""
    def __init__(self, eltern=None):
        super().__init__(eltern)
        self.setWindowTitle(tr("fp_title"))
        self.resize(1100, 720)
        self.widget = GrundrissWidget(self)
        self.setCentralWidget(self.widget)
        self.flaeche = self.widget.flaeche
