/**
 * ============================================================================
 * ESP32 Wi-Fi Analyzer - Firmware (main.cpp)
 * ============================================================================
 * 
 * Funktionsübersicht:
 * 1. Promiscuous-Modus (IEEE 802.11):
 *    Passiver Empfang von Management- und Daten-Frames auf physikalischer Ebene.
 * 2. Selektive Downlink-Filterung:
 *    Ausschließliche Erfassung von Basisstationspaketen (Access Points) zur
 *    Vermeidung von Messverzerrungen durch Client-Sendeasymmetrien.
 * 3. Kanalpersistenz:
 *    Feste Arretierung auf den Funkkanal des Zielnetzwerks während der Messung.
 * 4. Telemetriestrom (10 Hz):
 *    Periodische Datenübertragung via Bluetooth SPP (Serial Port Profile) sowie
 *    USB-UART im strukturierten JSON-Format.
 * ============================================================================
 */

#include <Arduino.h>
#include <WiFi.h>
#include "esp_wifi.h"
#include <BluetoothSerial.h>
#include "ping/ping_sock.h"

#include "Config.h"
#include "PacketDecoder.h"
#include "TargetTracker.h"

#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error "Bluetooth ist auf diesem Chip nicht aktiviert. Bitte Standard-ESP32 verwenden."
#endif

// ============================================================================
// GLOBALE OBJEKTE & STATUSVARIABLEN
// ============================================================================
BluetoothSerial SerialBT;
TargetTracker g_tracker;
GlobalConfig g_config;

volatile bool g_bt_connected = false;
volatile bool g_diag_active = false;
uint32_t g_last_diag_ping = 0;
uint32_t g_last_send_time = 0;
uint32_t g_last_packet_seen = 0;
uint32_t g_last_auto_scan = 0;
uint32_t g_total_packets_captured = 0;

String g_bt_puffer = "";
String g_usb_puffer = "";

// ============================================================================
// HILFSFUNKTIONEN ZUR JSON-PARSIERUNG
// ============================================================================
static String extractJsonValue(const String& json, const char* key) {
    int idx = json.indexOf(key);
    if (idx < 0) return "";
    int col = json.indexOf(':', idx);
    if (col < 0) return "";
    int q1 = json.indexOf('"', col + 1);
    if (q1 < 0) return "";
    int q2 = json.indexOf('"', q1 + 1);
    if (q2 <= q1) return "";
    return json.substring(q1 + 1, q2);
}

static int extractJsonInt(const String& json, const char* key, int default_val = 0) {
    int idx = json.indexOf(key);
    if (idx < 0) return default_val;
    int col = json.indexOf(':', idx);
    if (col < 0) return default_val;
    return json.substring(col + 1).toInt();
}

// ============================================================================
// PROMISCUOUS RX CALLBACK (802.11 INTERRUPT-EBENE)
// ============================================================================
void wifi_promiscuous_rx_callback(void* buf, wifi_promiscuous_pkt_type_t type) {
    if (!buf) return;
    const wifi_promiscuous_pkt_t* pkt = (wifi_promiscuous_pkt_t*)buf;
    const wifi_pkt_rx_ctrl_t* rx_ctrl = &pkt->rx_ctrl;
    const uint8_t* payload = pkt->payload;
    const uint16_t sig_len = rx_ctrl->sig_len;

    // Mindestlänge für 802.11 MAC-Header (24 Byte)
    if (sig_len < 24) return;

    // Analyse des Frame Control Feldes
    uint8_t fc0 = payload[0];
    uint8_t fc1 = payload[1];
    uint8_t frame_type = (fc0 >> 2) & 0x03;     // 0: Mgmt, 1: Control, 2: Data
    uint8_t frame_subtype = (fc0 >> 4) & 0x0F;  // 8: Beacon, 5: Probe Response
    bool is_retry = (fc1 & 0x08) != 0;          // 802.11 Retry-Flag (Bit 3)

    // Filterkriterium: Ausschließlich Downlink-Datenpakete und Management-Beacons zulassen
    if (frame_type == 0) {
        if (frame_subtype != 8 && frame_subtype != 5) return;
    } else if (frame_type == 2) {
        bool to_ds = (fc1 & 0x01) != 0;
        bool from_ds = (fc1 & 0x02) != 0;
        if (to_ds || !from_ds) return; // Upstream von Endgeräten verwerfen
    } else {
        return; // Control-Frames ignorieren
    }

    // Sender-BSSID (Addr2: payload[10..15])
    const uint8_t* transmitter_bssid = &payload[10];

    char detected_ssid[33] = {0};
    uint8_t beacon_channel = 0;

    if (frame_type == 0) {
        PacketDecoder::parseBeaconTags(payload, sig_len, detected_ssid, sizeof(detected_ssid), &beacon_channel);
    }

    uint32_t now = millis();

    // Zustandsverarbeitung im TargetTracker
    if (g_tracker.processPacket(transmitter_bssid, detected_ssid, frame_type, is_retry, rx_ctrl, now)) {
        g_last_packet_seen = now;
        g_total_packets_captured++;

        // Automatische Kanalsynchronisation bei Beacon-Erfassung
        if (beacon_channel >= 1 && beacon_channel <= 13) {
            if (g_config.auto_channel && g_config.current_channel != beacon_channel) {
                g_config.current_channel = beacon_channel;
                esp_wifi_set_channel(beacon_channel, WIFI_SECOND_CHAN_NONE);
            }
        }
    }
}

// ============================================================================
// BLUETOOTH STATUS-CALLBACK & INITIALISIERUNG
// ============================================================================
void btCallback(esp_spp_cb_event_t event, esp_spp_cb_param_t *param) {
    if (event == ESP_SPP_SRV_OPEN_EVT) {
        Serial.println(F("[BT] Verbindung hergestellt."));
        g_bt_connected = true;
        digitalWrite(STATUS_LED_PIN, HIGH);
    } else if (event == ESP_SPP_CLOSE_EVT) {
        Serial.println(F("[BT] Verbindung getrennt."));
        g_bt_connected = false;
        digitalWrite(STATUS_LED_PIN, LOW);
    }
}

void initWiFiPromiscuous() {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();

    wifi_promiscuous_filter_t filt = {
        .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA
    };
    esp_wifi_set_promiscuous_filter(&filt);
    esp_wifi_set_promiscuous_rx_cb(&wifi_promiscuous_rx_callback);
    esp_wifi_set_promiscuous(true);
    esp_wifi_set_channel(g_config.current_channel, WIFI_SECOND_CHAN_NONE);

    Serial.printf("[WIFI] Promiscuous Sniffer initialisiert auf Kanal %d\n", g_config.current_channel);
}

// ============================================================================
// WLAN-UMGEBUNGSSCAN
// ============================================================================
void performWiFiScan() {
    Serial.println(F("[SCAN] Starte Frequenzabtastung (2,4 GHz)..."));
    if (g_bt_connected) SerialBT.println(F("{\"status\":\"scanning\"}"));

    esp_wifi_set_promiscuous(false);
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    delay(40);

    int n = WiFi.scanNetworks(false, true); // Synchroner Suchlauf
    Serial.printf("[SCAN] %d Netzwerke erfasst.\n", n);

    if (n > 0) {
        for (int i = 0; i < n; ++i) {
            String ssid = WiFi.SSID(i);
            String bssid = WiFi.BSSIDstr(i);
            int32_t rssi = WiFi.RSSI(i);
            int32_t channel = WiFi.channel(i);

            char net_json[220];
            snprintf(net_json, sizeof(net_json),
                     "{\"scan_item\":{\"ssid\":\"%s\",\"bssid\":\"%s\",\"rssi\":%d,\"channel\":%d,\"band\":\"2.4 GHz\"}}",
                     ssid.c_str(), bssid.c_str(), (int)rssi, (int)channel);

            if (g_bt_connected) SerialBT.println(net_json);
            Serial.println(net_json);
            delay(5);
        }
    }

    if (g_bt_connected) SerialBT.println(F("{\"scan_complete\":true}"));
    Serial.println(F("{\"scan_complete\":true}"));

    WiFi.scanDelete();

    // Reaktivierung des Promiscuous-Empfängers
    initWiFiPromiscuous();
    if (g_config.current_channel >= 1 && g_config.current_channel <= 13) {
        esp_wifi_set_channel(g_config.current_channel, WIFI_SECOND_CHAN_NONE);
    }
}

// ============================================================================
// AKTIVE WLAN-DIAGNOSE (DHCP-BENCHMARK, DNS-LATENZ & PING)
// ============================================================================
static volatile uint32_t g_ping_rtt = 0;
static volatile bool g_ping_done = false;
static IPAddress g_internet_ping_target(1, 1, 1, 1);

static void ping_success_cb(esp_ping_handle_t hdl, void *args) {
    uint32_t elapsed_time = 0;
    esp_ping_get_profile(hdl, ESP_PING_PROF_TIMEGAP, &elapsed_time, sizeof(elapsed_time));
    g_ping_rtt = elapsed_time;
    g_ping_done = true;
}

static void ping_timeout_cb(esp_ping_handle_t hdl, void *args) {
    g_ping_rtt = 9999;
    g_ping_done = true;
}

static void ping_end_cb(esp_ping_handle_t hdl, void *args) {
    g_ping_done = true;
}

static uint32_t pingTarget(IPAddress ip) {
    ip_addr_t target_addr;
    memset(&target_addr, 0, sizeof(target_addr));
    target_addr.type = IPADDR_TYPE_V4;
    target_addr.u_addr.ip4.addr = static_cast<uint32_t>(ip);

    esp_ping_config_t ping_config = ESP_PING_DEFAULT_CONFIG();
    ping_config.target_addr = target_addr;
    ping_config.count = 1;
    ping_config.timeout_ms = 1200;

    esp_ping_callbacks_t cbs = {
        .cb_args = NULL,
        .on_ping_success = ping_success_cb,
        .on_ping_timeout = ping_timeout_cb,
        .on_ping_end = ping_end_cb
    };

    g_ping_rtt = 0;
    g_ping_done = false;

    esp_ping_handle_t ping = NULL;
    if (esp_ping_new_session(&ping_config, &cbs, &ping) == ESP_OK) {
        esp_ping_start(ping);
        uint32_t start_w = millis();
        while (!g_ping_done && (millis() - start_w < 1500)) {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
        esp_ping_stop(ping);
        esp_ping_delete_session(ping);
    }
    return g_ping_rtt;
}

void performActiveDiagnostics(const String& ssid, const String& password) {
    Serial.printf("[DIAG] Starte Diagnose fuer SSID '%s'...\n", ssid.c_str());

    String start_msg = "{\"diag_status\":{\"state\":\"connecting\",\"ssid\":\"" + ssid + "\"}}";
    if (g_bt_connected) SerialBT.println(start_msg);
    Serial.println(start_msg);

    // 1. Promiscuous-Modus temporär stoppen & Station-Modus aktivieren
    esp_wifi_set_promiscuous(false);
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(true);
    delay(100);

    // 2. Verbindungsaufbau & DHCP-Benchmark
    uint32_t t_start = millis();
    if (password.length() > 0) {
        WiFi.begin(ssid.c_str(), password.c_str());
    } else {
        WiFi.begin(ssid.c_str());
    }

    // Bis zu 10 Sekunden auf Assoziierung und DHCP-Zuweisung warten
    while (WiFi.status() != WL_CONNECTED && (millis() - t_start < 10000)) {
        vTaskDelay(pdMS_TO_TICKS(50));
    }

    uint32_t connect_duration_ms = millis() - t_start;

    if (WiFi.status() != WL_CONNECTED) {
        WiFi.disconnect(true);
        String err_msg = "{\"diag_result\":{\"success\":false,\"error\":\"Verbindung fehlgeschlagen\",\"connect_ms\":" + String(connect_duration_ms) + "}}";
        if (g_bt_connected) SerialBT.println(err_msg);
        Serial.println(err_msg);

        // Rückkehr in Promiscuous-Modus
        initWiFiPromiscuous();
        return;
    }

    // 3. IP-Netzwerkkonfiguration erfassen
    String local_ip = WiFi.localIP().toString();
    String gateway_ip = WiFi.gatewayIP().toString();
    String subnet = WiFi.subnetMask().toString();
    String dns_ip = WiFi.dnsIP().toString();

    // 4. DNS-Latenztest mit rotierenden Referenz-Domains zur Vermeidung von Cache-Verfaelschungen
    static uint8_t s_dns_idx = 0;
    const char* kDnsDomains[] = {
        "google.com", "cloudflare.com", "wikipedia.org", "apple.com",
        "microsoft.com", "amazon.com", "github.com", "heise.de"
    };
    const char* probe_host = kDnsDomains[s_dns_idx % 8];
    s_dns_idx++;

    uint32_t t_dns0 = millis();
    IPAddress resolved_ip;
    bool dns_ok = WiFi.hostByName(probe_host, resolved_ip);
    uint32_t dns_duration_ms = millis() - t_dns0;
    if (!dns_ok) {
        t_dns0 = millis();
        dns_ok = WiFi.hostByName("google.com", resolved_ip);
        dns_duration_ms = millis() - t_dns0;
    }

    // 5. Gateway-Ping (lokale Funkstrecke)
    uint32_t gw_ping_ms = pingTarget(WiFi.gatewayIP());

    // 6. Internet-Ping (konfigurierbares Ziel)
    uint32_t internet_ping_ms = pingTarget(g_internet_ping_target);
    if (internet_ping_ms >= 9000 && g_internet_ping_target == IPAddress(1, 1, 1, 1)) {
        internet_ping_ms = pingTarget(IPAddress(8, 8, 8, 8));
    }

    // 7. Diagnoseergebnis an Host-PC übertragen
    char diag_json[450];
    snprintf(diag_json, sizeof(diag_json),
             "{\"diag_result\":{\"success\":true,\"connect_ms\":%u,\"local_ip\":\"%s\",\"gateway_ip\":\"%s\",\"subnet\":\"%s\",\"dns_ip\":\"%s\",\"dns_ok\":%s,\"dns_ms\":%u,\"gw_ping_ms\":%u,\"internet_ping_ms\":%u}}",
             connect_duration_ms,
             local_ip.c_str(),
             gateway_ip.c_str(),
             subnet.c_str(),
             dns_ip.c_str(),
             dns_ok ? "true" : "false",
             dns_duration_ms,
             gw_ping_ms < 9000 ? gw_ping_ms : 0,
             internet_ping_ms < 9000 ? internet_ping_ms : 0);

    if (g_bt_connected) SerialBT.println(diag_json);
    Serial.println(diag_json);

    // 8. Diagnose-Modus aktiv halten fuer kontinuierlichen Pingverlauf
    g_diag_active = true;
    g_last_diag_ping = millis();
}

// ============================================================================
// BEFEHLSVERARBEITUNG
// ============================================================================
void processCommand(const String& cmd_str) {
    String cmd = cmd_str;
    cmd.trim();
    if (cmd.length() == 0) return;

    Serial.print(F("[CMD] "));
    Serial.println(cmd);

    // 1. JSON-Protokollverarbeitung
    if (cmd.startsWith("{") && cmd.endsWith("}")) {
        // A) Netzwerk-Scan
        if (cmd.indexOf("\"scan\"") >= 0) {
            performWiFiScan();
            return;
        }

        // B) Ziel-Konfiguration
        if (cmd.indexOf("\"set_filter\"") >= 0 || cmd.indexOf("\"set_target\"") >= 0) {
            String new_ssid = extractJsonValue(cmd, "\"ssid\"");
            String new_bssid = extractJsonValue(cmd, "\"bssid\"");
            int ch = extractJsonInt(cmd, "\"channel\"", 0);
            int r = extractJsonInt(cmd, "\"rate_hz\"", 0);

            if (r >= 1 && r <= 50) {
                g_config.sample_rate_hz = r;
                g_last_send_time = millis();
            }

            if (ch >= 1 && ch <= 13) {
                g_config.current_channel = ch;
                g_config.auto_channel = false;
                esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
            } else if (new_ssid.length() > 0 && ch == 0) {
                g_config.auto_channel = true;
            }

            if (new_ssid.length() > 0) {
                g_tracker.setTarget(
                    new_ssid.c_str(),
                    new_bssid.length() == 17 ? new_bssid.c_str() : nullptr,
                    (ch >= 1 && ch <= 13) ? (uint8_t)ch : 0
                );
            } else {
                g_tracker.clearTarget();
            }

            char reply[160];
            snprintf(reply, sizeof(reply), "{\"status\":\"ok\",\"ssid\":\"%s\",\"channel\":%d,\"rate_hz\":%d}",
                     new_ssid.c_str(), g_config.current_channel, g_config.sample_rate_hz);
            if (g_bt_connected) SerialBT.println(reply);
            Serial.println(reply);
            return;
        }

        // C) Verbindungsprüfung (Ping)
        if (cmd.indexOf("\"ping\"") >= 0) {
            String p = "{\"status\":\"pong\",\"time_ms\":" + String(millis()) + "}";
            if (g_bt_connected) SerialBT.println(p);
            Serial.println(p);
            return;
        }

        // D) Aktive Diagnose & Benchmarks
        if (cmd.indexOf("\"start_diag\"") >= 0) {
            String diag_ssid = extractJsonValue(cmd, "\"ssid\"");
            String diag_pass = extractJsonValue(cmd, "\"password\"");
            String target_ip_str = extractJsonValue(cmd, "\"target_ip\"");
            if (target_ip_str.length() > 0) {
                IPAddress parsed_ip;
                if (parsed_ip.fromString(target_ip_str)) {
                    g_internet_ping_target = parsed_ip;
                }
            } else {
                g_internet_ping_target = IPAddress(1, 1, 1, 1);
            }
            if (diag_ssid.length() == 0 && g_tracker.hasTarget()) {
                diag_ssid = g_tracker.getTargetSSID();
            }
            if (diag_ssid.length() > 0) {
                performActiveDiagnostics(diag_ssid, diag_pass);
            }
            return;
        }

        if (cmd.indexOf("\"stop_diag\"") >= 0) {
            g_diag_active = false;
            WiFi.disconnect(true);
            delay(40);
            initWiFiPromiscuous();
            if (g_config.current_channel >= 1 && g_config.current_channel <= 13) {
                esp_wifi_set_channel(g_config.current_channel, WIFI_SECOND_CHAN_NONE);
            }
            if (g_bt_connected) SerialBT.println(F("{\"diag_stopped\":true}"));
            Serial.println(F("{\"diag_stopped\":true}"));
            return;
        }
    }

    // 2. Textbasierte Fallback-Befehle (CLI)
    if (cmd.startsWith("SET_CHANNEL ")) {
        int ch = cmd.substring(12).toInt();
        if (ch >= 1 && ch <= 13) {
            g_config.current_channel = ch;
            g_config.auto_channel = false;
            esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
            if (g_bt_connected) SerialBT.printf("{\"status\":\"ok\",\"channel\":%d}\n", ch);
        }
    } else if (cmd.startsWith("SET_SSID ")) {
        String s = cmd.substring(9);
        s.trim();
        g_tracker.setTarget(s.c_str());
        if (g_bt_connected) SerialBT.printf("{\"status\":\"ok\",\"ssid\":\"%s\"}\n", s.c_str());
    } else if (cmd == "AUTO_CHANNEL") {
        g_config.auto_channel = true;
        if (g_bt_connected) SerialBT.println(F("{\"status\":\"ok\",\"auto_channel\":true}"));
    } else if (cmd.startsWith("SET_RATE ")) {
        int r = cmd.substring(9).toInt();
        if (r >= 1 && r <= 50) {
            g_config.sample_rate_hz = r;
            g_last_send_time = millis();
            if (g_bt_connected) SerialBT.printf("{\"status\":\"ok\",\"rate_hz\":%d}\n", r);
            Serial.printf("{\"status\":\"ok\",\"rate_hz\":%d}\n", r);
        }
    }
}

// ============================================================================
// SYSTEMINITIALISIERUNG
// ============================================================================
void setup() {
    pinMode(STATUS_LED_PIN, OUTPUT);
    digitalWrite(STATUS_LED_PIN, LOW);

    Serial.begin(115200);
    delay(400);
    Serial.println();
    Serial.println(F("=================================================="));
    Serial.println(F(" ESP32 Wi-Fi Signal Strength Analyzer             "));
    Serial.println(F(" Promiscuous RX & Bluetooth SPP Telemetry Stream  "));
    Serial.println(F("=================================================="));

    // Bluetooth SPP initialisieren
    SerialBT.register_callback(btCallback);
    if (!SerialBT.begin(BT_DEVICE_NAME)) {
        Serial.println(F("[FEHLER] Initialisierung des Bluetooth-Stacks fehlgeschlagen."));
        while (1) {
            digitalWrite(STATUS_LED_PIN, !digitalRead(STATUS_LED_PIN));
            delay(100);
        }
    }

    Serial.printf("[BT] SPP aktiv unter Kennung: '%s'\n", BT_DEVICE_NAME);

    // Wi-Fi Promiscuous Sniffer initialisieren
    initWiFiPromiscuous();

    Serial.println(F("[SYS] System betriebsbereit."));
}

// ============================================================================
// HAUPTSCHLEIFE (LOOP)
// ============================================================================
void loop() {
    uint32_t now = millis();

    // 1. Nicht-blockierender Befehlsempfang (Bluetooth)
    while (SerialBT.available()) {
        char c = (char)SerialBT.read();
        if (c == '\n') {
            processCommand(g_bt_puffer);
            g_bt_puffer = "";
        } else if (c != '\r') {
            g_bt_puffer += c;
        }
    }

    // 2. Nicht-blockierender Befehlsempfang (USB-UART)
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\n') {
            processCommand(g_usb_puffer);
            g_usb_puffer = "";
        } else if (c != '\r') {
            g_usb_puffer += c;
        }
    }

    // 3. Automatischer Kanalsuchlauf bei Signalverlust (nur bei aktivem auto_channel)
    if (g_config.auto_channel && g_tracker.hasTarget()) {
        if (now - g_last_packet_seen > 2500 && now - g_last_auto_scan > 120) {
            g_last_auto_scan = now;
            g_config.current_channel = (g_config.current_channel % 13) + 1;
            esp_wifi_set_channel(g_config.current_channel, WIFI_SECOND_CHAN_NONE);
        }
    }

    // 4. Status-LED (Blinken im Suchmodus, Daueranzeige bei Verbindung)
    if (!g_bt_connected) {
        static uint32_t last_blink = 0;
        if (now - last_blink >= 500) {
            last_blink = now;
            digitalWrite(STATUS_LED_PIN, !digitalRead(STATUS_LED_PIN));
        }
    }

    // 5. Modusabhängiger Datenversand (Live-Ping während Diagnose, sonst Promiscuous-Telemetrie)
    if (g_diag_active) {
        if (WiFi.status() == WL_CONNECTED && (now - g_last_diag_ping >= 1000)) {
            g_last_diag_ping = now;
            uint32_t gw_ms = pingTarget(WiFi.gatewayIP());
            uint32_t inet_ms = pingTarget(g_internet_ping_target);

            char ping_json[150];
            snprintf(ping_json, sizeof(ping_json),
                     "{\"diag_ping\":{\"gw_ms\":%u,\"internet_ms\":%u}}",
                     gw_ms < 9000 ? gw_ms : 0,
                     inet_ms < 9000 ? inet_ms : 0);

            if (SerialBT.hasClient()) SerialBT.println(ping_json);
            Serial.println(ping_json);
        }
    } else {
        uint32_t sample_rate = g_config.sample_rate_hz > 0 ? g_config.sample_rate_hz : 10;
        uint32_t target_interval_ms = 1000 / sample_rate;

        // Pacing-basierte Taktung: Verhindert kumulativen Zeitdrift und hält exakt 1, 5 oder 10 Hz
        if (now - g_last_send_time >= target_interval_ms) {
            g_last_send_time += target_interval_ms;
            // Falls g_last_send_time zu weit zurückliegt (z. B. nach Ratenänderung), an 'now' anpassen
            if (now - g_last_send_time > target_interval_ms) {
                g_last_send_time = now;
            }

            TelemetrySnapshot s;
            if (g_tracker.getTelemetrySnapshot(s, now)) {
                char json_buf[320];
                snprintf(json_buf, sizeof(json_buf),
                         "{\"timestamp_ms\":%u,\"target_ssid\":\"%s\",\"bssid\":\"%s\",\"channel\":%u,\"rssi\":%d,\"noise_floor\":%d,\"snr\":%d,\"retry_rate\":%.1f,\"mod\":\"%s\",\"phy\":\"%s\",\"mcs\":%u}",
                         s.timestamp_ms,
                         s.ssid,
                         s.bssid_str,
                         s.channel,
                         s.rssi,
                         s.noise_floor,
                         s.snr,
                         s.retry_rate,
                         s.modulation,
                         s.phy_mode,
                         s.mcs);

                if (SerialBT.hasClient()) {
                    SerialBT.println(json_buf);
                }
                Serial.println(json_buf);
            } else {
                // Heartbeat ohne arretierte Ziel-SSID
                char json_buf[260];
                snprintf(json_buf, sizeof(json_buf),
                         "{\"timestamp_ms\":%u,\"target_ssid\":\"Warte auf Ziel\",\"bssid\":\"--\",\"channel\":%u,\"rssi\":-100,\"noise_floor\":-95,\"snr\":0,\"retry_rate\":0.0,\"mod\":\"Suche Signal...\",\"phy\":\"802.11\",\"mcs\":0}",
                         now, g_config.current_channel);

                if (SerialBT.hasClient()) {
                    SerialBT.println(json_buf);
                }
                Serial.println(json_buf);
            }
        }
    }

    vTaskDelay(1);
}
