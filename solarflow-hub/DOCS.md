# SolarFlow Hub 2000 + ACE 1500 - Home Assistant Addon

MQTT Topic Transformer für Zendure SolarFlow Hub 2000 in Verbindung mit ACE 1500.
**Keine Cloud, kein Token nötig.**

## Voraussetzungen

1. Hub 2000 **und** ACE 1500 sind über den **Solarflow BT-Manager** auf lokales MQTT umgestellt (beide Geräte einzeln)
2. Lokaler MQTT Broker läuft (z.B. Mosquitto Addon)
3. MQTT Integration in Home Assistant ist eingerichtet

## IDs herausfinden

Mit [MQTT Explorer](https://mqtt-explorer.com) am Broker anmelden und kurz warten. Es erscheinen zwei Zweige:

```
▼ A8yh63          ← Hub 2000 (hub_product_id)
  ▼ XXXXXXXX      ← hub_device_id
▼ 8bM93H          ← ACE 1500 (ace_product_id)
  ▼ YYYYYYYY      ← ace_device_id
```

Bleiben beide Device-IDs leer, hört das Addon auf alle Zendure-Geräte am Broker.

## Konfiguration

| Option | Beschreibung | Beispiel |
|--------|-------------|---------|
| `mqtt_host` | IP des MQTT Brokers | `192.168.1.10` |
| `mqtt_port` | MQTT Port | `1883` |
| `mqtt_user` / `mqtt_password` | MQTT Zugang (optional) | `zendure` |
| `hub_product_id` | Product ID Hub 2000 | `A8yh63` |
| `hub_device_id` | Device ID Hub 2000 | `XXXXXXXX` |
| `ace_product_id` | Product ID ACE 1500 | `8bM93H` |
| `ace_device_id` | Device ID ACE 1500 | `YYYYYYYY` |
| `ha_discovery` | HA MQTT Discovery | `true` |
| `ha_prefix` | Discovery Prefix | `homeassistant` |
| `poll_interval` | Abfrageintervall in Sekunden | `30` |

## Was in Home Assistant erscheint

Zwei Geräte („SolarFlow Hub 2000 (…)“ und „ACE 1500 (…)“) plus je Batterie ein Gerät.
Entitäten entstehen erst, wenn das Gerät das Feld meldet, typisch:

- **Hub 2000:** Solar-/Pack-/Home-Leistung, Ladezustand, `outputLimit`, `inverseMaxPower`, SOC-Grenzen, Bypass-Modus, Buzzer, „ACE verbunden“
- **ACE 1500:** Netzleistung (`gridInputPower`), DC-Ausgang, AC-/DC-Schalter, AC-Modus, `inputLimit` (0–900 W in 100er-Schritten)

Topics: `solarflow-hub/<device_id>/telemetry/<feld>`, Status `solarflow-hub/<device_id>/status`.

## Hinweis Flash-Speicher

Schreibzugriffe auf `inputLimit`, `outputLimit` und `acMode` landen ohne aktiven **Smart Mode** im Flash des Geräts.
Für häufige Regelung (z.B. Nulleinspeisung per Automation) vorher Smart Mode einschalten.

## Parallel zum Hyper-Addon

Beide Addons können gleichzeitig laufen (eigene MQTT-Client-ID, eigene Topics und Unique-IDs).
