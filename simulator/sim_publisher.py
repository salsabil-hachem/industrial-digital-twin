"""
sim_publisher.py - The "machine" (edge device). Runs the physics plant in real time
and publishes its sensor data over MQTT, like a real IIoT gateway.

Publishes : factory/line1/motor1/telemetry   (JSON, 20 Hz)
Listens   : factory/line1/motor1/cmd         {"fault": "overload", "active": true} | {"reset": true}
"""
import json
import os
import time

import paho.mqtt.client as mqtt

from plant import Plant

HOST = os.getenv("MQTT_HOST", "localhost")
SPEEDUP = float(os.getenv("SIM_SPEEDUP", "1"))
BASE = "factory/line1/motor1"

plant = Plant()


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[sim] connected to {HOST} ({reason_code})")
    client.subscribe(f"{BASE}/cmd")


def on_message(client, userdata, msg):
    global plant
    try:
        cmd = json.loads(msg.payload)
    except json.JSONDecodeError:
        return
    if cmd.get("reset"):
        plant = Plant()
        print("[sim] machine reset")
    elif cmd.get("fault") in plant.faults:
        plant.set_fault(cmd["fault"], bool(cmd.get("active", True)))
        print(f"[sim] fault {cmd['fault']} -> {cmd.get('active', True)}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="motor1-sim")
client.on_connect = on_connect
client.on_message = on_message
while True:
    try:
        client.connect(HOST, 1883)
        break
    except OSError:
        print(f"[sim] waiting for broker {HOST}...")
        time.sleep(2)
client.loop_start()

next_t = time.time()
while True:
    m = plant.step()
    m["ts"] = int(time.time() * 1000)  # wall-clock timestamp (ms)
    m["tripped"] = int(m["tripped"])
    m = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}
    client.publish(f"{BASE}/telemetry", json.dumps(m))
    next_t += plant.dt / SPEEDUP
    time.sleep(max(0.0, next_t - time.time()))
