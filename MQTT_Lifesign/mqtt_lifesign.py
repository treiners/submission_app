import json
import os
import signal
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import psutil
from dotenv import load_dotenv

load_dotenv()


# MQTT connection settings
MQTT_BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "windows10-lifesign")

# Topic settings
MQTT_BASE_TOPIC = os.getenv("MQTT_BASE_TOPIC", "home/windows10_pc")
STATE_TOPIC = f"{MQTT_BASE_TOPIC}/lifesign/state"
METRICS_TOPIC = f"{MQTT_BASE_TOPIC}/metrics"

# Publish interval
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "60"))

running = True


def on_stop(signum, frame):
    del signum, frame
    global running
    running = False


def build_metrics_payload() -> str:
    # interval=None gives immediate CPU percentage since previous call.
    cpu_percent = psutil.cpu_percent(interval=None)
    memory_percent = psutil.virtual_memory().percent
    now = datetime.now(timezone.utc).isoformat()

    payload = {
        "cpu_percent": round(cpu_percent, 1),
        "memory_percent": round(memory_percent, 1),
        "timestamp_utc": now,
    }
    return json.dumps(payload)


def publish_online(client: mqtt.Client) -> None:
    client.publish(STATE_TOPIC, payload="1", qos=1, retain=True)


def publish_offline(client: mqtt.Client) -> None:
    client.publish(STATE_TOPIC, payload="0", qos=1, retain=True)


def publish_metrics(client: mqtt.Client) -> None:
    client.publish(METRICS_TOPIC, payload=build_metrics_payload(), qos=0, retain=False)


def main() -> None:
    signal.signal(signal.SIGINT, on_stop)
    signal.signal(signal.SIGTERM, on_stop)

    client = mqtt.Client(client_id=MQTT_CLIENT_ID, protocol=mqtt.MQTTv311)

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    # Last Will marks the PC offline if script or machine dies unexpectedly.
    client.will_set(STATE_TOPIC, payload="0", qos=1, retain=True)

    print(f"Connecting to MQTT broker {MQTT_BROKER}:{MQTT_PORT} ...")
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    print("Connected. Publishing lifesign and metrics...")
    publish_online(client)
    publish_metrics(client)

    try:
        while running:
            publish_online(client)
            publish_metrics(client)
            time.sleep(INTERVAL_SECONDS)
    finally:
        print("Stopping. Publishing offline state...")
        publish_offline(client)
        client.loop_stop()
        client.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
