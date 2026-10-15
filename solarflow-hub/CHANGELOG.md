# Changelog

## 1.1.0
- Keine doppelten Entitäten mehr: Werte, die der ACE vom Hub spiegelt (Akku, SOC-Grenzen, Restzeiten), erscheinen nur noch beim Hub; AC-Modus und Input Limit nur noch beim ACE. Solar-Eingang des ACE heißt jetzt „ACE Solar …“. Batterien nur noch beim ACE (vorher doppelt mit `_2`). Bereits angelegte Duplikate werden beim Start entfernt.

## 1.0.0
- Erste Version: Hub 2000 und ACE 1500 als zwei Geräte über lokales MQTT, gleiches Skript wie das Hyper-Add-on.
