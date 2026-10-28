"""Uso:
  python -m metaclean                     abre a interface no navegador
  python -m metaclean inspect FOTO...     lista os metadados
  python -m metaclean clean FOTO... [-o PASTA] [--sem-orientacao]
"""

import argparse
import sys
from pathlib import Path

from . import core
from .server import serve

LABELS = {"ai": "IA", "location": "LOCAL", "device": "APARELHO", "identity": "AUTOR"}


def main(argv=None):
    p = argparse.ArgumentParser(prog="metaclean", description="Remove metadados de imagens localmente.")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="abre a interface web local")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    i = sub.add_parser("inspect", help="mostra os metadados")
    i.add_argument("files", nargs="+", type=Path)
    c = sub.add_parser("clean", help="remove os metadados")
    c.add_argument("files", nargs="+", type=Path)
    c.add_argument("-o", "--out", type=Path, help="pasta de saída (padrão: ao lado do original)")
    c.add_argument("--sem-orientacao", action="store_true", help="remove também a tag Orientation")
    args = p.parse_args(argv)

    if args.cmd in (None, "serve"):
        serve(port=getattr(args, "port", 8765), open_browser=not getattr(args, "no_browser", False))
        return 0

    status = 0
    for f in args.files:
        try:
            data = f.read_bytes()
            if args.cmd == "inspect":
                info = core.inspect(data)
                print(f"\n{f} ({info['format']}, {info['summary']['removable']} metadados removíveis)")
                for t in info["tags"]:
                    mark = "mantido" if t.get("kept") else LABELS.get(t.get("flag"), "")
                    print(f"  [{t['group']}] {t['name']}: {t['value'][:120]}" + (f"  <{mark}>" if mark else ""))
            else:
                before = core.inspect(data)
                cleaned = core.clean(data, keep_orientation=not args.sem_orientacao)
                after = core.inspect(cleaned)
                dest = (args.out or f.parent) / core.cleaned_name(f.name, before["format"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(cleaned)
                print(f"{f} -> {dest}: {before['summary']['removable']} removidos, "
                      f"{after['summary']['removable']} restantes")
        except Exception as exc:  # noqa: BLE001
            print(f"{f}: erro: {exc}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
