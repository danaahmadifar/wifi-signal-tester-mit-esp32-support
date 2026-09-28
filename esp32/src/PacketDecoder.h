#pragma once
/**
 * ============================================================================
 * ESP32 Wi-Fi Analyzer - 802.11 Frame-Dekodierung & HF-Analyse (PacketDecoder.h)
 * ============================================================================
 * 
 * Funktionsumfang:
 * 1. MAC-Adressverarbeitung und Konvertierung (IEEE 802-Format).
 * 2. Auswertung der Empfänger-Hardware-Register (wifi_pkt_rx_ctrl_t):
 *    - Erkennung des PHY-Standards (Legacy 802.11b/g, 802.11n HT20/HT40, 802.11ac VHT).
 *    - Modulation and Coding Scheme (MCS 0 bis 7) sowie Bitratenbestimmung.
 * 3. Parser für Information Elements (IE) in 802.11 Management-Frames (Tag 0: SSID, Tag 3: DS Parameter).
 * 
 * Filtercharakteristik:
 * Zur selektiven Pegelbestimmung der Basisstation (Access Point) werden Upstream-Pakete
 * mobiler Endgeräte (Client Stations) verworfen. Da Endgeräte abweichende Sendeleistungen
 * und Antennengewinne aufweisen, würde deren Erfassung zu asymmetrischen Pegelsprüngen führen.
 * Es werden daher ausschließlich Management-Frames (Beacons, Probe Responses) sowie
 * Downlink-Datenpakete (FromDS=1, ToDS=0) ausgewertet.
 */

#include <Arduino.h>
#include "esp_wifi.h"

namespace PacketDecoder {

    /**
     * Konvertiert eine 6-Byte-MAC-Adresse in eine hexadezimale Zeichenkette (z. B. "AA:BB:CC:DD:EE:FF").
     */
    inline void macToString(const uint8_t* mac, char* out_str) {
        snprintf(out_str, 18, "%02X:%02X:%02X:%02X:%02X:%02X",
                 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    }

    /**
     * Parst eine hexadezimale Zeichenkette (Format "xx:xx:xx:xx:xx:xx") in ein 6-Byte-Array.
     * Rückgabewert: true bei erfolgreicher Syntaxprüfung, andernfalls false.
     */
    inline bool parseMacString(const char* str, uint8_t* mac_out) {
        if (!str || strlen(str) < 17) return false;
        unsigned int m[6];
        int parsed = sscanf(str, "%02x:%02x:%02x:%02x:%02x:%02x",
                            &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]);
        if (parsed == 6) {
            for (int i = 0; i < 6; i++) {
                mac_out[i] = (uint8_t)m[i];
            }
            return true;
        }
        return false;
    }

    /**
     * Vergleicht zwei 6-Byte-MAC-Adressen auf Identität.
     */
    inline bool compareMac(const uint8_t* mac1, const uint8_t* mac2) {
        for (int i = 0; i < 6; i++) {
            if (mac1[i] != mac2[i]) return false;
        }
        return true;
    }

    /**
     * Dekodiert die Hardware-Register des ESP32-Transceivers (wifi_pkt_rx_ctrl_t)
     * in textuelle Repräsentationen des Modulationsschemas und des PHY-Standards.
     */
    inline void decodeModulation(const wifi_pkt_rx_ctrl_t* rx_ctrl,
                                char* out_mod, size_t mod_len,
                                char* out_phy, size_t phy_len) {
        uint8_t sig_mode = rx_ctrl->sig_mode;
        uint8_t mcs = rx_ctrl->mcs;
        uint8_t cwb = rx_ctrl->cwb; // Kanalbandbreite: 0 = 20 MHz, 1 = 40 MHz

        // IEEE 802.11n (HT - High Throughput)
        if (sig_mode == 1 || sig_mode == 2) {
            snprintf(out_phy, phy_len, "802.11n (HT%d)", cwb ? 40 : 20);
            switch (mcs) {
                case 0: snprintf(out_mod, mod_len, "BPSK (MCS 0)"); break;
                case 1: snprintf(out_mod, mod_len, "QPSK 1/2 (MCS 1)"); break;
                case 2: snprintf(out_mod, mod_len, "QPSK 3/4 (MCS 2)"); break;
                case 3: snprintf(out_mod, mod_len, "16-QAM 1/2 (MCS 3)"); break;
                case 4: snprintf(out_mod, mod_len, "16-QAM 3/4 (MCS 4)"); break;
                case 5: snprintf(out_mod, mod_len, "64-QAM 2/3 (MCS 5)"); break;
                case 6: snprintf(out_mod, mod_len, "64-QAM 3/4 (MCS 6)"); break;
                case 7: snprintf(out_mod, mod_len, "64-QAM 5/6 (MCS 7)"); break;
                default: snprintf(out_mod, mod_len, "MCS %u", mcs); break;
            }
        }
        // IEEE 802.11ac (VHT - Very High Throughput)
        else if (sig_mode == 3) {
            snprintf(out_phy, phy_len, "802.11ac (VHT)");
            snprintf(out_mod, mod_len, "VHT (MCS %u)", mcs);
        }
        // Legacy IEEE 802.11b / 802.11g
        else {
            snprintf(out_phy, phy_len, "802.11b/g");
            uint32_t r = rx_ctrl->rate;
            switch (r) {
                case 0: snprintf(out_mod, mod_len, "DSSS (1 Mbps)"); break;
                case 1: snprintf(out_mod, mod_len, "DSSS (2 Mbps)"); break;
                case 2: snprintf(out_mod, mod_len, "CCK (5.5 Mbps)"); break;
                case 3: snprintf(out_mod, mod_len, "CCK (11 Mbps)"); break;
                case 0x0B: snprintf(out_mod, mod_len, "OFDM/BPSK (6 Mbps)"); break;
                case 0x0F: snprintf(out_mod, mod_len, "OFDM/BPSK (9 Mbps)"); break;
                case 0x0A: snprintf(out_mod, mod_len, "OFDM/QPSK (12 Mbps)"); break;
                case 0x0E: snprintf(out_mod, mod_len, "OFDM/QPSK (18 Mbps)"); break;
                case 0x09: snprintf(out_mod, mod_len, "OFDM/16-QAM (24 Mbps)"); break;
                case 0x0D: snprintf(out_mod, mod_len, "OFDM/16-QAM (36 Mbps)"); break;
                case 0x08: snprintf(out_mod, mod_len, "OFDM/64-QAM (48 Mbps)"); break;
                case 0x0C: snprintf(out_mod, mod_len, "OFDM/64-QAM (54 Mbps)"); break;
                default: snprintf(out_mod, mod_len, "OFDM (%u)", r); break;
            }
        }
    }

    /**
     * Parst Information Elements (IE) eines 802.11 Management-Frames (Beacon / Probe Response).
     * Extrahiert SSID (Tag 0) und Kanalangabe des Direct-Sequence-Parametersatzes (Tag 3).
     */
    inline bool parseBeaconTags(const uint8_t* payload, uint16_t sig_len,
                               char* out_ssid, size_t max_ssid_len,
                               uint8_t* out_channel) {
        if (sig_len < 38) return false;
        
        // Offset 36: Beginn der Information Elements nach 24B MAC-Header, 8B Timestamp, 2B Beacon Interval, 2B Capability Info
        uint16_t offset = 36;
        bool found_ssid = false;
        *out_channel = 0;

        while (offset + 1 < sig_len) {
            uint8_t tag_num = payload[offset];
            uint8_t tag_len = payload[offset + 1];
            if (offset + 2 + tag_len > sig_len) break;

            // Element ID 0: SSID
            if (tag_num == 0 && tag_len <= 32 && tag_len > 0) {
                size_t copy_len = (tag_len < max_ssid_len - 1) ? tag_len : (max_ssid_len - 1);
                memcpy(out_ssid, &payload[offset + 2], copy_len);
                out_ssid[copy_len] = '\0';
                found_ssid = true;
            }
            // Element ID 3: DS Parameter Set (Mittenfrequenzkanal)
            else if (tag_num == 3 && tag_len == 1) {
                *out_channel = payload[offset + 2];
            }

            offset += 2 + tag_len;
        }

        return found_ssid;
    }

} // namespace PacketDecoder
