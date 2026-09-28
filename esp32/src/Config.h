#pragma once
/**
 * ============================================================================
 * ESP32 Wi-Fi Analyzer - Systemkonfiguration & Datenstrukturen (Config.h)
 * ============================================================================
 * 
 * Architekturübersicht:
 * - Kanalpersistenz: Der Transceiver verbleibt auf der Mittenfrequenz des Zielnetzwerks,
 *   um Messlücken durch Kanalabtastung während der Messreihe zu vermeiden.
 * - HF-Koexistenz: Synchronisation der Telemetrierate (10 Hz) auf das Beacon-Intervall
 *   (100 TU ~ 102.4 ms) zur Vermeidung von Sende-/Empfangskonflikten zwischen Bluetooth SPP
 *   und Wi-Fi Promiscuous RX im 2,4-GHz-ISM-Band.
 * - BSSID-Hysterese: Unterdrückung von Ping-Pong-Effekten in Multi-AP-Topologien (ESS/Mesh).
 */

#include <Arduino.h>

// ============================================================================
// HARDWARE- & STANDARDPARAMETER
// ============================================================================

// Kennung für Bluetooth Classic (SPP-Profil)
#define BT_DEVICE_NAME        "ESP32_WiFi_Tester"

// Status-LED Pin (GPIO 2 auf ESP32 DevKit V1)
#define STATUS_LED_PIN        2

// Standardkanal für das 2,4-GHz-ISM-Band (Kanal 1 bis 13)
#define DEFAULT_CHANNEL       6

// Abtast- und Telemetrierate (10 Hz = 100 ms Intervall)
#define DEFAULT_RATE_HZ       10

// Signal-Timeout in Millisekunden
// Kompensiert temporäre Paketverluste durch Bluetooth-Sendefenster
#define SIGNAL_TIMEOUT_MS     2000

// ============================================================================
// DATENSTRUKTUR: ZIELNETZWERK (SINGLE-TARGET-MODUS)
// ============================================================================
struct TargetNetwork {
    char ssid[33] = {0};                // Service Set Identifier (max. 32 Oktette)
    uint8_t target_bssid[6] = {0};      // Optionale Filter-BSSID (MAC-Adresse)
    bool filter_by_bssid = false;       // Selektion ausschließlich nach BSSID
    
    // BSSID-Arretierung und Hystereseparameter
    uint8_t locked_bssid[6] = {0};
    bool has_locked_bssid = false;
    int32_t locked_bssid_rssi = -100;
    uint32_t locked_bssid_last_seen = 0;

    // Aktuelle Mess- und Zustandsdaten
    uint8_t target_channel = DEFAULT_CHANNEL;
    int32_t latest_rssi = -100;
    int8_t latest_noise_floor = -95;
    int32_t latest_snr = 0;
    float retry_rate = 0.0f;
    uint8_t latest_channel = DEFAULT_CHANNEL;
    char latest_mod[32] = "N/A";
    char latest_phy[24] = "N/A";
    uint8_t latest_mcs = 0;
    uint32_t latest_timestamp_ms = 0;
    uint32_t packet_count = 0;
    bool has_target = false;
};

// ============================================================================
// GLOBALE SYSTEMKONFIGURATION
// ============================================================================
struct GlobalConfig {
    uint8_t current_channel = DEFAULT_CHANNEL;
    bool auto_channel = false;          // Automatischer Kanalsuchlauf bei Signalverlust
    uint16_t sample_rate_hz = DEFAULT_RATE_HZ;
};

// ============================================================================
// TELEMETRIE-DATENSATZ (SERIALISIERUNG FÜR PC-SCHNITTSTELLE)
// ============================================================================
struct TelemetrySnapshot {
    char ssid[33];
    char bssid_str[18];
    uint8_t channel;
    int32_t rssi;
    int8_t noise_floor;
    int32_t snr;
    float retry_rate;
    char modulation[32];
    char phy_mode[24];
    uint8_t mcs;
    uint32_t timestamp_ms;
    uint32_t packet_count;
};
