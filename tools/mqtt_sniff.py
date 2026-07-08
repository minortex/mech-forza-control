import socket
import struct
import time


HOST = "127.0.0.1"
PORT = 13688
CLIENT_ID = "PluginClient_19"
USERNAME = "PluginClient_User_19"
PASSWORD = "PluginClient_Pwd888881772688_19"


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
    variable = enc_str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
    payload = enc_str(CLIENT_ID) + enc_str(USERNAME) + enc_str(PASSWORD)
    send_packet(sock, 0x10, variable + payload)
    fixed, body = read_packet(sock)
    if fixed != 0x20 or len(body) < 2 or body[1] != 0:
        raise RuntimeError(f"CONNECT failed: fixed=0x{fixed:02x} body={body!r}")


def subscribe(sock):
    payload = struct.pack("!H", 1) + enc_str("#") + bytes([0])
    send_packet(sock, 0x82, payload)
    fixed, body = read_packet(sock)
    if fixed != 0x90:
        raise RuntimeError(f"SUBSCRIBE failed: fixed=0x{fixed:02x} body={body!r}")


def parse_publish(fixed, body):
    qos = (fixed >> 1) & 0x03
    pos = 0
    topic_len = struct.unpack("!H", body[pos : pos + 2])[0]
    pos += 2
    topic = body[pos : pos + topic_len].decode("utf-8", errors="replace")
    pos += topic_len
    if qos:
        pos += 2
    payload = body[pos:].decode("utf-8", errors="replace")
    return topic, payload


def main():
    deadline = time.time() + 120
    next_ping = time.time() + 30
    with socket.create_connection((HOST, PORT), timeout=5) as sock:
        sock.settimeout(1)
        connect(sock)
        subscribe(sock)
        print("connected; listening for 120s. Switch mode in Control Center now.", flush=True)
        while time.time() < deadline:
            if time.time() >= next_ping:
                send_packet(sock, 0xC0, b"")
                next_ping = time.time() + 30
            try:
                fixed, body = read_packet(sock)
            except socket.timeout:
                continue
            if fixed == 0xD0:
                continue
            if fixed >> 4 == 3:
                topic, payload = parse_publish(fixed, body)
                print(f"{time.strftime('%H:%M:%S')} TOPIC={topic} PAYLOAD={payload}", flush=True)


if __name__ == "__main__":
    main()
