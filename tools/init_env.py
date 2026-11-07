"""Create or complete .env with strong random credentials (Python `secrets`, never printed in full).

  Laptop 1 (server):  python tools/init_env.py --role server
      creates .env from .env.example, generates SC_SERVER_PASSWORD, SC_NODE_PASSWORD and SC_EDITOR_PASSWORD,
      then prints the NODE password once so you can type it on Laptop 2 (it is not stored anywhere else).
  Laptop 2 (node):    python tools/init_env.py --role node --host 192.168.1.50
      creates .env, sets SC_MQTT_HOST and asks for the node password shown on Laptop 1 (input is hidden).

Existing real values are kept; only empty values and the 'change-me-*' placeholders are replaced.
Use --rotate to replace the generated passwords (then re-run make_broker_users.py and restart).
"""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = re.compile(r"^(|change-me.*)$")


def is_unset(value: str | None) -> bool:
    return value is None or bool(PLACEHOLDER.match(value.strip()))


def read_env(path: Path) -> list[str]:
    source = path if path.exists() else ROOT / ".env.example"
    return source.read_text(encoding="utf-8").splitlines()


def set_value(lines: list[str], key: str, value: str) -> list[str]:
    pattern = re.compile(rf"^\s*#?\s*{re.escape(key)}\s*=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            return lines
    return lines + [f"{key}={value}"]


def get_value(lines: list[str], key: str) -> str | None:
    for line in lines:
        m = re.match(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", line)
        if m:
            return m.group(1)
    return None


def new_password() -> str:
    return secrets.token_urlsafe(18)          # 24 URL-safe characters, ~144 bits


def mask(value: str) -> str:
    return value[:3] + "…" + value[-2:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--role", choices=["server", "node"], required=True)
    parser.add_argument("--host", help="Laptop 1 LAN IP (node role)")
    parser.add_argument("--node-password", help="node password from Laptop 1 (otherwise asked, hidden)")
    parser.add_argument("--rotate", action="store_true", help="replace already generated passwords")
    parser.add_argument("--env", default=str(ROOT / ".env"))
    args = parser.parse_args(argv)
    env_path = Path(args.env)
    lines = read_env(env_path)
    changed: list[str] = []

    if args.role == "server":
        keys = ["SC_SERVER_PASSWORD", "SC_NODE_PASSWORD", "SC_EDITOR_PASSWORD"]
        for key in keys:
            if args.rotate or is_unset(get_value(lines, key)):
                lines = set_value(lines, key, new_password())
                changed.append(key)
        if is_unset(get_value(lines, "SC_EDITOR_USERNAME")):
            lines = set_value(lines, "SC_EDITOR_USERNAME", "admin")
    else:
        if args.host:
            try:
                ipaddress.ip_address(args.host)
            except ValueError:
                print(f"--host must be an IP address such as 192.168.1.50, got {args.host!r}")
                return 2
            lines = set_value(lines, "SC_MQTT_HOST", args.host)
            changed.append("SC_MQTT_HOST")
        if args.rotate or is_unset(get_value(lines, "SC_NODE_PASSWORD")):
            password = args.node_password or getpass.getpass("Node password shown on Laptop 1 (hidden): ")
            if is_unset(password) or len(password) < 12:
                print("A node password of at least 12 characters is required (run init_env.py --role server on Laptop 1).")
                return 2
            lines = set_value(lines, "SC_NODE_PASSWORD", password)
            changed.append("SC_NODE_PASSWORD")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    print(f"{env_path.name}: {'updated ' + ', '.join(changed) if changed else 'already complete, nothing changed'}")
    if args.role == "server":
        node_pw = get_value(lines, "SC_NODE_PASSWORD") or ""
        if "SC_NODE_PASSWORD" in changed:
            print("Type this node password on Laptop 2 when init_env.py asks for it (shown once):")
            print(f"    {node_pw}")
        else:
            print(f"Node password unchanged ({mask(node_pw)}); it is in .env on this laptop.")
        print("Editor login: user 'admin', password = SC_EDITOR_PASSWORD in .env.")
        print("Next: python tools/make_broker_users.py   (writes the broker password file)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
