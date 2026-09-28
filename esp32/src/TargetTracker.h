#pragma once
/**
 * ============================================================================
 * ESP32 Wi-Fi Analyzer - Zielverfolgung & BSSID-Hysterese (TargetTracker.h)
 * ============================================================================
 * 
 * Funktionsweise:
 * - Selektive Zustandserfassung des konfigurierten 802.11-Zielnetzwerks.
 * - Thread-sichere Pufferung zwischen dem RX-Interrupt-Kontext (Promiscuous Callback)
 *   und dem Haupt-Thread (Loop/Telemetrieversand) über FreeRTOS-Spinlocks (portMUX_TYPE).
 * - BSSID-Hysterese:
 *   In Multi-AP-Topologien (z. B. WLAN-Mesh oder Extended Service Sets) besitzen mehrere
 *   Access Points identische SSIDs bei distinkten MAC-Adressen. Die Hysterese arretiert
 *   die Messung auf die empfangsstärkste BSSID und führt ein Handover erst bei einem
 *   Signalstärkenvorteil von mindestens 8 dB oder einem Verbindungsabriss (> 2500 ms) durch.
 */

#include <Arduino.h>
#include "Config.h"
#include "PacketDecoder.h"

class TargetTracker {
public:
    TargetTracker() {
        clearTarget();
    }

    /**
     * Konfiguriert das zu analysierende Zielnetzwerk.
     */
    void setTarget(const char* ssid, const char* bssid_str = nullptr, uint8_t channel = 0) {
        if (!ssid || strlen(ssid) == 0) {
            clearTarget();
            return;
        }

        portENTER_CRITICAL(&m_mux);
        m_target = TargetNetwork();
        strncpy(m_target.ssid, ssid, sizeof(m_target.ssid) - 1);
        m_target.has_target = true;

        if (channel >= 1 && channel <= 13) {
            m_target.target_channel = channel;
            m_target.latest_channel = channel;
        }

        if (bssid_str && strlen(bssid_str) == 17) {
            if (PacketDecoder::parseMacString(bssid_str, m_target.target_bssid)) {
                m_target.filter_by_bssid = true;
                memcpy(m_target.locked_bssid, m_target.target_bssid, 6);
                m_target.has_locked_bssid = true;
            }
        }
        portEXIT_CRITICAL(&m_mux);
    }

    /**
     * Setzt die Zielkonfiguration zurück und versetzt das Modul in den Ruhezustand.
     */
    void clearTarget() {
        portENTER_CRITICAL(&m_mux);
        m_target = TargetNetwork();
        portEXIT_CRITICAL(&m_mux);
    }

    bool hasTarget() {
        portENTER_CRITICAL(&m_mux);
        bool ht = m_target.has_target;
        portEXIT_CRITICAL(&m_mux);
        return ht;
    }

    const char* getTargetSSID() {
        return m_target.ssid;
    }

    uint8_t getTargetChannel() {
        return m_target.target_channel;
    }

    /**
     * Verarbeitet ein empfangenes 802.11-Paket und prüft die Übereinstimmung mit dem Zielnetzwerk.
     * Rückgabewert: true bei Zuordnung zum Zielnetzwerk, andernfalls false.
     */
    bool processPacket(const uint8_t* transmitter_bssid,
                       const char* detected_ssid,
                       uint8_t frame_type,
                       bool is_retry,
                       const wifi_pkt_rx_ctrl_t* rx_ctrl,
                       uint32_t now) {
        if (!m_target.has_target) return false;

        bool matched = false;

        portENTER_CRITICAL(&m_mux);

        // 1. Kriterium: Explizite BSSID-Filterung
        if (m_target.filter_by_bssid && PacketDecoder::compareMac(transmitter_bssid, m_target.target_bssid)) {
            matched = true;
        }
        // 2. Kriterium: SSID-Übereinstimmung bei Management-Frames (Beacon / Probe Response)
        else if (frame_type == 0 && detected_ssid && strlen(detected_ssid) > 0) {
            if (strcasecmp(m_target.ssid, detected_ssid) == 0) {
                // BSSID-Hystereselogik:
                if (!m_target.has_locked_bssid || (now - m_target.locked_bssid_last_seen > 2500)) {
                    memcpy(m_target.locked_bssid, transmitter_bssid, 6);
                    m_target.has_locked_bssid = true;
                    m_target.locked_bssid_rssi = rx_ctrl->rssi;
                    m_target.locked_bssid_last_seen = now;
                    matched = true;
                } else if (PacketDecoder::compareMac(m_target.locked_bssid, transmitter_bssid)) {
                    m_target.locked_bssid_rssi = rx_ctrl->rssi;
                    m_target.locked_bssid_last_seen = now;
                    matched = true;
                } else if (rx_ctrl->rssi > m_target.locked_bssid_rssi + 8) {
                    // Handover bei signifikantem Pegelvorteil (Delta >= 8 dB)
                    memcpy(m_target.locked_bssid, transmitter_bssid, 6);
                    m_target.has_locked_bssid = true;
                    m_target.locked_bssid_rssi = rx_ctrl->rssi;
                    m_target.locked_bssid_last_seen = now;
                    matched = true;
                }
            }
        }
        // 3. Kriterium: Downlink-Datenpakete (Frame Type 2) der arretierten BSSID
        else if (frame_type == 2 && m_target.has_locked_bssid) {
            if (PacketDecoder::compareMac(m_target.locked_bssid, transmitter_bssid)) {
                matched = true;
            }
        }

        // Aktualisierung der physikalischen Parameter bei Treffer
        if (matched) {
            m_target.latest_rssi = rx_ctrl->rssi;
            m_target.latest_noise_floor = rx_ctrl->noise_floor;
            m_target.latest_snr = (int32_t)rx_ctrl->rssi - (int32_t)rx_ctrl->noise_floor;

            // Exponentiell geglättete Wiederholungsrate (802.11 Retry-Rate in %)
            float retry_sample = is_retry ? 100.0f : 0.0f;
            m_target.retry_rate = m_target.retry_rate * 0.90f + retry_sample * 0.10f;

            if (rx_ctrl->channel >= 1 && rx_ctrl->channel <= 13) {
                m_target.latest_channel = rx_ctrl->channel;
            }
            m_target.latest_mcs = rx_ctrl->mcs;
            m_target.latest_timestamp_ms = now;
            m_target.packet_count++;

            PacketDecoder::decodeModulation(
                rx_ctrl,
                m_target.latest_mod, sizeof(m_target.latest_mod),
                m_target.latest_phy, sizeof(m_target.latest_phy)
            );
        }

        portEXIT_CRITICAL(&m_mux);
        return matched;
    }

    /**
     * Erzeugt einen konsistenten Telemetrie-Snapshot zur Übertragung an den Host-PC.
     */
    bool getTelemetrySnapshot(TelemetrySnapshot& out, uint32_t now) {
        portENTER_CRITICAL(&m_mux);
        if (!m_target.has_target) {
            portEXIT_CRITICAL(&m_mux);
            return false;
        }

        strncpy(out.ssid, m_target.ssid, sizeof(out.ssid) - 1);
        out.ssid[sizeof(out.ssid) - 1] = '\0';

        if (m_target.has_locked_bssid) {
            PacketDecoder::macToString(m_target.locked_bssid, out.bssid_str);
        } else {
            strncpy(out.bssid_str, "--", sizeof(out.bssid_str));
        }

        out.channel = (m_target.packet_count > 0) ? m_target.latest_channel : m_target.target_channel;
        
        // Timeout-Prüfung: Signalverlust nach Überschreitung von SIGNAL_TIMEOUT_MS
        if (now - m_target.latest_timestamp_ms < SIGNAL_TIMEOUT_MS && m_target.packet_count > 0) {
            out.rssi = m_target.latest_rssi;
            out.noise_floor = m_target.latest_noise_floor;
            out.snr = m_target.latest_snr;
            out.retry_rate = m_target.retry_rate;
        } else {
            out.rssi = -100;
            out.noise_floor = -95;
            out.snr = 0;
            out.retry_rate = 0.0f;
        }

        strncpy(out.modulation, m_target.latest_mod, sizeof(out.modulation) - 1);
        out.modulation[sizeof(out.modulation) - 1] = '\0';

        strncpy(out.phy_mode, m_target.latest_phy, sizeof(out.phy_mode) - 1);
        out.phy_mode[sizeof(out.phy_mode) - 1] = '\0';

        out.mcs = m_target.latest_mcs;
        out.timestamp_ms = m_target.latest_timestamp_ms > 0 ? m_target.latest_timestamp_ms : now;
        out.packet_count = m_target.packet_count;

        portEXIT_CRITICAL(&m_mux);
        return true;
    }

private:
    TargetNetwork m_target;
    portMUX_TYPE m_mux = portMUX_INITIALIZER_UNLOCKED;
};
