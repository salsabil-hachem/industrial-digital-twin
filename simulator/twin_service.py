"""
twin_service.py - Digital twin microservice.
Subscribes to the machine telemetry, runs the nominal model in parallel,
publishes predictions, residuals, health index and diagnosis.

Listens   : factory/line1/motor1/telemetry
Publishes : factory/line1/motor1/twin
"""
import json
import os
import time

import paho.mqtt.client as mqtt

from twin import DigitalTwin

HOST = os.getenv("MQTT_HOST", "localhost")
BASE = "factory/line1/motor1"
twin = DigitalTwin()
last_t = None


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[twin] connected to {HOST} ({reason_code})")
    client.subscribe(f"{BASE}/telemetry")


def on_message(client, userdata, msg):
    global twin, last_t
    m = json.loads(msg.payload)
    if last_t is not None and m["t"] < last_t:  # machine was reset -> reset the twin too
        twin = DigitalTwin()
    last_t = m["t"]
    out = twin.update(m)
    out = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}
    out["ts"] = m["ts"]
    client.publish(f"{BASE}/twin", json.dumps(out))


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="motor1-twin")
client.on_connect = on_connect
client.on_message = on_message
while True:
    try:
        client.connect(HOST, 1883)
        break
    except OSError:
        print(f"[twin] waiting for broker {HOST}...")
        time.sleep(2)
client.loop_forever()
