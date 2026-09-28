"""
WLAN Signal-Tester - Netzwerk-Diagnose & Latenzanalyse (diagnose_ansicht.py)
Fuehrt aktive Verbindungstests durch:
1. Verbindungsaufbau & DHCP-Laufzeit (ms)
2. DNS-Auflösungszeit (ms)
3. Gateway-Ping zum lokalen Router (WLAN-Latenz)
4. Internet-Ping zu konfigurierbaren Gegenstellen (WAN-Latenz)
5. 60-Sekunden Live-Pingverlauf (Vergleich Router vs. Internet)
"""

import time
import socket
import subprocess
import re
from collections import deque

from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QProgressBar, QFrame, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import pyqtgraph as pg

from core.datenmodelle import DiagnoseErgebnis
from ui.sprachen import tr, is_rtl


class HostDiagnoseThread(QThread):
    """Fuehrt den einmaligen Basis-Benchmark auf dem PC aus."""
    status_signal = pyqtSignal(str)
    fertig_signal = pyqtSignal(object)

    DOMAINS = [
        "google.com", "cloudflare.com", "wikipedia.org", "apple.com",
        "microsoft.com", "amazon.com", "github.com", "heise.de"
    ]
    _domain_idx = 0

    def __init__(self, ziel_ssid: str, passwort: str = "", ping_ziel: str = "1.1.1.1", eltern=None):
        super().__init__(eltern)
        self.ziel_ssid = ziel_ssid
        self.passwort = passwort
        self.ping_ziel = self._loese_ziel_auf(ping_ziel)
        self.abgebrochen = False

    def abbrechen(self):
        self.abgebrochen = True

    @staticmethod
    def _loese_ziel_auf(ziel: str) -> str:
        s = (ziel or "").strip()
        if not s:
            return "1.1.1.1"
        if " " in s:
            s = s.split()[0]
        try:
            return socket.gethostbyname(s)
        except Exception:
            return s

    @staticmethod
    def _ping(ip: str, anzahl: int = 2) -> float:
        if not ip or ip == "--":
            return 0.0
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.run(
                ["ping", "-n", str(anzahl), "-w", "1000", ip],
                capture_output=True, text=True, startupinfo=info, timeout=4.0
            )
            m = re.search(r"(?:Mittelwert|Average)\s*=\s*(\d+)\s*ms", proc.stdout, re.IGNORECASE)
            if m:
                return float(m.group(1))
            werte = [float(w) for w in re.findall(r"(?:Zeit|time)[=<](\d+)\s*ms", proc.stdout, re.IGNORECASE)]
            if werte:
                return round(sum(werte) / len(werte), 1)
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _lese_netzwerkkonfiguration() -> tuple[str, str, str, str]:
        lokal, gw, mask, dns = "--", "--", "--", "--"
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, startupinfo=info, timeout=3.0)
            
            # Zerlege nach Adapter-Blöcken (Zeilen am Zeilenanfang ohne Einrückung)
            adapter_bloecke = re.split(r"\r?\n(?=[^\s])", proc.stdout)
            beste_wahl = None

            for block in adapter_bloecke:
                b_ip, b_gw, b_mask, b_dns = "--", "--", "--", "--"
                for zeile in block.splitlines():
                    zc = zeile.strip()
                    m_ip = re.search(r"IPv4[^\:]*:\s*([\d\.]+)", zc, re.IGNORECASE)
                    if m_ip:
                        ip = m_ip.group(1).strip()
                        if not ip.startswith("169.254."):
                            b_ip = ip
                    m_gw = re.search(r"(?:Default Gateway|Standardgateway)[^\:]*:\s*([\d\.]+)", zc, re.IGNORECASE)
                    if m_gw:
                        b_gw = m_gw.group(1).strip()
                    m_mask = re.search(r"(?:Subnet Mask|Subnetzmaske)[^\:]*:\s*([\d\.]+)", zc, re.IGNORECASE)
                    if m_mask:
                        b_mask = m_mask.group(1).strip()
                    m_dns = re.search(r"(?:DNS Servers|DNS-Server)[^\:]*:\s*([\d\.]+)", zc, re.IGNORECASE)
                    if m_dns and not m_dns.group(1).startswith("127."):
                        b_dns = m_dns.group(1).strip()

                if b_ip != "--" and b_gw != "--":
                    # Bevorzuge echte physische WLAN-Adapter vor virtuellen Switches
                    is_virt = "vethernet" in block.lower() or "virtual" in block.lower()
                    is_wifi = any(w in block.lower() for w in ["wireless", "wlan", "wi-fi"])
                    score = (2 if is_wifi else 1) - (2 if is_virt else 0)
                    if beste_wahl is None or score > beste_wahl[0]:
                        beste_wahl = (score, b_ip, b_gw, b_mask, b_dns)

            if beste_wahl:
                _, lokal, gw, mask, dns = beste_wahl
        except Exception:
            pass

        # Fallback über Socketverbindung
        if lokal == "--":
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                lokal = s.getsockname()[0]
                s.close()
            except Exception:
                pass

        return lokal, gw, mask, dns

    def _messe_dns(self, dns_ip: str) -> tuple[bool, float]:
        domain = self.DOMAINS[HostDiagnoseThread._domain_idx % len(self.DOMAINS)]
        HostDiagnoseThread._domain_idx += 1
        server = dns_ip if (dns_ip and dns_ip != "--") else "8.8.8.8"

        # 1. Direkte UDP-DNS-Anfrage an Port 53 zur Vermeidung des OS-Caches
        try:
            query = b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
            for part in domain.split("."):
                query += bytes([len(part)]) + part.encode("ascii")
            query += b"\x00\x00\x01\x00\x01"

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.5)
            t0 = time.perf_counter()
            sock.sendto(query, (server, 53))
            resp, _ = sock.recvfrom(512)
            dauer = (time.perf_counter() - t0) * 1000.0
            sock.close()
            if len(resp) >= 12:
                return True, round(dauer, 1)
        except Exception:
            pass

        # 2. Fallback ueber Standard-Socket
        try:
            t0 = time.perf_counter()
            socket.gethostbyname(domain)
            return True, max(0.5, round((time.perf_counter() - t0) * 1000.0, 1))
        except Exception:
            return False, 0.0

    def run(self):
        erg = DiagnoseErgebnis(internet_ziel=self.ping_ziel)
        t_start = time.time()

        self.status_signal.emit("Prüfe Netzwerk- und DHCP-Konfiguration...")
        lokal, gw, mask, dns = self._lese_netzwerkkonfiguration()
        erg.verbindungsdauer_ms = max(50, int((time.time() - t_start) * 1000))
        erg.lokale_ip = lokal
        erg.gateway_ip = gw
        erg.subnetz_maske = mask
        erg.dns_server = dns if dns != "--" else gw

        if lokal == "--":
            erg.verbindung_erfolgreich = False
            erg.status_nachricht = "Keine aktive IP-Adresse gefunden."
            self.fertig_signal.emit(erg)
            return

        erg.verbindung_erfolgreich = True
        if self.abgebrochen:
            return

        self.status_signal.emit("Teste DNS-Auflösungszeit...")
        erg.dns_ok, erg.dns_latenz_ms = self._messe_dns(erg.dns_server)
        if self.abgebrochen:
            return

        self.status_signal.emit(f"Pinge Gateway {gw} (WLAN-Strecke)...")
        erg.gateway_ping_ms = self._ping(gw, anzahl=2)
        if self.abgebrochen:
            return

        self.status_signal.emit(f"Pinge Internet-Ziel ({self.ping_ziel})...")
        i_ping = self._ping(self.ping_ziel, anzahl=2)
        if i_ping == 0.0 and self.ping_ziel == "1.1.1.1":
            i_ping = self._ping("8.8.8.8", anzahl=2)
        erg.internet_ping_ms = i_ping

        erg.status_nachricht = "Diagnose abgeschlossen. Starte Live-Pingverlauf..."
        self.fertig_signal.emit(erg)


class HostLivePingThread(QThread):
    """Pingt periodisch (jede Sekunde) Router und Internet fuer den Live-Graph."""
    ping_signal = pyqtSignal(float, float)

    def __init__(self, gateway_ip: str, ping_ziel: str = "1.1.1.1", eltern=None):
        super().__init__(eltern)
        self.gateway_ip = gateway_ip
        self.ping_ziel = ping_ziel if ping_ziel else "1.1.1.1"
        self.laeuft = True

    def stoppen(self):
        self.laeuft = False

    def _schnell_ping(self, ip: str) -> float:
        if not ip or ip == "--":
            return 0.0
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.run(
                ["ping", "-n", "1", "-w", "800", ip],
                capture_output=True, text=True, startupinfo=info, timeout=1.2
            )
            m = re.search(r"(?:Mittelwert|Average|Zeit|time)[=<](\d+)\s*ms", proc.stdout, re.IGNORECASE)
            if m:
                return float(m.group(1))
        except Exception:
            pass
        return 0.0

    def run(self):
        while self.laeuft:
            gw_ms = self._schnell_ping(self.gateway_ip)
            if not self.laeuft:
                break
            inet_ms = self._schnell_ping(self.ping_ziel)
            if inet_ms == 0.0 and self.laeuft and self.ping_ziel == "1.1.1.1":
                inet_ms = self._schnell_ping("8.8.8.8")

            if self.laeuft:
                self.ping_signal.emit(gw_ms, inet_ms)

            for _ in range(10):
                if not self.laeuft:
                    break
                time.sleep(0.1)


class NetzwerkDiagnoseWidget(QWidget):
    """Haupt-Widget fuer Netzwerk-Diagnose und Latenzverlauf."""

    def __init__(self, serial_worker=None, standard_ssid: str = "", eltern=None):
        super().__init__(eltern)
        self.serial_worker = serial_worker
        self.standard_ssid = standard_ssid
        self.host_thread = None
        self.live_ping_thread = None
        self.ist_aktiv = False
        self.aktuelles_ping_ziel = "1.1.1.1"

        # 60s Ringspeicher fuer das Diagramm
        self.ping_zeiten = deque()
        self.ping_gw_werte = deque()
        self.ping_inet_werte = deque()

        self.letzter_gw_ping = 0.0
        self.letzter_inet_ping = 0.0
        self.aktuelle_gateway_ip = ""

        self.letzter_connect_ms = None
        self.letzter_dns_ok = None
        self.letzter_dns_ms = None
        self.letzte_ip = "--"
        self.letzter_gw = "--"
        self.letzter_dns = "--"
        self.status_zustand = "ready"

        self._erstelle_layout()
        self.aktualisiere_sprache()

        if self.serial_worker:
            self.serial_worker.diagnose_status.connect(self._esp32_status)
            self.serial_worker.diagnose_ergebnis.connect(self._esp32_ergebnis)
            self.serial_worker.diagnose_ping.connect(self._esp32_ping)

    def setze_ziel_ssid(self, ssid: str):
        if not self.ist_aktiv and ssid:
            import re
            sauber = re.sub(r"\s*\([+-]?\d+\s*dBm,\s*Ch\s*\d+\)$", "", ssid.strip(), flags=re.IGNORECASE)
            self.txt_ssid.setText(sauber.strip())

    def setze_pruefer(self, modus: str):
        idx = self.combo_pruefer.findData(modus)
        if idx >= 0:
            self.combo_pruefer.setCurrentIndex(idx)

    def _ermittle_ping_ziel(self) -> str:
        text = self.combo_ping_ziel.currentText().strip()
        data = self.combo_ping_ziel.currentData()
        kandidat = data if (data and text.startswith(str(data))) else text
        if " " in kandidat:
            kandidat = kandidat.split()[0]
        try:
            return socket.gethostbyname(kandidat)
        except Exception:
            return kandidat if kandidat else "1.1.1.1"

    def _karte(self, titel: str) -> tuple[QFrame, QVBoxLayout, QLabel]:
        k = QFrame()
        k.setStyleSheet("background-color: #141414; border: 1px solid #222222; border-radius: 4px;")
        lay = QVBoxLayout(k)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        t = QLabel(titel.upper())
        t.setStyleSheet("font-size: 10px; font-weight: 700; color: #737373;")
        lay.addWidget(t)
        return k, lay, t

    def _erstelle_layout(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(6)

        # 1. Kopfbereich
        kopf = QVBoxLayout()
        kopf.setSpacing(2)
        self.lbl_titel = QLabel(tr("diag_title"))
        self.lbl_titel.setStyleSheet("font-size: 15px; font-weight: 800; color: #ffffff;")
        self.lbl_untertitel = QLabel(tr("diag_subtitle"))
        self.lbl_untertitel.setStyleSheet("font-size: 11px; color: #888888;")
        kopf.addWidget(self.lbl_titel)
        kopf.addWidget(self.lbl_untertitel)
        root.addLayout(kopf)

        # 2. Eingabeleiste
        leiste = QFrame()
        leiste.setStyleSheet("background-color: #121212; border: 1px solid #242424; border-radius: 4px;")
        l_lay = QHBoxLayout(leiste)
        l_lay.setContentsMargins(8, 6, 8, 6)
        l_lay.setSpacing(8)

        self.lbl_ssid = QLabel(tr("diag_ssid"))
        l_lay.addWidget(self.lbl_ssid)
        self.txt_ssid = QLineEdit(self.standard_ssid)
        self.txt_ssid.setPlaceholderText(tr("diag_ssid_placeholder"))
        l_lay.addWidget(self.txt_ssid, 2)

        self.lbl_pass = QLabel(tr("diag_pass"))
        l_lay.addWidget(self.lbl_pass)
        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_pass.setPlaceholderText(tr("diag_pass_placeholder"))
        l_lay.addWidget(self.txt_pass, 2)

        self.lbl_pruefer = QLabel(tr("diag_tester"))
        l_lay.addWidget(self.lbl_pruefer)
        self.combo_pruefer = QComboBox()
        self.combo_pruefer.addItem(tr("diag_tester_host"), "host")
        self.combo_pruefer.addItem(tr("diag_tester_esp32"), "esp32")
        l_lay.addWidget(self.combo_pruefer, 2)

        self.lbl_ping_ziel = QLabel(tr("diag_target"))
        l_lay.addWidget(self.lbl_ping_ziel)
        self.combo_ping_ziel = QComboBox()
        self.combo_ping_ziel.setEditable(True)
        self.combo_ping_ziel.addItem("1.1.1.1 (Cloudflare)", "1.1.1.1")
        self.combo_ping_ziel.addItem("8.8.8.8 (Google DNS)", "8.8.8.8")
        self.combo_ping_ziel.addItem("9.9.9.9 (Quad9)", "9.9.9.9")
        self.combo_ping_ziel.addItem("google.com", "google.com")
        self.combo_ping_ziel.setMinimumWidth(160)
        l_lay.addWidget(self.combo_ping_ziel, 2)

        self.btn_start_stop = QPushButton(tr("diag_start"))
        self.btn_start_stop.setProperty("class", "PrimaryButton")
        self.btn_start_stop.clicked.connect(self.umschalten)
        l_lay.addWidget(self.btn_start_stop)

        root.addWidget(leiste)

        # 3. 4 Metrik-Karten
        karten_lay = QHBoxLayout()
        karten_lay.setSpacing(6)

        # Karte 1: Verbindungsaufbau & DHCP
        k1, l1, self.lbl_t1 = self._karte(tr("diag_card_dhcp"))
        self.lbl_v1 = QLabel("--")
        self.lbl_v1.setStyleSheet("font-size: 24px; font-weight: 800; color: #22c55e; font-family: monospace;")
        self.lbl_s1 = QLabel(tr("diag_ready"))
        self.lbl_s1.setStyleSheet("font-size: 11px; color: #888888;")
        l1.addWidget(self.lbl_v1)
        l1.addWidget(self.lbl_s1)
        karten_lay.addWidget(k1)

        # Karte 2: DNS-Latenz
        k2, l2, self.lbl_t2 = self._karte(tr("diag_card_dns"))
        self.lbl_v2 = QLabel("--")
        self.lbl_v2.setStyleSheet("font-size: 24px; font-weight: 800; color: #38bdf8; font-family: monospace;")
        self.lbl_s2 = QLabel(tr("diag_ready"))
        self.lbl_s2.setStyleSheet("font-size: 11px; color: #888888;")
        l2.addWidget(self.lbl_v2)
        l2.addWidget(self.lbl_s2)
        karten_lay.addWidget(k2)

        # Karte 3: Router-Ping (WLAN)
        k3, l3, self.lbl_t3 = self._karte(tr("diag_card_gw"))
        self.lbl_v3 = QLabel("--")
        self.lbl_v3.setStyleSheet("font-size: 24px; font-weight: 800; color: #22c55e; font-family: monospace;")
        self.lbl_s3 = QLabel(tr("diag_ready"))
        self.lbl_s3.setStyleSheet("font-size: 11px; color: #888888;")
        l3.addWidget(self.lbl_v3)
        l3.addWidget(self.lbl_s3)
        karten_lay.addWidget(k3)

        # Karte 4: Internet-Ping (WAN)
        k4, l4, self.lbl_t4 = self._karte(tr("diag_card_inet"))
        self.lbl_v4 = QLabel("--")
        self.lbl_v4.setStyleSheet("font-size: 24px; font-weight: 800; color: #38bdf8; font-family: monospace;")
        self.lbl_s4 = QLabel(tr("diag_ready"))
        self.lbl_s4.setStyleSheet("font-size: 11px; color: #888888;")
        l4.addWidget(self.lbl_v4)
        l4.addWidget(self.lbl_s4)
        karten_lay.addWidget(k4)

        root.addLayout(karten_lay)

        # 4. Live-Pingverlauf (Diagramm)
        diagramm_rahmen = QFrame()
        diagramm_rahmen.setStyleSheet("background-color: #121212; border: 1px solid #242424; border-radius: 4px;")
        d_lay = QVBoxLayout(diagramm_rahmen)
        d_lay.setContentsMargins(8, 6, 8, 6)

        d_kopf = QHBoxLayout()
        self.lbl_diag_titel = QLabel(tr("diag_graph_title"))
        self.lbl_diag_titel.setStyleSheet("font-weight: 700; color: #a0a0a0; font-size: 11px;")
        d_kopf.addWidget(self.lbl_diag_titel)

        d_kopf.addSpacing(16)
        self.leg_gw = QLabel(tr("diag_leg_router"))
        self.leg_gw.setStyleSheet("color: #22c55e; font-weight: 700; font-size: 11px;")
        d_kopf.addWidget(self.leg_gw)

        self.leg_inet = QLabel(tr("diag_leg_internet"))
        self.leg_inet.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 11px;")
        d_kopf.addWidget(self.leg_inet)

        d_kopf.addStretch()
        self.lbl_ping_stats = QLabel("Router: -- ms | Internet: -- ms | Delta: -- ms")
        self.lbl_ping_stats.setStyleSheet("color: #777777; font-family: monospace; font-size: 10px;")
        d_kopf.addWidget(self.lbl_ping_stats)
        d_lay.addLayout(d_kopf)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#070707")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.setYRange(0, 100, padding=0.05)
        self.plot_widget.setXRange(-60, 0, padding=0.01)
        self.plot_widget.setLabel("left", tr("diag_y_label"), units="ms")
        self.plot_widget.setLabel("bottom", tr("diag_x_label"), units="s")

        self.kurve_gw = self.plot_widget.plot(pen=pg.mkPen(color="#22c55e", width=2.0))
        self.kurve_inet = self.plot_widget.plot(pen=pg.mkPen(color="#38bdf8", width=2.0))
        d_lay.addWidget(self.plot_widget)

        root.addWidget(diagramm_rahmen, stretch=1)

        # 5. Detail-Leiste
        details = QFrame()
        details.setStyleSheet("background-color: #121212; border: 1px solid #242424; border-radius: 4px;")
        det_lay = QHBoxLayout(details)
        det_lay.setContentsMargins(8, 4, 8, 4)
        det_lay.setSpacing(12)

        self.lbl_det_ip = QLabel("IP: --")
        self.lbl_det_gw = QLabel("Gateway: --")
        self.lbl_det_dns = QLabel("DNS: --")
        self.lbl_det_delta = QLabel("WAN-Delta: --")
        for lbl in (self.lbl_det_ip, self.lbl_det_gw, self.lbl_det_dns, self.lbl_det_delta):
            lbl.setStyleSheet("font-size: 10px; color: #888888; font-family: monospace;")
            det_lay.addWidget(lbl)

        det_lay.addStretch()

        self.prog_balken = QProgressBar()
        self.prog_balken.setRange(0, 0)
        self.prog_balken.setFixedHeight(12)
        self.prog_balken.setFixedWidth(140)
        self.prog_balken.hide()
        det_lay.addWidget(self.prog_balken)

        self.lbl_status = QLabel(tr("diag_status_ready"))
        self.lbl_status.setStyleSheet("font-size: 11px; color: #aaaaaa;")
        det_lay.addWidget(self.lbl_status)

        root.addWidget(details)

    def umschalten(self):
        if self.ist_aktiv:
            self.stoppen()
        else:
            self.starten()

    def starten(self):
        import re
        rohe_ssid = self.txt_ssid.text().strip()
        ssid = re.sub(r"\s*\([+-]?\d+\s*dBm,\s*Ch\s*\d+\)$", "", rohe_ssid, flags=re.IGNORECASE).strip()
        self.txt_ssid.setText(ssid)

        if not ssid:
            self.lbl_status.setText("Bitte zuerst eine Ziel-SSID angeben.")
            return

        pruefer = self.combo_pruefer.currentData()
        self.aktuelles_ping_ziel = self._ermittle_ping_ziel()

        if pruefer == "esp32":
            if not self.serial_worker or not self.serial_worker.isRunning():
                self.lbl_status.setText("ESP32 ist nicht verbunden. Bitte Port verbinden oder Host-PC wählen.")
                return

        self.ist_aktiv = True
        self.status_zustand = "running"
        self.btn_start_stop.setText(tr("diag_stop"))
        self.btn_start_stop.setProperty("class", "DangerButton")
        self.btn_start_stop.style().unpolish(self.btn_start_stop)
        self.btn_start_stop.style().polish(self.btn_start_stop)

        self.prog_balken.show()
        self.lbl_status.setText(f"Diagnose gestartet ({'ESP32' if pruefer == 'esp32' else 'Host-PC'})...")

        self.ping_zeiten.clear()
        self.ping_gw_werte.clear()
        self.ping_inet_werte.clear()
        self.kurve_gw.setData([], [])
        self.kurve_inet.setData([], [])

        if pruefer == "esp32":
            self.serial_worker.starte_diagnose(ssid=ssid, passwort=self.txt_pass.text().strip(), ziel_ip=self.aktuelles_ping_ziel)
        else:
            self.host_thread = HostDiagnoseThread(
                ziel_ssid=ssid,
                passwort=self.txt_pass.text().strip(),
                ping_ziel=self.aktuelles_ping_ziel,
                eltern=self
            )
            self.host_thread.status_signal.connect(self.lbl_status.setText)
            self.host_thread.fertig_signal.connect(self._host_ergebnis)
            self.host_thread.start()

    def stoppen(self):
        self.ist_aktiv = False
        self.status_zustand = "stopped"
        self.prog_balken.hide()
        self.btn_start_stop.setText(tr("diag_start"))
        self.btn_start_stop.setProperty("class", "PrimaryButton")
        self.btn_start_stop.style().unpolish(self.btn_start_stop)
        self.btn_start_stop.style().polish(self.btn_start_stop)

        if self.host_thread and self.host_thread.isRunning():
            self.host_thread.abbrechen()
            self.host_thread.wait(500)

        if self.live_ping_thread and self.live_ping_thread.isRunning():
            self.live_ping_thread.stoppen()
            self.live_ping_thread.wait(500)

        if self.serial_worker and self.serial_worker.isRunning():
            self.serial_worker.stoppe_diagnose()

        if "abgeschlossen" not in self.lbl_status.text() and "Fehler" not in self.lbl_status.text() and "fehlgeschlagen" not in self.lbl_status.text():
            self.lbl_status.setText(tr("diag_status_stopped"))

    def _host_ergebnis(self, erg: DiagnoseErgebnis):
        self.prog_balken.hide()
        self.lbl_status.setText(erg.status_nachricht)

        if not erg.verbindung_erfolgreich:
            self.status_zustand = "error"
            self.lbl_v1.setText(tr("diag_error"))
            self.lbl_v1.setStyleSheet("font-size: 24px; font-weight: 800; color: #ef4444;")
            self.lbl_s1.setText(tr("diag_no_conn"))
            self.stoppen()
            return

        self.status_zustand = "done"
        self._zeige_ergebnisse(
            connect_ms=erg.verbindungsdauer_ms,
            dns_ok=erg.dns_ok,
            dns_ms=erg.dns_latenz_ms,
            gw_ms=erg.gateway_ping_ms,
            inet_ms=erg.internet_ping_ms,
            ip=erg.lokale_ip,
            gw=erg.gateway_ip,
            dns=erg.dns_server
        )

        # Live-Pingverlauf auf dem Host-PC starten
        if self.ist_aktiv:
            self.live_ping_thread = HostLivePingThread(
                gateway_ip=erg.gateway_ip,
                ping_ziel=self.aktuelles_ping_ziel,
                eltern=self
            )
            self.live_ping_thread.ping_signal.connect(self._ping_punkt)
            self.live_ping_thread.start()

    def _esp32_status(self, daten: dict):
        if "msg" in daten:
            self.lbl_status.setText(f"ESP32: {daten['msg']}")

    def _esp32_ergebnis(self, daten: dict):
        self.prog_balken.hide()
        ok = daten.get("success", daten.get("connect_ok", False))

        if not ok:
            self.status_zustand = "error"
            err = daten.get("error", "Verbindung fehlgeschlagen")
            self.lbl_status.setText(f"ESP32: {err} (Passwort prüfen)")
            self.lbl_v1.setText(tr("diag_error"))
            self.lbl_v1.setStyleSheet("font-size: 24px; font-weight: 800; color: #ef4444;")
            self.lbl_s1.setText(tr("diag_no_conn"))
            self.stoppen()
            return

        self.status_zustand = "done"
        self.lbl_status.setText(f"ESP32: {tr('diag_status_done')}")
        self._zeige_ergebnisse(
            connect_ms=int(daten.get("connect_ms", 0)),
            dns_ok=bool(daten.get("dns_ok", False)),
            dns_ms=float(daten.get("dns_ms", 0.0)),
            gw_ms=float(daten.get("gw_ping_ms", 0.0)),
            inet_ms=float(daten.get("internet_ping_ms", daten.get("inet_ping_ms", 0.0))),
            ip=str(daten.get("local_ip", "--")),
            gw=str(daten.get("gateway_ip", daten.get("gateway", "--"))),
            dns=str(daten.get("dns_ip", daten.get("dns", "--")))
        )

    def _esp32_ping(self, daten: dict):
        gw = float(daten.get("gw_ms", 0.0))
        inet = float(daten.get("internet_ms", daten.get("inet_ms", 0.0)))
        self._ping_punkt(gw, inet)

    def aktualisiere_sprache(self):
        """Aktualisiert alle UI-Texte und Beschriftungen bei Sprachwechsel."""
        self.lbl_titel.setText(tr("diag_title"))
        self.lbl_untertitel.setText(tr("diag_subtitle"))
        self.lbl_ssid.setText(tr("diag_ssid"))
        self.txt_ssid.setPlaceholderText(tr("diag_ssid_placeholder"))
        self.lbl_pass.setText(tr("diag_pass"))
        self.txt_pass.setPlaceholderText(tr("diag_pass_placeholder"))
        self.lbl_pruefer.setText(tr("diag_tester"))

        self.combo_pruefer.blockSignals(True)
        self.combo_pruefer.setItemText(0, tr("diag_tester_host"))
        self.combo_pruefer.setItemText(1, tr("diag_tester_esp32"))
        self.combo_pruefer.blockSignals(False)

        self.lbl_ping_ziel.setText(tr("diag_target"))

        if not self.ist_aktiv:
            self.btn_start_stop.setText(tr("diag_start"))
        else:
            self.btn_start_stop.setText(tr("diag_stop"))

        # 4 Metrik-Karten
        self.lbl_t1.setText(tr("diag_card_dhcp").upper())
        self.lbl_t2.setText(tr("diag_card_dns").upper())
        self.lbl_t3.setText(tr("diag_card_gw").upper())
        self.lbl_t4.setText(tr("diag_card_inet").upper())

        # Kachel-Subtexte
        if self.letzter_connect_ms is None:
            self.lbl_s1.setText(tr("diag_ready"))
            self.lbl_s2.setText(tr("diag_ready"))
            self.lbl_s3.setText(tr("diag_ready"))
            self.lbl_s4.setText(tr("diag_ready"))
        else:
            self._zeige_ergebnisse(
                connect_ms=self.letzter_connect_ms,
                dns_ok=self.letzter_dns_ok,
                dns_ms=self.letzter_dns_ms,
                gw_ms=self.letzter_gw_ping,
                inet_ms=self.letzter_inet_ping,
                ip=self.letzte_ip,
                gw=self.letzter_gw,
                dns=self.letzter_dns,
                punkt_hinzufuegen=False
            )

        # Diagramm
        self.lbl_diag_titel.setText(tr("diag_graph_title"))
        self.leg_gw.setText(tr("diag_leg_router"))
        self.leg_inet.setText(tr("diag_leg_internet"))
        self.plot_widget.setLabel("left", tr("diag_y_label"), units="ms")
        self.plot_widget.setLabel("bottom", tr("diag_x_label"), units="s")

        delta = (self.letzter_inet_ping - self.letzter_gw_ping) if (self.letzter_inet_ping > 0 and self.letzter_gw_ping > 0) else 0.0
        gw_txt = f"{self.letzter_gw_ping:.1f}" if self.letzter_gw_ping > 0 else "--"
        inet_txt = f"{self.letzter_inet_ping:.1f}" if self.letzter_inet_ping > 0 else "--"
        delta_txt = f"{delta:.1f}" if delta > 0 else "--"
        self.lbl_ping_stats.setText(tr("diag_stats_fmt", gw=gw_txt, inet=inet_txt, delta=delta_txt))

        # Status
        if self.status_zustand == "ready":
            self.lbl_status.setText(tr("diag_status_ready"))
        elif self.status_zustand == "stopped":
            self.lbl_status.setText(tr("diag_status_stopped"))
        elif self.status_zustand == "done":
            self.lbl_status.setText(tr("diag_status_done"))

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)

    def _zeige_ergebnisse(self, connect_ms: int, dns_ok: bool, dns_ms: float,
                          gw_ms: float, inet_ms: float, ip: str, gw: str, dns: str,
                          punkt_hinzufuegen: bool = True):
        self.letzter_connect_ms = connect_ms
        self.letzter_dns_ok = dns_ok
        self.letzter_dns_ms = dns_ms
        self.letzter_gw_ping = gw_ms
        self.letzter_inet_ping = inet_ms
        self.letzte_ip = ip
        self.letzter_gw = gw
        self.letzter_dns = dns

        # 1. DHCP
        self.lbl_v1.setText(f"{connect_ms} ms")
        col1 = "#22c55e" if connect_ms < 1500 else "#eab308" if connect_ms < 3500 else "#ef4444"
        self.lbl_v1.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {col1}; font-family: monospace;")
        self.lbl_s1.setText(tr("diag_opt") if connect_ms < 1500 else tr("diag_moderate") if connect_ms < 3500 else tr("diag_slow"))

        # 2. DNS
        if dns_ok and dns_ms > 0:
            self.lbl_v2.setText(f"{dns_ms:.0f} ms")
            col2 = "#22c55e" if dns_ms < 30 else "#eab308" if dns_ms < 80 else "#ef4444"
            self.lbl_v2.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {col2}; font-family: monospace;")
            self.lbl_s2.setText(tr("diag_fast") if dns_ms < 30 else tr("diag_normal") if dns_ms < 80 else tr("diag_delayed"))
        else:
            self.lbl_v2.setText(tr("diag_error"))
            self.lbl_v2.setStyleSheet("font-size: 24px; font-weight: 800; color: #ef4444;")
            self.lbl_s2.setText(tr("diag_timeout"))

        # 3. Router-Ping
        if gw_ms > 0:
            self.lbl_v3.setText(f"{gw_ms:.1f} ms")
            col3 = "#22c55e" if gw_ms < 6 else "#eab308" if gw_ms < 18 else "#ef4444"
            self.lbl_v3.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {col3}; font-family: monospace;")
            self.lbl_s3.setText(tr("diag_opt") if gw_ms < 6 else tr("diag_moderate") if gw_ms < 18 else tr("diag_slow"))
        else:
            self.lbl_v3.setText(tr("diag_error"))
            self.lbl_v3.setStyleSheet("font-size: 24px; font-weight: 800; color: #ef4444;")
            self.lbl_s3.setText(tr("diag_timeout"))

        # 4. Internet-Ping
        if inet_ms > 0:
            self.lbl_v4.setText(f"{inet_ms:.1f} ms")
            col4 = "#22c55e" if inet_ms < 35 else "#eab308" if inet_ms < 75 else "#ef4444"
            self.lbl_v4.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {col4}; font-family: monospace;")
            self.lbl_s4.setText(tr("diag_fast") if inet_ms < 35 else tr("diag_normal") if inet_ms < 75 else tr("diag_slow"))
        else:
            self.lbl_v4.setText(tr("diag_error"))
            self.lbl_v4.setStyleSheet("font-size: 24px; font-weight: 800; color: #ef4444;")
            self.lbl_s4.setText(tr("diag_timeout"))

        # Details
        self.lbl_det_ip.setText(f"IP: {ip}")
        self.lbl_det_gw.setText(f"Gateway: {gw}")
        self.lbl_det_dns.setText(f"DNS: {dns}")
        if gw_ms > 0 and inet_ms >= gw_ms:
            delta = inet_ms - gw_ms
            self.lbl_det_delta.setText(f"WAN-Delta (Provider): +{delta:.1f} ms")
        else:
            self.lbl_det_delta.setText("WAN-Delta: --")

        self.aktuelle_gateway_ip = gw
        if punkt_hinzufuegen:
            self._ping_punkt(gw_ms, inet_ms)

    def _ping_punkt(self, gw_ms: float, inet_ms: float):
        jetzt = time.time()
        self.ping_zeiten.append(jetzt)
        self.ping_gw_werte.append(gw_ms)
        self.ping_inet_werte.append(inet_ms)

        grenze = jetzt - 60.0
        while self.ping_zeiten and self.ping_zeiten[0] < grenze:
            self.ping_zeiten.popleft()
            self.ping_gw_werte.popleft()
            self.ping_inet_werte.popleft()

        xs = [t - jetzt for t in self.ping_zeiten]
        self.kurve_gw.setData(xs, list(self.ping_gw_werte))
        self.kurve_inet.setData(xs, list(self.ping_inet_werte))

        max_y = max(max(self.ping_inet_werte or [40]), max(self.ping_gw_werte or [20]))
        self.plot_widget.setYRange(0, max(50.0, max_y * 1.25))

        delta = (inet_ms - gw_ms) if (inet_ms > 0 and gw_ms > 0) else 0.0
        self.lbl_ping_stats.setText(tr("diag_stats_fmt", gw=f"{gw_ms:.1f}", inet=f"{inet_ms:.1f}", delta=f"{delta:.1f}"))

        # Live-Aktualisierung der Kacheln 3 und 4
        if gw_ms > 0:
            self.lbl_v3.setText(f"{gw_ms:.1f} ms")
        if inet_ms > 0:
            self.lbl_v4.setText(f"{inet_ms:.1f} ms")


class WlanDiagnoseFenster(QDialog):
    """Dialog-Wrapper fuer eigenstaendige Anzeige."""
    def __init__(self, serial_worker=None, standard_ssid: str = "", eltern=None):
        super().__init__(eltern)
        self.setWindowTitle(tr("diag_title"))
        self.resize(1020, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.widget = NetzwerkDiagnoseWidget(serial_worker, standard_ssid, self)
        lay.addWidget(self.widget)
