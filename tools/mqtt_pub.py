import socket
import struct
import sys


HOST = "127.0.0.1"
PORT = 13688
CLIENT_ID = "PluginClient_18"
USERNAME = "PluginClient_User_18"
PASSWORD = "PluginClient_Pwd888881772688_18"


def enc_str(value):
    data = value.encode("utf-8")
    return struct.pack("!H", len(data)) + data


def enc_len(length):
    out = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length:
            digit |= 0x80
        out.append(digit)
        if not length:
            return bytes(out)


def read_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError("socket closed")
        data.extend(chunk)
    return bytes(data)


def read_packet(sock):
    fixed = read_exact(sock, 1)[0]
    multiplier = 1
    remaining = 0
    while True:
        digit = read_exact(sock, 1)[0]
        remaining += (digit & 127) * multiplier
        if digit & 128 == 0:
            break
        multiplier *= 128
    return fixed, read_exact(sock, remaining)


def send_packet(sock, packet_type, payload):
    sock.sendall(bytes([packet_type]) + enc_len(len(payload)) + payload)


def connect(sock):
    variable = enc_str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 30)
    payload = enc_str(CLIENT_ID) + enc_str(USERNAME) + enc_str(PASSWORD)
    send_packet(sock, 0x10, variable + payload)
    fixed, body = read_packet(sock)
    if fixed != 0x20 or len(body) < 2 or body[1] != 0:
        raise RuntimeError(f"CONNECT failed: fixed=0x{fixed:02x} body={body!r}")


def publish(sock, topic, payload):
    body = enc_str(topic) + payload.encode("utf-8")
    send_packet(sock, 0x30, body)


def main():
    if len(sys.argv) != 3:
        print("usage: mqtt_pub.py <topic> <payload>", file=sys.stderr)
        raise SystemExit(2)
    with socket.create_connection((HOST, PORT), timeout=5) as sock:
        connect(sock)
        publish(sock, sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
