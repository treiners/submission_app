# MQTT Lifesign for Windows 10

This project publishes a lifesign (`1`/`0`) plus CPU/RAM usage from a Windows PC to MQTT for Home Assistant.

## Files
- `mqtt_lifesign.py`: Main script.
- `.env.example`: Environment configuration template.
- `requirements.txt`: Python dependencies.
- `home_assistant_mqtt.yaml`: Example Home Assistant MQTT entities.

## 1) Install dependencies
In PowerShell, inside this folder:

```powershell
pip install -r requirements.txt
```

## 2) Configure
Copy `.env.example` to `.env` and edit values:

- `MQTT_BROKER`: IP/hostname of your MQTT broker.
- `MQTT_PORT`: Usually `1883`.
- `MQTT_USERNAME` / `MQTT_PASSWORD`: If broker auth is enabled.
- `MQTT_BASE_TOPIC`: Topic prefix. Default is `home/windows10_pc`.
- `INTERVAL_SECONDS`: Publish frequency in seconds.

## 3) Run

```powershell
python mqtt_lifesign.py
```

## 4) Home Assistant setup
Merge the content of `home_assistant_mqtt.yaml` into your Home Assistant `configuration.yaml`
or create equivalent entities via UI.

Topics used by this script:
- `home/windows10_pc/lifesign/state` (`1` = alive, `0` = offline)
- `home/windows10_pc/metrics` (JSON with `cpu_percent`, `memory_percent`)

## Notes
- The script publishes retained online/offline state.
- If the PC/script dies unexpectedly, MQTT Last Will publishes `0` (offline).
