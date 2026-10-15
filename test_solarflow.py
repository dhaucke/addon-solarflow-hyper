#!/usr/bin/env python3
"""Self-check without broker: python3 test_solarflow.py"""
import importlib.util
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).parent
HYPER = ROOT / "solarflow-hyper/rootfs/usr/bin/solarflow-hyper.py"
HUB = ROOT / "solarflow-hub/rootfs/usr/bin/solarflow-hub.py"

if "paho" not in sys.modules:  # stub so the test runs without paho-mqtt installed
    client_mod = types.ModuleType("paho.mqtt.client")
    sys.modules.update({"paho": types.ModuleType("paho"), "paho.mqtt": types.ModuleType("paho.mqtt"),
                        "paho.mqtt.client": client_mod})

spec = importlib.util.spec_from_file_location("sf", HYPER)
sf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sf)


class FakeClient:
    def __init__(self):
        self.pub = {}

    def publish(self, topic, payload, retain=False):
        self.pub[topic] = payload


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, json.dumps(payload).encode()


assert HYPER.read_bytes() == HUB.read_bytes(), "solarflow-hub.py differs from solarflow-hyper.py"

c = FakeClient()
sf.on_message(c, None, Msg("gDa3tb/HYP0/properties/report", {
    "packData": [{"sn": "CO4FAAAA123456", "socLevel": 80}, {"sn": "CO4FBBBB654321", "socLevel": 70}],
}))
sf.on_message(c, None, Msg("A8yh63/HUB1/properties/report", {
    "properties": {"outputLimit": 300, "passMode": 1, "remainOutTime": 59999, "connectedWithAce": 1},
    "packData": [{"sn": "CO4FCCCC111111", "socLevel": 80}],
}))
# hub only mirrors the packs on the ACE: old entities removed, no telemetry
assert c.pub["homeassistant/sensor/hyper_HUB1_bat_CO4FCCCC111111_socLevel/config"] == ""
assert "solarflow-hyper/HUB1/telemetry/batteries/CO4FCCCC111111/socLevel" not in c.pub
sf.on_message(c, None, Msg("/8bM93H/ACE1/properties/report", {"properties": {"inputLimit": 400, "dcSwitch": 1}}))

# only reported fields get discovered, filtered value neither
assert "homeassistant/number/hyper_HUB1_outputLimit/config" in c.pub
assert "homeassistant/sensor/hyper_HUB1_remainOutTime/config" not in c.pub
assert "solarflow-hyper/HUB1/telemetry/remainOutTime" not in c.pub
assert "homeassistant/sensor/hyper_HUB1_electricLevel/config" not in c.pub
assert c.pub["solarflow-hyper/HUB1/telemetry/outputLimit"] == "300"

hub_dev = json.loads(c.pub["homeassistant/number/hyper_HUB1_outputLimit/config"])["device"]
assert hub_dev["model"] == "Hub 2000" and hub_dev["name"] == "SolarFlow Hub 2000 (HUB1)"

sel = json.loads(c.pub["homeassistant/select/hyper_HUB1_passMode/config"])
assert sel["options"] == ["Automatisch", "Immer aus", "Immer ein"]

# ACE override: inputLimit 0-900 in 100 W steps; leading slash topic works
ace = json.loads(c.pub["homeassistant/number/hyper_ACE1_inputLimit/config"])
assert (ace["max"], ace["step"]) == (900, 100) and ace["device"]["model"] == "ACE 1500"
assert ace["command_topic"] == "iot/8bM93H/ACE1/properties/write"
assert "homeassistant/switch/hyper_ACE1_dcSwitch/config" in c.pub

# mirrored fields only on their owner; old entities get removed via empty config
sf.on_message(c, None, Msg("8bM93H/ACE1/properties/report", {"properties": {"electricLevel": 99, "gridInputPower": 5, "solarPower1": 7}}))
assert json.loads(c.pub["homeassistant/sensor/hyper_ACE1_solarPower1/config"])["name"] == "ACE Solar Power 1"
assert c.pub["homeassistant/sensor/hyper_ACE1_electricLevel/config"] == ""
assert "solarflow-hyper/ACE1/telemetry/electricLevel" not in c.pub
assert "homeassistant/sensor/hyper_ACE1_gridInputPower/config" in c.pub
sf.on_message(c, None, Msg("8bM93H/ACE1/properties/report", {"packData": [{"sn": "CO4FBBBB654321", "socLevel": 70}]}))
assert json.loads(c.pub["homeassistant/sensor/hyper_ACE1_bat_CO4FBBBB654321_socLevel/config"])["device"]["via_device"] == "ACE1"
assert c.pub["solarflow-hyper/ACE1/telemetry/batteries/CO4FBBBB654321/socLevel"] == "70"
sf.on_message(c, None, Msg("A8yh63/HUB1/properties/report", {"properties": {"acMode": 1}}))
assert "solarflow-hyper/HUB1/telemetry/acMode" not in c.pub

# battery name from serial, independent of order
bat = json.loads(c.pub["homeassistant/sensor/hyper_HYP0_bat_CO4FBBBB654321_socLevel/config"])
assert bat["device"]["name"] == "Batterie 654321"

# discovery published once per field, not on every report
c.pub.clear()
sf.on_message(c, None, Msg("A8yh63/HUB1/properties/report", {"properties": {"outputLimit": 250}}))
assert list(c.pub) == ["solarflow-hyper/HUB1/status", "solarflow-hyper/HUB1/telemetry/outputLimit"]

# hyper keeps its device name
sf.on_message(c, None, Msg("gDa3tb/HYP1/properties/report", {"properties": {"outputLimit": 1}}))
assert json.loads(c.pub["homeassistant/number/hyper_HYP1_outputLimit/config"])["device"]["name"] == "SolarFlow Hyper (HYP1)"

print("ok")
