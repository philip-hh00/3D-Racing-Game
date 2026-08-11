"""Pack / unpack the relay server catalogue (data/settings/servers.dat).

The plaintext list is deliberately NOT kept in the repository — the .dat is the
single source of truth. Edit it round-trip:

    python tools/pack_servers.py --unpack > servers.json    # read it out
    ...edit servers.json...
    python tools/pack_servers.py servers.json               # write it back

Reminder: the blob is obfuscated, not encrypted. See src/net/servers.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.net import servers  # noqa: E402

DAT_PATH = Path("data") / "settings" / "servers.dat"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="JSON file with the server list")
    ap.add_argument("--unpack", action="store_true",
                    help="print the current .dat as JSON instead of packing")
    ap.add_argument("--out", default=str(DAT_PATH), help=f"output path (default {DAT_PATH})")
    args = ap.parse_args()

    if args.unpack:
        blob = Path(args.out).read_text("utf-8")
        json.dump(servers.decode(blob), sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    if not args.source:
        ap.error("need a source JSON file (or --unpack)")

    entries = json.loads(Path(args.source).read_text("utf-8"))
    if not isinstance(entries, list) or not entries:
        print("source must be a non-empty JSON list", file=sys.stderr)
        return 1

    # Validate through the same parser the game uses, so a typo fails here and
    # not at runtime in front of a player.
    parsed = servers._parse_list(entries)
    if len(parsed) != len(entries):
        print("some entries were rejected — check id/code_prefix/tcp_host/tcp_port",
              file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(servers.encode(entries), "utf-8")
    print(f"wrote {out} ({len(entries)} servers: "
          f"{', '.join(s.code_prefix + '=' + s.id for s in parsed)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
