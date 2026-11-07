"""Print this laptop's LAN IPv4 address (put it in SC_MQTT_HOST on Laptop 2).

Uses the UDP-connect trick: no packet is sent; the OS just picks the interface it would use.
"""
import socket


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # TEST-NET address, never routed
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


if __name__ == "__main__":
    ip = lan_ip()
    print(f"Laptop 1 LAN IP: {ip}")
    print(f"  On Laptop 2 run: python tools/init_env.py --role node --host {ip}   (or setup_node.ps1 -ServerIp {ip})")
    print(f"  Dashboard from any laptop on this Wi-Fi: http://{ip}:1880/dashboard")
    if ip.startswith("127.") or ip.startswith("169.254."):
        print("  WARNING: no usable network address - connect both laptops to the same Wi-Fi/LAN first.")
