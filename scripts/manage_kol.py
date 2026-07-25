"""KOL 名单管理。

用法:
    .venv/bin/python scripts/manage_kol.py add <handle> [--category <cat>] [--notes <n>]
    .venv/bin/python scripts/manage_kol.py remove <handle>
    .venv/bin/python scripts/manage_kol.py list
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stockradar.db import get_db, upsert_kol, list_kols


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    conn = get_db()
    cmd = args[0]

    if cmd == "add" and len(args) >= 2:
        handle = args[1].lstrip("@")
        kwargs = {}
        if "--category" in args:
            kwargs["category"] = args[args.index("--category") + 1]
        if "--notes" in args:
            kwargs["notes"] = args[args.index("--notes") + 1]
        kol_id = upsert_kol(conn, handle, **kwargs)
        print(f"[ok] @{handle} (id={kol_id})")

    elif cmd == "remove" and len(args) >= 2:
        handle = args[1].lstrip("@").lower()
        conn.execute("UPDATE kol SET enabled=0 WHERE handle=?", (handle,))
        conn.commit()
        print(f"[ok] @{handle} 已禁用")

    elif cmd == "list":
        kols = list_kols(conn, enabled_only=False)
        if not kols:
            print("名单为空")
        for k in kols:
            status = "✓" if k["enabled"] else "✗"
            print(f"  {status} @{k['handle']:20s} {k.get('category',''):15s} {k.get('display_name','')}")

    else:
        print(__doc__)
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
