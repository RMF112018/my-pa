"""Profile the legacy SQLite source database for the my-pa PostgreSQL migration.

READ-ONLY. The source is opened with `immutable=1` and is never written to.

Privacy: this script records ONLY identifiers, DDL, type names and counts.
No row value is ever selected into the output. `typeof()` sampling returns
storage-class *names* only.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

COUNT_TIMEOUT_SECONDS = 120.0
SAMPLE_LIMIT = 1000

FTS_SHADOW_SUFFIXES = (
    "_data",
    "_idx",
    "_content",
    "_docsize",
    "_config",
    "_segments",
    "_segdir",
    "_stat",
    "_stemmer",
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def affinity(declared: str) -> str:
    """SQLite column affinity resolution (datatype3.html section 3.1)."""
    t = (declared or "").upper()
    if "INT" in t:
        return "INTEGER"
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return "TEXT"
    if t == "" or "BLOB" in t:
        return "BLOB"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "REAL"
    return "NUMERIC"


def connect(source: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{source}?immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def q(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    cur = conn.execute(sql, params)
    try:
        return cur.fetchall()
    finally:
        cur.close()


def counted(conn: sqlite3.Connection, ident: str) -> tuple[int | None, float, str | None]:
    """Exact COUNT(*) with a wall-clock abort guard. Returns (count, seconds, error)."""
    deadline = time.monotonic() + COUNT_TIMEOUT_SECONDS
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20000)
    start = time.monotonic()
    try:
        # S608: a table name cannot be a bound parameter. `ident` comes from
        # `sqlite_master` in a read-only local file, not from any input.
        row = conn.execute(f'SELECT COUNT(*) FROM "{ident}"').fetchone()  # noqa: S608
        return int(row[0]), time.monotonic() - start, None
    except sqlite3.OperationalError as exc:
        elapsed = time.monotonic() - start
        if elapsed >= COUNT_TIMEOUT_SECONDS - 1:
            return None, elapsed, f"row_count_timeout: aborted after {elapsed:.1f}s"
        return None, elapsed, f"{type(exc).__name__}: {exc}"
    except sqlite3.DatabaseError as exc:
        return None, time.monotonic() - start, f"{type(exc).__name__}: {exc}"
    finally:
        conn.set_progress_handler(None, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="legacy SQLite file")
    parser.add_argument("--output", type=Path, required=True, help="profile JSON to write")
    args = parser.parse_args()
    source: Path = args.source
    output: Path = args.output

    conn = connect(source)
    log(f"opened {source} (immutable)")

    master = q(
        conn,
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE type IN ('table','view') ORDER BY type, name",
    )
    index_master = q(
        conn,
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index'",
    )
    index_sql_by_name = {r["name"]: r["sql"] for r in index_master}

    all_names = {r["name"] for r in master}

    # --- FTS classification -------------------------------------------------
    fts_virtual: set[str] = set()
    for r in master:
        sql = r["sql"] or ""
        if re.search(r"\bCREATE\s+VIRTUAL\s+TABLE\b", sql, re.I) and re.search(
            r"\bUSING\s+fts[345]?\b", sql, re.I
        ):
            fts_virtual.add(r["name"])
    virtual_tables = {
        r["name"]
        for r in master
        if re.search(r"\bCREATE\s+VIRTUAL\s+TABLE\b", r["sql"] or "", re.I)
    }
    fts_shadow: dict[str, str] = {}
    for name in all_names:
        for suf in FTS_SHADOW_SUFFIXES:
            if name.endswith(suf) and name[: -len(suf)] in fts_virtual:
                fts_shadow[name] = name[: -len(suf)]
                break

    log(
        f"{len(master)} objects; fts virtual={len(fts_virtual)} shadow={len(fts_shadow)} "
        f"other virtual={len(virtual_tables - fts_virtual)}"
    )

    objects: list[dict[str, Any]] = []
    global_types: Counter[str] = Counter()
    total = len(master)

    for i, r in enumerate(master, 1):
        name = r["name"]
        otype = r["type"]
        sql = r["sql"]
        entry: dict[str, Any] = {
            "name": name,
            "type": otype,
            "sql": sql,
            "is_virtual": name in virtual_tables,
            "is_fts": name in fts_virtual or name in fts_shadow,
            "fts_role": (
                "fts_virtual"
                if name in fts_virtual
                else ("fts_shadow" if name in fts_shadow else None)
            ),
            "fts_base_table": fts_shadow.get(name),
            "without_rowid": bool(re.search(r"WITHOUT\s+ROWID", sql or "", re.I)),
            "is_internal": name.startswith("sqlite_"),
            "errors": [],
        }

        # --- columns --------------------------------------------------------
        cols: list[dict[str, Any]] = []
        try:
            for c in q(conn, f'PRAGMA table_info("{name}")'):
                cols.append(
                    {
                        "cid": c["cid"],
                        "name": c["name"],
                        "declared_type": c["type"],
                        "affinity": affinity(c["type"]),
                        "notnull": bool(c["notnull"]),
                        "default": c["dflt_value"],
                        "pk": c["pk"],
                    }
                )
        except sqlite3.DatabaseError as exc:
            entry["errors"].append(f"table_info: {exc}")
        entry["columns"] = cols
        entry["column_count"] = len(cols)

        hist = Counter(c["declared_type"] for c in cols)
        entry["declared_type_histogram"] = dict(sorted(hist.items()))
        if otype == "table":
            global_types.update(hist)

        entry["primary_key"] = [
            c["name"] for c in sorted((c for c in cols if c["pk"]), key=lambda c: c["pk"])
        ]
        entry["has_primary_key"] = bool(entry["primary_key"])
        entry["is_rowid_alias_pk"] = (
            len(entry["primary_key"]) == 1
            and not entry["without_rowid"]
            and any(
                c["pk"] == 1 and affinity(c["declared_type"]) == "INTEGER"
                for c in cols
                if c["name"] == entry["primary_key"][0]
            )
        )

        # --- foreign keys ---------------------------------------------------
        fks: list[dict[str, Any]] = []
        if otype == "table":
            try:
                raw = q(conn, f'PRAGMA foreign_key_list("{name}")')
                by_id: dict[int, dict[str, Any]] = {}
                for f in raw:
                    e = by_id.setdefault(
                        f["id"],
                        {
                            "id": f["id"],
                            "referenced_table": f["table"],
                            "from_columns": [],
                            "to_columns": [],
                            "on_update": f["on_update"],
                            "on_delete": f["on_delete"],
                            "match": f["match"],
                        },
                    )
                    e["from_columns"].append(f["from"])
                    e["to_columns"].append(f["to"])
                for e in by_id.values():
                    e["referenced_table_exists"] = any(
                        n.lower() == (e["referenced_table"] or "").lower() for n in all_names
                    )
                    if all(t is None for t in e["to_columns"]):
                        e["to_columns"] = []
                    fks = sorted(by_id.values(), key=lambda x: x["id"])
            except sqlite3.DatabaseError as exc:
                entry["errors"].append(f"foreign_key_list: {exc}")
        entry["foreign_keys"] = fks

        # --- indexes --------------------------------------------------------
        idxs: list[dict[str, Any]] = []
        if otype == "table":
            try:
                for ix in q(conn, f'PRAGMA index_list("{name}")'):
                    iname = ix["name"]
                    info = q(conn, f'PRAGMA index_info("{iname}")')
                    xinfo = q(conn, f'PRAGMA index_xinfo("{iname}")')
                    idxs.append(
                        {
                            "name": iname,
                            "unique": bool(ix["unique"]),
                            "origin": ix["origin"],
                            "partial": bool(ix["partial"]),
                            "columns": [ii["name"] for ii in info],
                            "column_descending": [bool(xi["desc"]) for xi in xinfo if xi["key"]],
                            "has_expression_column": any(ii["name"] is None for ii in info),
                            "sql": index_sql_by_name.get(iname),
                        }
                    )
            except sqlite3.DatabaseError as exc:
                entry["errors"].append(f"index_list: {exc}")
        entry["indexes"] = idxs

        # --- row count ------------------------------------------------------
        cnt, secs, err = counted(conn, name)
        entry["row_count"] = cnt
        entry["row_count_seconds"] = round(secs, 3)
        if err is not None:
            entry["row_count_error"] = err
            if err.startswith("row_count_timeout"):
                entry["row_count_timeout"] = True
            entry["errors"].append(err)

        # --- ambiguous-type storage-class sampling --------------------------
        samples: dict[str, dict[str, int]] = {}
        ambiguous = [
            c["name"]
            for c in cols
            if c["affinity"] in ("BLOB", "NUMERIC") and c["name"] is not None
        ]
        if (
            ambiguous
            and otype == "table"
            and not entry["is_fts"]
            and not entry["is_virtual"]
            and cnt
        ):
            sel = ", ".join(f'typeof("{c}")' for c in ambiguous)
            inner = ", ".join(f'"{c}"' for c in ambiguous)
            try:
                rows = q(
                    conn,
                    # S608: identifiers, again from `sqlite_master`, not input.
                    f'SELECT {sel} FROM (SELECT {inner} FROM "{name}" LIMIT {SAMPLE_LIMIT})',  # noqa: S608
                )
                counters = [Counter() for _ in ambiguous]
                for row in rows:
                    for j in range(len(ambiguous)):
                        counters[j][row[j]] += 1
                for cname, ctr in zip(ambiguous, counters, strict=True):
                    samples[cname] = dict(sorted(ctr.items()))
            except sqlite3.DatabaseError as exc:
                entry["errors"].append(f"typeof_sample: {exc}")
        entry["ambiguous_columns"] = ambiguous
        entry["storage_class_samples"] = samples
        entry["storage_class_sample_size"] = SAMPLE_LIMIT

        objects.append(entry)
        log(
            f"[{i}/{total}] {otype} {name}: cols={len(cols)} idx={len(idxs)} fk={len(fks)} "
            f"rows={cnt if cnt is not None else 'ERR'} ({secs:.1f}s)"
        )

    # --- database-level -----------------------------------------------------
    db: dict[str, Any] = {"path": str(source), "size_bytes": source.stat().st_size}
    for pragma in (
        "application_id",
        "user_version",
        "page_size",
        "page_count",
        "encoding",
        "freelist_count",
        "auto_vacuum",
        "journal_mode",
    ):
        try:
            row = conn.execute(f"PRAGMA {pragma}").fetchone()
            db[pragma] = row[0] if row else None
        except sqlite3.DatabaseError as exc:
            db[pragma] = f"error: {exc}"
    db["sqlite_library_version"] = conn.execute("SELECT sqlite_version()").fetchone()[0]

    sm: dict[str, Any] = {}
    try:
        row = conn.execute("SELECT COUNT(*), MAX(version) FROM schema_migrations").fetchone()
        sm = {"row_count": row[0], "max_version": row[1]}
    except sqlite3.DatabaseError as exc:
        sm = {"error": str(exc)}
    db["schema_migrations"] = sm

    db["index_count"] = len(index_master)
    db["trigger_count"] = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'"
    ).fetchone()[0]

    profile = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": db,
        "distinct_declared_types": dict(
            sorted(global_types.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "fts": {
            "virtual_tables": sorted(fts_virtual),
            "shadow_tables": sorted(fts_shadow),
            "other_virtual_tables": sorted(virtual_tables - fts_virtual),
        },
        "objects": objects,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, indent=1, sort_keys=False), encoding="utf-8")
    log(f"wrote {output} ({output.stat().st_size} bytes)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
