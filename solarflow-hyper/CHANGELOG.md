# Changelog

## 2.2.0
- Entitäten werden erst angelegt, wenn das Gerät das Feld meldet. Bei bestehenden Installationen bleiben alte, nie gemeldete Entitäten (retained Discovery) bestehen; bei Bedarf in HA am Gerät löschen.
- Batterien heißen nach Seriennummer („Batterie 3A1B2C“) statt nach Erkennungsreihenfolge; Namen bleiben nach Neustart stabil.
- Neue Felder: `passMode`, `autoRecover`, `acSwitch`, `dcSwitch`, `dcOutputPower`, `batteryElectric`, `smartMode`, `connectedWithAce`.
- paho-mqtt auf 2.1.0 festgelegt.
- `build.yaml` mit Basis-Image je Architektur.
