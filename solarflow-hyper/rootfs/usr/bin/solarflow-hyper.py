#!/usr/bin/env python3
"""
SolarFlow Hyper - Auto-Discovery MQTT Topic Transformer
Automatically discovers all Zendure devices on the MQTT broker.

Reads:  /<product_id>/<device_id>/properties/report
        /<product_id>/<device_id>/properties/energy
Writes: solarflow-hyper/<device_id>/telemetry/<key>
        solarflow-hyper/<device_id>/telemetry/batteries/<sn>/<key>
        solarflow-hyper/<device_id>/status

With HA_DISCOVERY=true, also publishes MQTT discovery messages so
devices appear automatically in Home Assistant without any mqtt.yaml.
"""

import json
import logging
import os
import time
import threading
import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s: %(message)s")
log = logging.getLogger("solarflow-hyper")

MQTT_HOST     = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USER     = os.environ.get("MQTT_USER", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
HA_DISCOVERY  = os.environ.get("HA_DISCOVERY", "true").lower() == "true"
HA_PREFIX     = os.environ.get("HA_PREFIX", "homeassistant")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 30))
PRODUCT_ID    = os.environ.get("PRODUCT_ID", "")
DEVICE_ID     = os.environ.get("DEVICE_ID", "")
OUTPUT_PREFIX = "solarflow-hyper"

discovered_devices = {}
_msg_id = 0


def next_msg_id():
    global _msg_id
    _msg_id += 1
    return _msg_id


def poll_devices(client):
    while True:
        time.sleep(POLL_INTERVAL)
        for device_id, info in list(discovered_devices.items()):
            product_id = info["product_id"]
            topic = f"iot/{product_id}/{device_id}/properties/read"
            payload = json.dumps({
                "messageId": next_msg_id(),
                "deviceId": device_id,
                "properties": ["getAll"]
            })
            client.publish(topic, payload)
            log.debug(f"Polled {device_id}")


PROPERTY_FIELDS = {
    "hubState":        {"name": "Hub State",            "type": "sensor"},
    "solarInputPower": {"name": "Solar Input Power",    "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "packInputPower":  {"name": "Pack Input Power",     "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "outputPackPower": {"name": "Output Pack Power",    "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "outputHomePower": {"name": "Output Home Power",    "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "acOutputPower":   {"name": "AC Output Power",      "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "gridInputPower":  {"name": "Grid Input Power",     "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "outputPower":     {"name": "Output Power",         "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "chargePower":     {"name": "Charge Power",         "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "solarPower1":     {"name": "Solar Power 1",        "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement", "icon": "mdi:solar-panel"},
    "solarPower2":     {"name": "Solar Power 2",        "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement", "icon": "mdi:solar-panel"},
    "outputLimit":     {"name": "Output Limit",         "type": "number", "unit": "W",   "device_class": "power",            "min": 0,  "max": 1200},
    "inputLimit":      {"name": "Input Limit",          "type": "number", "unit": "W",   "device_class": "power",            "min": 0,  "max": 1200},
    "inverseMaxPower": {"name": "Inverter Limit",       "type": "number", "unit": "W",   "min": 0,  "max": 2400},
    "chargeLimit":     {"name": "Charge Limit AC",      "type": "number", "unit": "W",   "min": 0,  "max": 1200},
    "remainOutTime":   {"name": "Remain Out Time",      "type": "sensor", "unit": "min", "device_class": "duration"},
    "remainInputTime": {"name": "Remain Input Time",    "type": "sensor", "unit": "min", "device_class": "duration"},
    "electricLevel":   {"name": "Electric Level",       "type": "sensor", "unit": "%",   "device_class": "battery"},
    "socSet":          {"name": "Charge SOC Limit",     "type": "number", "unit": "%",   "min": 5,  "max": 100,
                        "value_template": "{{ (value | float * 0.1) | round(0) | int }}",
                        "cmd_template":   '{"properties": {"socSet": {{ (value | float * 10) | int }} }}'},
    "minSoc":          {"name": "Discharge SOC Limit",  "type": "number", "unit": "%",   "min": 5,  "max": 35,
                        "value_template": "{{ (value | float * 0.1) | round(0) | int }}",
                        "cmd_template":   '{"properties": {"minSoc": {{ (value | float * 10) | int }} }}'},
    "packNum":         {"name": "Pack Num",              "type": "sensor", "icon": "mdi:battery-check-outline"},
    "packState":       {"name": "Pack State",            "type": "sensor",
                        "value_template": "{{ 'Standby' if value=='0' else ('Laden' if value=='1' else ('Entladen' if value=='2' else 'Unknown')) }}",
                        "icon": "mdi:battery-sync-outline"},
    "hyperTmp":        {"name": "Temperatur",            "type": "sensor", "unit": "°C",  "device_class": "temperature",
                        "value_template": "{{ (value | float / 10 - 273.15) | round(1) }}"},
    "faultLevel":      {"name": "Fault Level",           "type": "sensor", "icon": "mdi:alert-circle-outline"},
    "strength":        {"name": "WLAN Signal",            "type": "sensor", "unit": "dBm", "device_class": "signal_strength", "entity_category": "diagnostic"},
    "mode":            {"name": "Modus",                 "type": "sensor", "icon": "mdi:cog"},
    "autoModel":       {"name": "Auto Model",            "type": "sensor", "icon": "mdi:auto-mode"},
    "gridOffMode":     {"name": "Grid Off Mode",         "type": "sensor", "icon": "mdi:transmission-tower-off"},
    "phaseSwitch":     {"name": "Phase Switch",          "type": "sensor", "icon": "mdi:electric-switch"},
    "localState":      {"name": "Local State",           "type": "sensor", "icon": "mdi:lan"},
    "chargingType":    {"name": "Charging Type",         "type": "sensor", "icon": "mdi:ev-plug-type1"},
    "chargingMode":    {"name": "Charging Mode",         "type": "sensor", "icon": "mdi:battery-charging"},
    "socLimit":        {"name": "SOC Limit",             "type": "sensor", "unit": "%",   "icon": "mdi:battery-lock"},
    "masterSwitch":    {"name": "Master Switch",         "type": "switch"},
    "buzzerSwitch":    {"name": "Buzzer",                 "type": "switch", "icon": "mdi:bullhorn-outline"},
    "hemsState":       {"name": "HEMS State",             "type": "switch", "icon": "mdi:home-lightning-bolt"},
    "wifiState":       {"name": "WiFi",                   "type": "binary_sensor", "device_class": "connectivity", "entity_category": "diagnostic"},
    "heatState":       {"name": "Heizung",                "type": "binary_sensor", "icon": "mdi:heating-coil"},
    "ctOff":           {"name": "CT Off",                 "type": "binary_sensor", "icon": "mdi:current-ac"},
    "gridReverse":     {"name": "Grid Reverse",           "type": "binary_sensor", "icon": "mdi:transmission-tower"},
    "acMode":          {"name": "AC Modus",               "type": "select",
                        "options": {"0": "Aus", "1": "AC Laden", "2": "AC Entladen"}},
    "pass":            {"name": "Pass Mode",              "type": "select",
                        "options": {"0": "Automatisch", "1": "Immer aus", "2": "Immer ein"}},
}

BATTERY_FIELDS = {
    "maxTemp":     {"name": "Temperatur",  "type": "sensor", "unit": "°C", "device_class": "temperature",
                    "value_template": "{{ (value | float / 10 - 273.15) | round(1) }}"},
    "totalVol":    {"name": "Spannung",    "type": "sensor", "unit": "V",  "device_class": "voltage",
                    "value_template": "{{ (value | float / 100) | round(1) }}"},
    "maxVol":      {"name": "Zelle Max V", "type": "sensor", "unit": "V",  "device_class": "voltage",
                    "value_template": "{{ (value | float / 100) | round(2) }}", "icon": "mdi:alpha-v-circle-outline"},
    "minVol":      {"name": "Zelle Min V", "type": "sensor", "unit": "V",  "device_class": "voltage",
                    "value_template": "{{ (value | float / 100) | round(2) }}", "icon": "mdi:alpha-v-circle-outline"},
    "batcur":      {"name": "Strom",       "type": "sensor", "unit": "A",  "device_class": "current",
                    "value_template": "{{ (value | float / 10) | round(1) }}"},
    "socLevel":    {"name": "Ladezustand", "type": "sensor", "unit": "%",  "device_class": "battery"},
    "state":       {"name": "Status",      "type": "sensor",
                    "value_template": "{{ 'Standby' if value=='0' else ('Laden' if value=='1' else ('Entladen' if value=='2' else 'Unknown')) }}",
                    "icon": "mdi:battery-sync-outline"},
    "power":       {"name": "Leistung",    "type": "sensor", "unit": "W",  "device_class": "power", "state_class": "measurement"},
    "softVersion": {"name": "Firmware",    "type": "sensor", "icon": "mdi:chip", "entity_category": "diagnostic"},
}

FILTER_FIELDS = {
    "remainOutTime":   59900,
    "remainInputTime": 59900,
}


def build_select_templates(field, options_map):
    vt = ""
    ct = ""
    for i, (k, v) in enumerate(options_map.items()):
        kw = "if" if i == 0 else "elif"
        vt += f"{{% {kw} value == '{k}' %}}{v}\n"
        ct += f"{{% {kw} value == '{v}' %}}{json.dumps({'properties': {field: int(k)}})}\n"
    vt += "{% else %}Unbekannt\n{% endif %}"
    ct += "{% endif %}"
    return vt, ct


def publish_ha_discovery_device(client, device_id, product_id):
    write_topic  = f"iot/{product_id}/{device_id}/properties/write"
    status_topic = f"{OUTPUT_PREFIX}/{device_id}/status"
    dev_info = {
        "identifiers": [device_id],
        "name": f"SolarFlow Hyper ({device_id})",
        "manufacturer": "Zendure",
        "model": "Hyper 2000",
    }

    # Online/offline status sensor
    client.publish(f"{HA_PREFIX}/binary_sensor/hyper_{device_id}_status/config", json.dumps({
        "name": "Status",
        "unique_id": f"hyper_{device_id}_status",
        "state_topic": status_topic,
        "device": dev_info,
        "icon": "mdi:power",
        "payload_on": "online",
        "payload_off": "offline",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
    }), retain=True)

    for field, cfg in PROPERTY_FIELDS.items():
        unique_id   = f"hyper_{device_id}_{field}"
        state_topic = f"{OUTPUT_PREFIX}/{device_id}/telemetry/{field}"
        etype       = cfg["type"]

        p = {
            "name":                  cfg["name"],
            "unique_id":             unique_id,
            "state_topic":           state_topic,
            "device":                dev_info,
            "availability_topic":    status_topic,
            "payload_available":     "online",
            "payload_not_available": "offline",
        }
        if "unit" in cfg:
            p["unit_of_measurement"] = cfg["unit"]
        for k in ("device_class", "state_class", "icon", "entity_category"):
            if k in cfg:
                p[k] = cfg[k]
        if "value_template" in cfg:
            p["value_template"] = cfg["value_template"]

        if etype == "number":
            p.update({
                "command_topic":    write_topic,
                "min":              cfg.get("min", 0),
                "max":              cfg.get("max", 1200),
                "step":             1,
                "mode":             "box",
                "command_template": cfg.get("cmd_template", f'{{"properties": {{"{field}": {{{{ value | int }}}} }}}}'),
            })
            disc = f"{HA_PREFIX}/number/{unique_id}/config"

        elif etype == "switch":
            p.update({
                "command_topic": write_topic,
                "payload_on":    json.dumps({"properties": {field: 1}}),
                "payload_off":   json.dumps({"properties": {field: 0}}),
                "state_on":      1,
                "state_off":     0,
            })
            disc = f"{HA_PREFIX}/switch/{unique_id}/config"

        elif etype == "binary_sensor":
            p.update({"payload_on": "1", "payload_off": "0"})
            disc = f"{HA_PREFIX}/binary_sensor/{unique_id}/config"

        elif etype == "select":
            options_map = cfg["options"]
            vt, ct = build_select_templates(field, options_map)
            p.update({
                "options":          list(options_map.values()),
                "command_topic":    write_topic,
                "value_template":   vt,
                "command_template": ct,
            })
            disc = f"{HA_PREFIX}/select/{unique_id}/config"

        else:
            disc = f"{HA_PREFIX}/sensor/{unique_id}/config"

        client.publish(disc, json.dumps(p), retain=True)

    log.info(f"HA discovery published for device {device_id}")


def publish_ha_discovery_battery(client, device_id, sn, bat_num):
    status_topic = f"{OUTPUT_PREFIX}/{device_id}/status"
    dev_info = {
        "identifiers": [sn],
        "name": f"Batterie {bat_num} ({sn[-6:]})",
        "manufacturer": "Zendure",
        "model": "AB2000",
        "via_device": device_id,
    }

    for field, cfg in BATTERY_FIELDS.items():
        unique_id   = f"hyper_{device_id}_bat_{sn}_{field}"
        state_topic = f"{OUTPUT_PREFIX}/{device_id}/telemetry/batteries/{sn}/{field}"

        p = {
            "name":                  cfg["name"],
            "unique_id":             unique_id,
            "state_topic":           state_topic,
            "device":                dev_info,
            "availability_topic":    status_topic,
            "payload_available":     "online",
            "payload_not_available": "offline",
        }
        if "unit" in cfg:
            p["unit_of_measurement"] = cfg["unit"]
        for k in ("device_class", "state_class", "icon", "entity_category"):
            if k in cfg:
                p[k] = cfg[k]
        if "value_template" in cfg:
            p["value_template"] = cfg["value_template"]

        client.publish(f"{HA_PREFIX}/sensor/{unique_id}/config", json.dumps(p), retain=True)

    log.info(f"HA discovery published for battery {bat_num} ({sn})")


def register_battery(client, device_id, product_id, sn):
    if sn not in discovered_devices[device_id]["batteries"]:
        discovered_devices[device_id]["batteries"].add(sn)
        bat_num = len(discovered_devices[device_id]["batteries"])
        log.info(f"New battery: {sn} (#{bat_num}) on {device_id}")
        if HA_DISCOVERY:
            publish_ha_discovery_battery(client, device_id, sn, bat_num)


def handle_report(client, product_id, device_id, payload):
    if device_id not in discovered_devices:
        discovered_devices[device_id] = {"product_id": product_id, "batteries": set()}
        log.info(f"New device: {device_id} (product: {product_id})")
        if HA_DISCOVERY:
            publish_ha_discovery_device(client, device_id, product_id)

    # Update online status
    client.publish(f"{OUTPUT_PREFIX}/{device_id}/status", "online", retain=True)

    props = payload.get("properties", {})

    for field in PROPERTY_FIELDS:
        if field in props:
            value = props[field]
            if field in FILTER_FIELDS and value >= FILTER_FIELDS[field]:
                continue
            client.publish(
                f"{OUTPUT_PREFIX}/{device_id}/telemetry/{field}",
                str(value),
                retain=True
            )

    for pack in payload.get("packData", []):
        sn = pack.get("sn")
        if not sn:
            continue
        register_battery(client, device_id, product_id, sn)
        for field in BATTERY_FIELDS:
            if field in pack:
                client.publish(
                    f"{OUTPUT_PREFIX}/{device_id}/telemetry/batteries/{sn}/{field}",
                    str(pack[field]),
                    retain=True
                )


def handle_energy(client, product_id, device_id, payload):
    if device_id not in discovered_devices:
        return
    props = payload.get("properties", {})
    for field in ["outputPower", "chargePower", "mode"]:
        if field in props:
            client.publish(
                f"{OUTPUT_PREFIX}/{device_id}/telemetry/{field}",
                str(props[field]),
                retain=True
            )


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log.info(f"Connected to MQTT {MQTT_HOST}:{MQTT_PORT}")

        if PRODUCT_ID and DEVICE_ID:
            # Subscribe with and without leading slash
            for prefix in [PRODUCT_ID, f"/{PRODUCT_ID}"]:
                client.subscribe(f"{prefix}/{DEVICE_ID}/properties/report")
                client.subscribe(f"{prefix}/{DEVICE_ID}/properties/energy")
                client.subscribe(f"{prefix}/{DEVICE_ID}/telemetry/batteries/#")

            log.info(f"Subscribed to: {PRODUCT_ID}/{DEVICE_ID}/properties/report")
            log.info(f"Subscribed to: {PRODUCT_ID}/{DEVICE_ID}/properties/energy")

            # Initial poll
            client.publish(
                f"iot/{PRODUCT_ID}/{DEVICE_ID}/properties/read",
                json.dumps({"messageId": next_msg_id(), "deviceId": DEVICE_ID, "properties": ["getAll"]})
            )
            log.info(f"Initial poll sent to {PRODUCT_ID}/{DEVICE_ID}")

            # Publish online
            client.publish(f"{OUTPUT_PREFIX}/{DEVICE_ID}/status", "online", retain=True)
        else:
            client.subscribe("+/+/properties/report")
            client.subscribe("+/+/properties/energy")
            client.subscribe("+/+/telemetry/batteries/#")
            log.warning("No PRODUCT_ID/DEVICE_ID - subscribing to all topics")

        # Re-poll known devices
        for device_id, info in list(discovered_devices.items()):
            product_id = info["product_id"]
            client.publish(
                f"iot/{product_id}/{device_id}/properties/read",
                json.dumps({"messageId": next_msg_id(), "deviceId": device_id, "properties": ["getAll"]})
            )
    else:
        log.error(f"Connection failed rc={reason_code}")


def on_message(client, userdata, msg):
    topic = msg.topic
    parts = topic.split("/")

    # Remove leading empty string from leading slash
    if parts and parts[0] == "":
        parts = parts[1:]

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        log.warning(f"JSON parse error on {topic}: {e}")
        return

    if len(parts) < 4:
        return

    product_id = parts[0]
    device_id  = parts[1]

    if parts[2] == "properties" and parts[3] == "report":
        handle_report(client, product_id, device_id, payload)

    elif parts[2] == "properties" and parts[3] == "energy":
        handle_energy(client, product_id, device_id, payload)

    elif len(parts) == 6 and parts[2] == "telemetry" and parts[3] == "batteries":
        sn    = parts[4]
        field = parts[5]
        if device_id not in discovered_devices:
            discovered_devices[device_id] = {"product_id": product_id, "batteries": set()}
            if HA_DISCOVERY:
                publish_ha_discovery_device(client, device_id, product_id)
        register_battery(client, device_id, product_id, sn)
        client.publish(
            f"{OUTPUT_PREFIX}/{device_id}/telemetry/batteries/{sn}/{field}",
            msg.payload.decode("utf-8"),
            retain=True
        )


def main():
    log.info("SolarFlow Hyper MQTT Transformer starting...")
    log.info(f"  Broker:        {MQTT_HOST}:{MQTT_PORT}")
    log.info(f"  Device:        {PRODUCT_ID}/{DEVICE_ID}")
    log.info(f"  HA Discovery:  {HA_DISCOVERY}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="solarflow-hyper-transformer")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    if DEVICE_ID:
        client.will_set(f"{OUTPUT_PREFIX}/{DEVICE_ID}/status", "offline", retain=True)

    client.on_connect = on_connect
    client.on_message = on_message

    poll_thread = threading.Thread(target=poll_devices, args=(client,), daemon=True)
    poll_thread.start()
    log.info(f"Polling every {POLL_INTERVAL}s")

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as e:
            log.error(f"MQTT error: {e} — retrying in 10s")
            time.sleep(10)


if __name__ == "__main__":
    main()
