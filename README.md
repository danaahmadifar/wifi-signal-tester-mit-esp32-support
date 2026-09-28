# ESP32 WLAN Signal-Tester & Netzwerk-Diagnose

Ein modulares Mess- und Diagnosesystem zur Analyse von WLAN-Signalen mit einem ESP32 und einer Python-Desktop-Applikation (PyQt6). Das System erfasst Signalstärke (RSSI), SNR, Retry-Rate und Modulationsarten im passiven 802.11-Sniffer-Modus, führt aktive Netzwerk-Benchmarks durch (DHCP, DNS, Dual-Ping) und erstellt Signal-Heatmaps auf Grundrissen. Die Datenübertragung erfolgt wahlweise über Bluetooth Classic (SPP) oder per USB-Kabel.

### 1. Signal-Analyzer
<img width="1338" height="867" alt="image" src="https://github.com/user-attachments/assets/8b7d6b2a-6d97-45f9-bc63-f01404285d79" />
### 2. Netzwerk-Diagnose
<img width="1334" height="865" alt="image" src="https://github.com/user-attachments/assets/99202cc6-9e22-4592-8611-673e7977777b" />
### 3. Grundriss & Heatmap
<img width="1335" height="865" alt="image" src="https://github.com/user-attachments/assets/c545a3da-8bc6-40c9-9b84-0d41bb2e31b0" />

---

## Verwendete Hardware

* **Mikrocontroller**: ESP32 DevKit V1 / NodeMCU (2,4 GHz Wi-Fi & Bluetooth Classic)
* **Schnittstellen**: Bluetooth Classic SPP (`ESP32_WiFi_Tester`, PIN `1234`) oder USB-UART (115200 Baud)
* **Host-System**: PC mit Windows 10/11 und Python 3.9+
* **Alternative**: Interne WLAN-Karte des Host-PCs (für passive Basismessungen ohne ESP32)

### Bild Mobiler Messaufbau
<img width="2000" height="1500" alt="image" src="https://github.com/user-attachments/assets/702e0426-3296-4152-8752-7864b9714f88" />

---

## Funktionen und Bedienung

### 1. Signal-Analyzer
* **Echtzeit-Diagramm**: 60-Sekunden-Verlauf des Signalpegels (dBm) mit Rohdaten, adaptiver Glättung und Mittelwertlinie.
* **Abtastrate**: Einstellbar auf feste Raten (**1 Hz**, **5 Hz**, **10 Hz**) mit driftfreier Taktung und sofortiger Übernahme.
* **Messwerte**: Signalstärke (RSSI), Rauschabstand (SNR), 802.11-Wiederholrate (Retry-Rate), Modulationsart (z. B. 64-QAM, QPSK, CCK) und MCS-Index.
* **Filter & Hysterese**: Arretierung auf Ziel-SSID/BSSID und Kanal (1–14). BSSID-Hysterese verhindert Pegelsprünge in Mesh-Netzwerken.
* **Alarm & Logging**: Optischer Schwellenwert-Alarm und CSV-Export der Messdaten.

### 2. Netzwerk-Diagnose
* **Verbindungstest**: Misst die Dauer für Wi-Fi-Handshake und DHCP-Adresszuweisung.
* **DNS & Dual-Ping**: Prüft DNS-Auflösungszeiten sowie simultane Pings zu Router/Gateway und frei wählbarem Internet-Ziel (z. B. `1.1.1.1`).
* **Live-Pingverlauf**: 60-Sekunden-Latenzgraph zur Erkennung von Jitter und Paketverlusten inkl. Qualitätsbewertung.

### 3. Grundriss & Heatmap
* **Karten-Import**: Unterstützt Vektorgrafiken (SVG) sowie Bilddateien (PNG/JPG).
* **Messpunkte**: Klick in den Plan setzt einen Messpunkt, die **Leertaste** übernimmt den aktuellen Signalwert.
* **5-Stufen-Heatmap**: Berechnet die Signalabdeckung (IDW-Interpolation) von Rot (schwach) bis Grün (stark).
* **Export**: Speichert die Heatmap als PNG-Bild oder CSV-Punktliste.

### 4. Mehrsprachigkeit
* Unterstützt 8 Sprachen mit nativer Rechts-nach-Links (RTL) Layout-Umschaltung: Deutsch (DE), Englisch (EN), Französisch (FR), Spanisch (ES), Chinesisch (ZH), Russisch (RU), Arabisch (AR) und Persisch (FA).

---

## Projektstruktur

* `esp32/src/main.cpp`: ESP32-Hauptprogramm (Sniffer-Callback, Bluetooth SPP & UART-Stream, aktive Diagnose).
* `esp32/src/Config.h`: Datenstrukturen, Standardparameter und Hardware-Konfiguration.
* `esp32/src/PacketDecoder.h`: 802.11-Frame-Parsing, MAC-Adressen- und Modulationserkennung.
* `esp32/src/TargetTracker.h`: Zielnetzwerk-Filterung, BSSID-Hysterese und Telemetrie-Snapshots.
* `python_gui/main.py`: Haupteinstiegspunkt der Desktop-Applikation und View-Steuerung.
* `python_gui/core/`: `serieller_worker.py` (ESP32-Kommunikation), `wlan_scanner.py` (PC-WLAN) und `datenmodelle.py`.
* `python_gui/ui/`: `design.py` (Dark Theme & QSS), `sprachen.py` (Übersetzungen & RTL) und `komponenten.py`.
* `python_gui/ui/views/`: Ansichten (`analyzer_ansicht.py`, `diagnose_ansicht.py`, `grundriss_ansicht.py`).

---

## Einrichtung und Start

### 1. ESP32 flashen
1. Das Verzeichnis `esp32` in VS Code mit PlatformIO öffnen.
2. ESP32 per USB anschließen und Firmware übertragen:
   ```bash
   pio run -t upload
   ```

### 2. Bluetooth koppeln (optional)
1. Unter Windows in den **Bluetooth & Geräte**-Einstellungen nach **`ESP32_WiFi_Tester`** suchen und koppeln (PIN: `1234`).
2. Der COM-Port ist im Geräte-Manager unter *Anschlüsse (COM & LPT)* zu finden.

### 3. GUI starten
1. Abhängigkeiten installieren:
   ```bash
   pip install -r python_gui/requirements.txt
   ```
2. Anwendung starten per Doppelklick auf `Start_WiFi_Tester.bat` oder im Terminal:
   ```bash
   python python_gui/main.py
   ```
3. COM-Port oder interne WLAN-Karte auswählen und auf **Verbinden** klicken.
