#!/usr/bin/env python3
"""
SolarFlow - Auto-Discovery MQTT Topic Transformer
Shared by the add-ons solarflow-hyper (Hyper 2000) and solarflow-hub (Hub 2000 + ACE 1500);
both ship an identical copy of this file (checked by test_solarflow.py).

Reads:  <product_id>/<device_id>/properties/report
        <product_id>/<device_id>/properties/energy
Writes: <OUTPUT_PREFIX>/<device_id>/telemetry/<key>
        <OUTPUT_PREFIX>/<device_id>/telemetry/batteries/<sn>/<key>
        <OUTPUT_PREFIX>/<device_id>/status

With HA_DISCOVERY=true, every field gets an MQTT discovery message the first time
the device reports it, so each device only shows the entities it actually has.
"""

import json
import logging
import os
import time
import threading
import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s: %(message)s")
log = logging.getLogger("solarflow")

MQTT_HOST     = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT     = int(os.environ.get("MQTT_PORT", 1883))
MQTT_USER     = os.environ.get("MQTT_USER", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
HA_DISCOVERY  = os.environ.get("HA_DISCOVERY", "true").lower() == "true"
HA_PREFIX     = os.environ.get("HA_PREFIX", "homeassistant")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 30))
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "solarflow-hyper")
UID_PREFIX    = os.environ.get("UID_PREFIX", "hyper")
# "product_id/device_id" pairs, comma separated; empty = listen to everything
DEVICES = [tuple(d.strip().split("/", 1)) for d in os.environ.get("DEVICES", "").split(",") if "/" in d]

# product_id -> (device name prefix, model)
PRODUCTS = {
    "gDa3tb": ("SolarFlow Hyper",    "Hyper 2000"),
    "A8yh63": ("SolarFlow Hub 2000", "Hub 2000"),
    "73bkTV": ("SolarFlow Hub 1200", "Hub 1200"),
    "8bM93H": ("ACE 1500",           "ACE 1500"),
}

discovered_devices = {}
_msg_id = 0


def next_msg_id():
    global _msg_id
    _msg_id += 1
    return _msg_id


def send_poll(client, product_id, device_id):
    client.publish(
        f"iot/{product_id}/{device_id}/properties/read",
        json.dumps({"messageId": next_msg_id(), "deviceId": device_id, "properties": ["getAll"]})
    )


def poll_devices(client):
    while True:
        time.sleep(POLL_INTERVAL)
        for device_id, info in list(discovered_devices.items()):
            send_poll(client, info["product_id"], device_id)
            log.debug(f"Polled {device_id}")


_STATE_TEMPLATE = "{{ 'Standby' if value=='0' else ('Laden' if value=='1' else ('Entladen' if value=='2' else 'Unknown')) }}"
_KELVIN_TEMPLATE = "{{ (value | float / 10 - 273.15) | round(1) }}"

PROPERTY_FIELDS = {
    "hubState":        {"name": "Hub State",            "type": "sensor"},
    "solarInputPower": {"name": "Solar Input Power",    "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "packInputPower":  {"name": "Pack Input Power",     "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "outputPackPower": {"name": "Output Pack Power",    "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "outputHomePower": {"name": "Output Home Power",    "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "acOutputPower":   {"name": "AC Output Power",      "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "dcOutputPower":   {"name": "DC Output Power",      "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "gridInputPower":  {"name": "Grid Input Power",     "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
    "batteryElectric": {"name": "Battery Power",        "type": "sensor", "unit": "W",   "device_class": "power",            "state_class": "measurement"},
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
    "packState":       {"name": "Pack State",            "type": "sensor", "value_template": _STATE_TEMPLATE, "icon": "mdi:battery-sync-outline"},
    "hyperTmp":        {"name": "Temperatur",            "type": "sensor", "unit": "°C",  "device_class": "temperature", "value_template": _KELVIN_TEMPLATE},
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
    "acSwitch":        {"name": "AC Switch",              "type": "switch", "icon": "mdi:power-socket-de"},
    "dcSwitch":        {"name": "DC Switch",              "type": "switch", "icon": "mdi:current-dc"},
    "autoRecover":     {"name": "Bypass Auto Recover",    "type": "switch", "icon": "mdi:restore"},
    "smartMode":       {"name": "Smart Mode",             "type": "switch", "icon": "mdi:memory"},
    "wifiState":       {"name": "WiFi",                   "type": "binary_sensor", "device_class": "connectivity", "entity_category": "diagnostic"},
    "heatState":       {"name": "Heizung",                "type": "binary_sensor", "icon": "mdi:heating-coil"},
    "ctOff":           {"name": "CT Off",                 "type": "binary_sensor", "icon": "mdi:current-ac"},
    "gridReverse":     {"name": "Grid Reverse",           "type": "binary_sensor", "icon": "mdi:transmission-tower"},
    "connectedWithAce": {"name": "ACE verbunden",         "type": "binary_sensor", "device_class": "connectivity", "icon": "mdi:link-variant"},
    "acMode":          {"name": "AC Modus",               "type": "select",
                        "options": {"0": "Aus", "1": "AC Laden", "2": "AC Entladen"}},
    "pass":            {"name": "Pass Mode",              "type": "select",
                        "options": {"0": "Automatisch", "1": "Immer aus", "2": "Immer ein"}},
    "passMode":        {"name": "Bypass Modus",           "type": "select",
                        "options": {"0": "Automatisch", "1": "Immer aus", "2": "Immer ein"}},
}

# Per-product deviations from PROPERTY_FIELDS
PRODUCT_OVERRIDES = {
    "8bM93H": {"inputLimit":      {"max": 900, "step": 100},
               # ACE has its own solar input, named apart from the hub's
               "solarInputPower": {"name": "ACE Solar Input Power"},
               "solarPower1":     {"name": "ACE Solar Power 1"},
               "solarPower2":     {"name": "ACE Solar Power 2"}},
    "A8yh63": {"inputLimit": {"max": 900, "step": 100}},
}

# Fields a product mirrors from its partner (Hub 2000 <-> ACE 1500); shown only on the owner
PRODUCT_HIDDEN = {
    "8bM93H": {"socSet", "minSoc", "autoModel", "electricLevel", "outputPackPower", "packInputPower",
               "packNum", "packState", "remainOutTime", "remainInputTime"},
    # ACE is the AC charger and the packs sit on it, so these belong to it
    "A8yh63": {"acMode", "inputLimit", "packData"},
}

BATTERY_FIELDS = {
    "maxTemp":     {"name": "Temperatur",  "type": "sensor", "unit": "°C", "device_class": "temperature", "value_template": _KELVIN_TEMPLATE},
    "totalVol":    {"name": "Spannung",    "type": "sensor", "unit": "V",  "device_class": "voltage",
                    "value_template": "{{ (value | float / 100) | round(1) }}"},
    "maxVol":      {"name": "Zelle Max V", "type": "sensor", "unit": "V",  "device_class": "voltage",
                    "value_template": "{{ (value | float / 100) | round(2) }}", "icon": "mdi:alpha-v-circle-outline"},
    "minVol":      {"name": "Zelle Min V", "type": "sensor", "unit": "V",  "device_class": "voltage",
                    "value_template": "{{ (value | float / 100) | round(2) }}", "icon": "mdi:alpha-v-circle-outline"},
    "batcur":      {"name": "Strom",       "type": "sensor", "unit": "A",  "device_class": "current",
                    "value_template": "{{ (value | float / 10) | round(1) }}"},
    "socLevel":    {"name": "Ladezustand", "type": "sensor", "unit": "%",  "device_class": "battery"},
    "state":       {"name": "Status",      "type": "sensor", "value_template": _STATE_TEMPLATE, "icon": "mdi:battery-sync-outline"},
    "power":       {"name": "Leistung",    "type": "sensor", "unit": "W",  "device_class": "power", "state_class": "measurement"},
    "softVersion": {"name": "Firmware",    "type": "sensor", "icon": "mdi:chip", "entity_category": "diagnostic"},
}

FILTER_FIELDS = {
    "remainOutTime":   59900,
    "remainInputTime": 59900,
}


def field_cfg(product_id, field):
    return {**PROPERTY_FIELDS[field], **PRODUCT_OVERRIDES.get(product_id, {}).get(field, {})}


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


def device_info(device_id, product_id):
    name, model = PRODUCTS.get(product_id, ("Zendure", f"Unbekannt ({product_id})"))
    return {
        "identifiers": [device_id],
        "name": f"{name} ({device_id})",
        "manufacturer": "Zendure",
        "model": model,
    }


def base_payload(cfg, unique_id, state_topic, dev_info, status_topic):
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
    for k in ("device_class", "state_class", "icon", "entity_category", "value_template"):
        if k in cfg:
            p[k] = cfg[k]
    return p


def publish_ha_discovery_status(client, device_id, product_id):
    client.publish(f"{HA_PREFIX}/binary_sensor/{UID_PREFIX}_{device_id}_status/config", json.dumps({
        "name": "Status",
        "unique_id": f"{UID_PREFIX}_{device_id}_status",
        "state_topic": f"{OUTPUT_PREFIX}/{device_id}/status",
        "device": device_info(device_id, product_id),
        "icon": "mdi:power",
        "payload_on": "online",
        "payload_off": "offline",
        "device_class": "connectivity",
        "entity_category": "diagnostic",
    }), retain=True)


def publish_ha_discovery_field(client, device_id, product_id, field):
    cfg          = field_cfg(product_id, field)
    write_topic  = f"iot/{product_id}/{device_id}/properties/write"
    unique_id    = f"{UID_PREFIX}_{device_id}_{field}"
    etype        = cfg["type"]
    p = base_payload(cfg, unique_id, f"{OUTPUT_PREFIX}/{device_id}/telemetry/{field}",
                     device_info(device_id, product_id), f"{OUTPUT_PREFIX}/{device_id}/status")

    if etype == "number":
        p.update({
            "command_topic":    write_topic,
            "min":              cfg.get("min", 0),
            "max":              cfg.get("max", 1200),
            "step":             cfg.get("step", 1),
            "mode":             "box",
            "command_template": cfg.get("cmd_template", f'{{"properties": {{"{field}": {{{{ value | int }}}} }}}}'),
        })
    elif etype == "switch":
        p.update({
            "command_topic": write_topic,
            "payload_on":    json.dumps({"properties": {field: 1}}),
            "payload_off":   json.dumps({"properties": {field: 0}}),
            "state_on":      1,
            "state_off":     0,
        })
    elif etype == "binary_sensor":
        p.update({"payload_on": "1", "payload_off": "0"})
    elif etype == "select":
        vt, ct = build_select_templates(field, cfg["options"])
        p.update({
            "options":          list(cfg["options"].values()),
            "command_topic":    write_topic,
            "value_template":   vt,
            "command_template": ct,
        })

    client.publish(f"{HA_PREFIX}/{etype}/{unique_id}/config", json.dumps(p), retain=True)


def publish_ha_discovery_battery(client, device_id, sn):
    dev_info = {
        "identifiers": [sn],
        # Named by serial, not by discovery order, so names survive restarts
        "name": f"Batterie {sn[-6:]}",
        "manufacturer": "Zendure",
        "via_device": device_id,
    }
    for field, cfg in BATTERY_FIELDS.items():
        unique_id = f"{UID_PREFIX}_{device_id}_bat_{sn}_{field}"
        p = base_payload(cfg, unique_id, f"{OUTPUT_PREFIX}/{device_id}/telemetry/batteries/{sn}/{field}",
                         dev_info, f"{OUTPUT_PREFIX}/{device_id}/status")
        client.publish(f"{HA_PREFIX}/sensor/{unique_id}/config", json.dumps(p), retain=True)
    log.info(f"HA discovery published for battery {sn}")


def register_device(client, device_id, product_id):
    if device_id not in discovered_devices:
        discovered_devices[device_id] = {"product_id": product_id, "batteries": set(), "fields": set()}
        log.info(f"New device: {device_id} (product: {product_id})")
        if HA_DISCOVERY:
            publish_ha_discovery_status(client, device_id, product_id)
            # Empty retained config removes entities that earlier versions created
            for field in PRODUCT_HIDDEN.get(product_id, set()) & PROPERTY_FIELDS.keys():
                client.publish(f"{HA_PREFIX}/{PROPERTY_FIELDS[field]['type']}/{UID_PREFIX}_{device_id}_{field}/config",
                               "", retain=True)


def publish_field(client, device_id, field, value):
    dev = discovered_devices[device_id]
    if HA_DISCOVERY and field not in dev["fields"]:
        publish_ha_discovery_field(client, device_id, dev["product_id"], field)
    dev["fields"].add(field)
    client.publish(f"{OUTPUT_PREFIX}/{device_id}/telemetry/{field}", str(value), retain=True)


def register_battery(client, device_id, sn):
    """Returns False if this device only mirrors the battery (its partner owns it)."""
    dev = discovered_devices[device_id]
    owner = "packData" not in PRODUCT_HIDDEN.get(dev["product_id"], ())
    if sn not in dev["batteries"]:
        dev["batteries"].add(sn)
        log.info(f"New battery: {sn} on {device_id}" + ("" if owner else " (mirrored, ignored)"))
        if HA_DISCOVERY and owner:
            publish_ha_discovery_battery(client, device_id, sn)
        elif HA_DISCOVERY:
            # Remove the duplicate entities earlier versions created for the mirror
            for field in BATTERY_FIELDS:
                client.publish(f"{HA_PREFIX}/sensor/{UID_PREFIX}_{device_id}_bat_{sn}_{field}/config", "", retain=True)
    return owner


def handle_report(client, product_id, device_id, payload):
    register_device(client, device_id, product_id)
    client.publish(f"{OUTPUT_PREFIX}/{device_id}/status", "online", retain=True)

    props = payload.get("properties", {})
    hidden = PRODUCT_HIDDEN.get(product_id, set())
    for field in PROPERTY_FIELDS:
        if field in props and field not in hidden:
            value = props[field]
            if field in FILTER_FIELDS and value >= FILTER_FIELDS[field]:
                continue
            publish_field(client, device_id, field, value)

    for pack in payload.get("packData", []):
        sn = pack.get("sn")
        if not sn:
            continue
        if not register_battery(client, device_id, sn):
            continue
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
    hidden = PRODUCT_HIDDEN.get(product_id, set())
    for field in ["outputPower", "chargePower", "mode"]:
        if field in props and field not in hidden:
            publish_field(client, device_id, field, props[field])


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log.info(f"Connected to MQTT {MQTT_HOST}:{MQTT_PORT}")

        if DEVICES:
            for product_id, device_id in DEVICES:
                # Subscribe with and without leading slash
                for prefix in [product_id, f"/{product_id}"]:
                    client.subscribe(f"{prefix}/{device_id}/properties/report")
                    client.subscribe(f"{prefix}/{device_id}/properties/energy")
                    client.subscribe(f"{prefix}/{device_id}/telemetry/batteries/#")
                log.info(f"Subscribed to: {product_id}/{device_id}")
                send_poll(client, product_id, device_id)
                client.publish(f"{OUTPUT_PREFIX}/{device_id}/status", "online", retain=True)
        else:
            client.subscribe("+/+/properties/report")
            client.subscribe("+/+/properties/energy")
            client.subscribe("+/+/telemetry/batteries/#")
            log.warning("No devices configured - subscribing to all topics")

        # Re-poll known devices
        for device_id, info in list(discovered_devices.items()):
            send_poll(client, info["product_id"], device_id)
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
        register_device(client, device_id, product_id)
        if not register_battery(client, device_id, sn):
            return
        client.publish(
            f"{OUTPUT_PREFIX}/{device_id}/telemetry/batteries/{sn}/{field}",
            msg.payload.decode("utf-8"),
            retain=True
        )


def main():
    log.info("SolarFlow MQTT Transformer starting...")
    log.info(f"  Broker:        {MQTT_HOST}:{MQTT_PORT}")
    log.info(f"  Devices:       {', '.join('/'.join(d) for d in DEVICES) or 'auto'}")
    log.info(f"  HA Discovery:  {HA_DISCOVERY}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{OUTPUT_PREFIX}-transformer")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    # ponytail: MQTT allows only one last will, so it covers the first configured device only
    if DEVICES:
        client.will_set(f"{OUTPUT_PREFIX}/{DEVICES[0][1]}/status", "offline", retain=True)

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
