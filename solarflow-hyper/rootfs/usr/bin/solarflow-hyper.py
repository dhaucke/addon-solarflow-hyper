#!/usr/bin/env python3
"""
SolarFlow Hyper - Auto-Discovery MQTT Topic Transformer
Automatically discovers all Zendure devices on the MQTT broker.

Reads:  <product_id>/<device_id>/properties/report
Writes: solarflow-hyper/<device_id>/telemetry/<key>
        solarflow-hyper/<device_id>/telemetry/batteries/<sn>/<key>

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
OUTPUT_PREFIX = "solarflow-hyper"
PRODUCT_ID    = os.environ.get("PRODUCT_ID", "")
DEVICE_ID     = os.environ.get("DEVICE_ID", "")

# Discovered devices: { device_id: { product_id, batteries: set() } }
discovered_devices = {}
_msg_id = 0


def next_msg_id():
    global _msg_id
    _msg_id += 1
    return _msg_id


def poll_devices(client):
    """Periodically send getAll request to all known devices."""
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
            log.debug(f"Polled {device_id} via {topic}")

PROPERTY_FIELDS = {
    "hubState":        {"name": "Hub State",         "type": "sensor"},
    "solarInputPower": {"name": "Solar Input Power", "type": "sensor", "unit": "W",   "device_class": "power",       "state_class": "measurement"},
    "packInputPower":  {"name": "Pack Input Power",  "type": "sensor", "unit": "W",   "device_class": "power",       "state_class": "measurement"},
    "outputPackPower": {"name": "Output Pack Power", "type": "sensor", "unit": "W",   "device_class": "power",       "state_class": "measurement"},
    "outputHomePower": {"name": "Output Home Power", "type": "sensor", "unit": "W",   "device_class": "power",       "state_class": "measurement"},
    "outputLimit":     {"name": "Output Limit",      "type": "number", "unit": "W",   "device_class": "power",       "min": 0,  "max": 1200},
    "inputLimit":      {"name": "Input Limit",       "type": "number", "unit": "W",   "device_class": "power",       "min": 0,  "max": 1200},
    "inverseMaxPower": {"name": "Inverter Limit",    "type": "number", "unit": "W",   "min": 0,  "max": 2400},
    "remainOutTime":   {"name": "Remain Out Time",   "type": "sensor", "unit": "min", "device_class": "duration"},
    "remainInputTime": {"name": "Remain Input Time", "type": "sensor", "unit": "min", "device_class": "duration"},
    "electricLevel":   {"name": "Electric Level",   "type": "sensor", "unit": "%",   "device_class": "battery"},
    "socSet":          {"name": "Charge Limit",      "type": "number", "unit": "%",   "min": 5,  "max": 100,
                        "value_template": "{{ (value | float * 0.1) | round(0) | int }}",
                        "cmd_template":   '{"properties": {"socSet": {{ (value | float * 10) | int }} }}'},
    "minSoc":          {"name": "Discharge Limit",   "type": "number", "unit": "%",   "min": 5,  "max": 35,
                        "value_template": "{{ (value | float * 0.1) | round(0) | int }}",
                        "cmd_template":   '{"properties": {"minSoc": {{ (value | float * 10) | int }} }}'},
    "solarPower1":     {"name": "Solar Power 1",     "type": "sensor", "unit": "W",   "device_class": "power", "state_class": "measurement", "icon": "mdi:solar-panel"},
    "solarPower2":     {"name": "Solar Power 2",     "type": "sensor", "unit": "W",   "device_class": "power", "state_class": "measurement", "icon": "mdi:solar-panel"},
    "gridInputPower":  {"name": "Grid Input Power",  "type": "sensor", "unit": "W",   "device_class": "power", "state_class": "measurement"},
    "acOutputPower":   {"name": "AC Output Power",   "type": "sensor", "unit": "W",   "device_class": "power", "state_class": "measurement"},
    "hyperTmp":        {"name": "Temperatur",        "type": "sensor", "unit": "°C",  "device_class": "temperature",
                        "value_template": "{{ (value | float / 10 - 273.15) | round(1) }}"},
    "packNum":         {"name": "Pack Num",          "type": "sensor", "icon": "mdi:battery-check-outline"},
    "masterSwitch":    {"name": "Master Switch",     "type": "switch"},
    "buzzerSwitch":    {"name": "Buzzer",            "type": "switch", "icon": "mdi:bullhorn-outline"},
    "wifiState":       {"name": "WiFi",              "type": "binary_sensor", "device_class": "connectivity", "entity_category": "diagnostic"},
    "heatState":       {"name": "Heizung",           "type": "binary_sensor", "icon": "mdi:heating-coil"},
    "acMode":          {"name": "AC Modus",          "type": "select",
                        "options": {"0": "Aus", "1": "AC Laden", "2": "AC Entladen"}},
    "pass":            {"name": "Pass Mode",         "type": "select",
                        "options": {"0": "Automatisch", "1": "Immer aus", "2": "Immer ein"}},
}

BATTERY_FIELDS = {
    "maxTemp":  {"name": "Temperatur",  "type": "sensor", "unit": "°C", "device_class": "temperature",
                 "value_template": "{{ (value | float / 10 - 273.15) | round(1) }}"},
    "totalVol": {"name": "Spannung",    "type": "sensor", "unit": "V",  "device_class": "voltage",
                 "value_template": "{{ (value | float / 100) | round(1) }}"},
    "maxVol":   {"name": "Zelle Max V", "type": "sensor", "unit": "V",  "device_class": "voltage",
                 "value_template": "{{ (value | float / 100) | round(2) }}", "icon": "mdi:alpha-v-circle-outline"},
    "minVol":   {"name": "Zelle Min V", "type": "sensor", "unit": "V",  "device_class": "voltage",
                 "value_template": "{{ (value | float / 100) | round(2) }}", "icon": "mdi:alpha-v-circle-outline"},
    "batcur":   {"name": "Strom",       "type": "sensor", "unit": "A",  "device_class": "current",
                 "value_template": "{{ (value | float / 10) | round(1) }}"},
    "socLevel": {"name": "Ladezustand", "type": "sensor", "unit": "%",  "device_class": "battery"},
}


def build_select_templates(field, options_map):
    """Build value_template and command_template for select entities."""
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
    write_topic = f"iot/{product_id}/{device_id}/properties/write"
    dev_info = {
        "identifiers": [device_id],
        "name": f"SolarFlow Hyper ({device_id})",
        "manufacturer": "Zendure",
        "model": "Hyper 2000",
    }

    for field, cfg in PROPERTY_FIELDS.items():
        unique_id   = f"hyper_{device_id}_{field}"
        state_topic = f"{OUTPUT_PREFIX}/{device_id}/telemetry/{field}"
        etype       = cfg["type"]

        p = {
            "name":        cfg["name"],
            "unique_id":   unique_id,
            "state_topic": state_topic,
            "device":      dev_info,
        }
        for k in ("unit_of_measurement", "device_class", "state_class", "icon", "entity_category"):
            if k == "unit_of_measurement" and "unit" in cfg:
                p[k] = cfg["unit"]
            elif k in cfg:
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
            "name":        cfg["name"],
            "unique_id":   unique_id,
            "state_topic": state_topic,
            "device":      dev_info,
        }
        if "unit" in cfg:
            p["unit_of_measurement"] = cfg["unit"]
        for k in ("device_class", "state_class", "icon"):
            if k in cfg:
                p[k] = cfg[k]
        if "value_template" in cfg:
            p["value_template"] = cfg["value_template"]

        disc = f"{HA_PREFIX}/sensor/{unique_id}/config"
        client.publish(disc, json.dumps(p), retain=True)

    log.info(f"HA discovery published for battery {bat_num} ({sn}) on device {device_id}")


def register_battery(client, device_id, product_id, sn):
    if sn not in discovered_devices[device_id]["batteries"]:
        discovered_devices[device_id]["batteries"].add(sn)
        bat_num = len(discovered_devices[device_id]["batteries"])
        log.info(f"New battery discovered: {sn} (#{bat_num}) on {device_id}")
        if HA_DISCOVERY:
            publish_ha_discovery_battery(client, device_id, sn, bat_num)


def handle_report(client, product_id, device_id, payload):
    if device_id not in discovered_devices:
        discovered_devices[device_id] = {"product_id": product_id, "batteries": set()}
        log.info(f"New device discovered: {device_id} (product: {product_id})")
        if HA_DISCOVERY:
            publish_ha_discovery_device(client, device_id, product_id)

    props = payload.get("properties", {})

    # Publish individual telemetry
    for field in PROPERTY_FIELDS:
        if field in props:
            client.publish(
                f"{OUTPUT_PREFIX}/{device_id}/telemetry/{field}",
                str(props[field]),
                retain=True
            )

    # Handle embedded packData
    for pack in props.get("packData", []):
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


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log.info(f"Connected to MQTT {MQTT_HOST}:{MQTT_PORT}")
        client.subscribe(f"/{PRODUCT_ID}/{DEVICE_ID}/properties/report")
        client.subscribe(f"/{PRODUCT_ID}/{DEVICE_ID}/telemetry/batteries/#")
        log.info(f"Subscribed to: {PRODUCT_ID}/{DEVICE_ID}/properties/report")
        log.info(f"Subscribed to: {PRODUCT_ID}/{DEVICE_ID}/telemetry/batteries/#")
        # Send initial getAll to configured device
        if PRODUCT_ID and DEVICE_ID:
            topic = f"iot/{PRODUCT_ID}/{DEVICE_ID}/properties/read"
            payload = json.dumps({"messageId": next_msg_id(), "deviceId": DEVICE_ID, "properties": ["getAll"]})
            client.publish(topic, payload)
            log.info(f"Initial poll sent to {PRODUCT_ID}/{DEVICE_ID}")
        else:
            log.warning("No PRODUCT_ID/DEVICE_ID configured - waiting for device to report")
        # Re-poll already known devices
        for device_id, info in list(discovered_devices.items()):
            product_id = info["product_id"]
            topic = f"iot/{product_id}/{device_id}/properties/read"
            payload = json.dumps({"messageId": next_msg_id(), "deviceId": device_id, "properties": ["getAll"]})
            client.publish(topic, payload)
    else:
        log.error(f"Connection failed rc={rc}")


def on_message(client, userdata, msg):
    log.info(f"Message received on topic: {topic}")
    topic = msg.topic
    parts = topic.split("/")

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        log.warning(f"JSON parse error on {topic}: {e}")
        return

    # <product>/<device>/properties/report
    if len(parts) == 5 and parts[3] == "report":
        handle_report(client, parts[1], parts[2], payload)

    # <product>/<device>/telemetry/batteries/<sn>/<field>
    elif len(parts) == 6 and parts[2] == "telemetry" and parts[3] == "batteries":
        product_id, device_id, sn, field = parts[0], parts[1], parts[4], parts[5]
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
    log.info(f"  Broker:       {MQTT_HOST}:{MQTT_PORT}")
    log.info(f"  HA Discovery: {HA_DISCOVERY}")
    log.info(f"  Output:       {OUTPUT_PREFIX}/<device_id>/telemetry/")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="solarflow-hyper-transformer")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message

    # Start polling thread
    poll_thread = threading.Thread(target=poll_devices, args=(client,), daemon=True)
    poll_thread.start()
    log.info(f"Polling devices every {POLL_INTERVAL}s")

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as e:
            log.error(f"MQTT error: {e} — retrying in 10s")
            time.sleep(10)


if __name__ == "__main__":
    main()
