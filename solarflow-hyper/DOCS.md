# SolarFlow Hyper - Home Assistant Addon

MQTT Topic Transformer für Zendure Hyper 2000.  
**Kein DTU, keine Cloud, kein Token nötig.**

## Voraussetzungen

1. Zendure Gerät muss über den **Solarflow BT-Manager** auf lokales MQTT umgestellt sein
2. Lokaler MQTT Broker muss laufen (z.B. EMQX oder Mosquitto Addon)
3. MQTT Integration in Home Assistant muss eingerichtet sein

## Product ID und Device ID herausfinden

Nachdem du dein Gerät mit dem Solarflow BT-Manager auf lokales MQTT umgestellt hast, sendet es automatisch Daten an deinen Broker. So findest du deine IDs:

### Mit MQTT Explorer (empfohlen)

1. Lade [MQTT Explorer](https://mqtt-explorer.com) herunter und installiere ihn
2. Verbinde dich mit deinem lokalen MQTT Broker
3. Warte kurz bis Nachrichten ankommen
4. Du siehst ein Topic-Baum wie diesen:
   ```
   ▼ gDa3tb          ← das ist deine PRODUCT_ID
     ▼ XXXXXXXX      ← das ist deine DEVICE_ID
       ▼ properties
           report
   ```
5. Trage beide Werte in die Addon-Konfiguration ein

### Bekannte Product IDs

| Gerät | Product ID |
|-------|-----------|
| Hyper 2000 | `gDa3tb` |
| Hub 2000 | `A8yh63` |
| Hub 1200 | `73bkTV` |
| ACE 1500 | `8bM93H` |

## Konfiguration

| Option | Beschreibung | Beispiel |
|--------|-------------|---------|
| `mqtt_host` | IP deines MQTT Brokers | `192.168.1.10` |
| `mqtt_port` | MQTT Port | `1883` |
| `mqtt_user` | MQTT Benutzername (optional) | `zendure` |
| `mqtt_password` | MQTT Passwort (optional) | `geheim` |
| `product_id` | Product ID deines Geräts | `gDa3tb` |
| `device_id` | Device ID deines Geräts | `XXXXXXXX` |
| `ha_discovery` | HA MQTT Discovery aktivieren | `true` |
| `ha_prefix` | HA Discovery Prefix | `homeassistant` |
| `poll_interval` | Abfrageintervall in Sekunden | `30` |

## Wie es funktioniert

Das Addon sendet beim Start und alle `poll_interval` Sekunden eine Anfrage an dein Gerät:
```
iot/<product_id>/<device_id>/properties/read
{"messageId": 1, "deviceId": "<device_id>", "properties": ["getAll"]}
```

Das Gerät antwortet dann mit allen aktuellen Werten auf:
```
<product_id>/<device_id>/properties/report
```

Das Addon transformiert diese Daten in übersichtliche Einzeltopics:
```
solarflow-hyper/<device_id>/telemetry/outputLimit
solarflow-hyper/<device_id>/telemetry/electricLevel
solarflow-hyper/<device_id>/telemetry/batteries/<sn>/socLevel
```

Mit `ha_discovery: true` erscheinen alle Entitäten automatisch in Home Assistant ohne mqtt.yaml!

## Steuerung (Schreiben)

Um Werte zu setzen, publiziere direkt ans Gerät:
```
iot/<product_id>/<device_id>/properties/write
{"properties": {"outputLimit": 200}}
```

Die number/switch/select Entitäten in HA machen das automatisch.
