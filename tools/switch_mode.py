#!/usr/bin/env python3
import json
import socket
import sys
import threading
import time

import mqtt_pub as pub
import mqtt_sniff as sniff


ACTIONS = {
    "gaming": "OPERATING_GAMING_MODE",
    "balance": "OPERATING_GAMING_MODE",
    "balanced": "OPERATING_GAMING_MODE",
    "game": "OPERATING_GAMING_MODE",
    "office": "OPERATING_OFFICE_MODE",
    "silent": "OPERATING_OFFICE_MODE",
    "quiet": "OPERATING_OFFICE_MODE",
    "turbo": "OPERATING_TURBO_MODE",
    "performance": "OPERATING_TURBO_MODE",
    "perf": "OPERATING_TURBO_MODE",
    "custom": "OPERATING_CUSTOM_MODE",
}

EXPECTED_MODE = {
    "OPERATING_OFFICE_MODE": "0",
    "OPERATING_GAMING_MODE": "1",
    "OPERATING_TURBO_MODE": "2",
}


def build_payload(action):
    return json.dumps({"Action": action}, separators=(",", ":"))


def publish_mode(action):
    payload = json.dumps({"Action": action}, separators=(",", ":"))
    with socket.create_connection((pub.HOST, pub.PORT), timeout=5) as sock:
        pub.connect(sock)
        pub.publish(sock, "Fan/Control", payload)
    return payload


def wait_status(action, timeout=8):
    expected = EXPECTED_MODE.get(action)
    deadline = time.time() + timeout
    payload = build_payload(action)
    with socket.create_connection((sniff.HOST, sniff.PORT), timeout=5) as sock:
        sock.settimeout(1)
        sniff.connect(sock)
        sniff.subscribe(sock)
        threading.Timer(0.5, publish_mode, args=(action,)).start()
        print(f"published Fan/Control {payload}", flush=True)
        saw_expected = False
        while time.time() < deadline:
            try:
                fixed, body = sniff.read_packet(sock)
            except socket.timeout:
                continue
            if fixed >> 4 != 3:
                continue
            topic, payload = sniff.parse_publish(fixed, body)
            if topic not in ("Tray/Status", "Fan/Status"):
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            mode = data.get("OperatingMode")
            if mode is None:
                continue
            print(f"{topic}: OperatingMode={mode}", flush=True)
            if expected is None or str(mode) == expected:
                saw_expected = True
                if topic == "Fan/Status":
                    print(
                        "Profile={profile} Table={table} AMD_SPL/SPPT/FPPT={spl}/{sppt}/{fppt} Tcc={tcc}".format(
                            profile=data.get("ProfileName"),
                            table=data.get("FAN_TableName"),
                            spl=data.get("CPU_AmdSPL"),
                            sppt=data.get("CPU_AmdSPPT"),
                            fppt=data.get("CPU_AmdFPPT"),
                            tcc=data.get("CPU_AmdTccTarget") or data.get("CPU_TccOffset"),
                        ),
                        flush=True,
                    )
                    return True
        return saw_expected


def main():
    if len(sys.argv) != 2 or sys.argv[1].lower() not in ACTIONS:
        names = "office | gaming | turbo | custom"
        print(f"usage: switch_mode.py {names}", file=sys.stderr)
        raise SystemExit(2)

    mode = sys.argv[1].lower()
    action = ACTIONS[mode]
    if not wait_status(action):
        print("No matching status update observed before timeout.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
