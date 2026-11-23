#!/usr/bin/env python3
"""Compare DuckDB CSV inference for each input against a reference CSV."""

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import duckdb


DIALECT_FIELDS = (
    "delimiter", "quote", "escape", "newline", "skip_rows", "has_header",
    "date_format", "timestamp_format",
)


class InputError(ValueError):
    pass


def sniff(connection, pathname, sample_size):
    path = Path(pathname).resolve(strict=True)
    if not path.is_file():
        raise InputError("expected a local regular file")
    # DuckDB's CSV reader interprets glob metacharacters in filenames.
    filename = path.as_posix()
    if any(character in filename for character in "*?[]"):
        raise InputError("the resolved filename contains CSV glob metacharacters")
    result = connection.execute(
        """
        SELECT Delimiter, Quote, Escape, NewLineDelimiter, SkipRows, HasHeader,
               DateFormat, TimestampFormat, Columns
        FROM sniff_csv(?, sample_size = ?)
        """,
        [filename, sample_size],
    ).fetchone()
    if result is None:
        raise InputError("the CSV sniffer returned no result")
    dialect = dict(zip(DIALECT_FIELDS, result[:-1], strict=True))
    columns = result[-1]
    names = [column["name"] for column in columns]
    if len(names) != len(set(names)):
        raise InputError("inferred column names are not unique")
    return {"dialect": dialect, "columns": columns}


def differences(reference, current):
    changes = []
    for field in DIALECT_FIELDS:
        before = reference["dialect"][field]
        after = current["dialect"][field]
        if before != after:
            changes.append({"kind": "dialect", "field": field, "before": before, "after": after})

    before = {column["name"]: column["type"] for column in reference["columns"]}
    after = {column["name"]: column["type"] for column in current["columns"]}
    for name, datatype in before.items():
        if name not in after:
            changes.append({"kind": "column_removed", "column": name, "before": datatype})
        elif datatype != after[name]:
            changes.append({"kind": "column_type", "column": name, "before": datatype, "after": after[name]})
    for name, datatype in after.items():
        if name not in before:
            changes.append({"kind": "column_added", "column": name, "after": datatype})

    # A change to the relative order of shared columns matters even when
    # another column was added or removed.
    old_order = [name for name in before if name in after]
    new_order = [name for name in after if name in before]
    if old_order != new_order:
        changes.append({"kind": "column_order", "before": old_order, "after": new_order})
    return changes


def inspect_file(connection, filename, sample_size):
    try:
        return {"path": filename, "fingerprint": sniff(connection, filename, sample_size)}
    except InputError as error:
        return {"path": filename, "error": str(error)}
    except (OSError, RuntimeError) as error:
        return {"path": filename, "error": f"cannot open local file ({type(error).__name__})"}
    except duckdb.Error as error:
        # DuckDB diagnostics can include entire source records.
        return {"path": filename, "error": f"DuckDB could not infer CSV settings ({type(error).__name__})"}


def check(reference_path, files, sample_size, synthetic=False):
    with duckdb.connect(
        ":memory:",
        config={
            "autoload_known_extensions": "false",
            "autoinstall_known_extensions": "false",
        },
    ) as connection:
        reference = inspect_file(connection, reference_path, sample_size)
        results = []
        for filename in files:
            current = inspect_file(connection, filename, sample_size)
            if "error" not in reference and "error" not in current:
                current["changes"] = differences(reference["fingerprint"], current["fingerprint"])
            results.append(current)

    return {
        "version": 1,
        "duckdb_version": duckdb.__version__,
        "synthetic": synthetic,
        "sample_size": sample_size,
        "reference": reference,
        "files": results,
        "changed_files": sum(bool(item.get("changes")) for item in results),
        "errors": sum("error" in item for item in [reference, *results]),
    }


def demo():
    examples = {
        "reference.csv": "id,amount\n1,50\n2,35\n",
        "same.csv": "id,amount\n3,75\n4,100\n",
        "changed.csv": "id;amount;currency\n5;unknown;USD\n6;missing;EUR\n",
    }
    with TemporaryDirectory(prefix="csv-preflight-") as folder:
        root = Path(folder)
        paths = [str(root / filename) for filename in examples]
        for path, data in zip(paths, examples.values(), strict=True):
            Path(path).write_text(data, encoding="utf-8", newline="\n")
        report = check(paths[0], paths[1:], sample_size=-1, synthetic=True)
        for item in [report["reference"], *report["files"]]:
            item["path"] = Path(item["path"]).name
        return report


def render(report):
    if report["synthetic"]:
        print("Synthetic demo using DuckDB CSV inference")
    reference = report["reference"]
    print(f"Reference {ascii(reference['path'])} (DuckDB {report['duckdb_version']}, sample size {report['sample_size']})")
    if "error" in reference:
        print(f"  ERROR: {reference['error']}")
    for item in report["files"]:
        print(ascii(item["path"]))
        if "error" in item:
            print(f"  ERROR: {item['error']}")
            continue
        if "changes" not in item:
            print("  Comparison unavailable: reference could not be read")
            continue
        if not item["changes"]:
            print("  No inferred differences")
            continue
        for change in item["changes"]:
            subject = change.get("field", change.get("column", "shared columns"))
            before = ascii(change["before"]) if "before" in change else "(absent)"
            after = ascii(change["after"]) if "after" in change else "(absent)"
            print(f"  {change['kind']} {ascii(subject)}: {before} -> {after}")
    print(f"{report['changed_files']} changed file(s), {report['errors']} input error(s)")


def parse_sample_size(value):
    count = int(value)
    if count == -1 or 1 <= count <= 10_000_000:
        return count
    raise argparse.ArgumentTypeError("use -1 or an integer from 1 to 10000000")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check", help="compare each input with a known-good CSV")
    check_parser.add_argument("reference", help="known-good CSV")
    check_parser.add_argument("files", nargs="+", help="candidate CSV paths")
    check_parser.add_argument("--sample-size", type=parse_sample_size, default=20_480,
                              help="DuckDB sample size (default: 20480; -1 sniffs the whole file)")
    check_parser.add_argument("--json", action="store_true", help="emit versioned JSON")
    demo_parser = commands.add_parser("demo", help="run a labeled synthetic example")
    demo_parser.add_argument("--json", action="store_true", help="emit versioned JSON")

    args = parser.parse_args(argv)
    try:
        report = demo() if args.command == "demo" else check(args.reference, args.files, args.sample_size)
    except (duckdb.Error, OSError) as error:
        print(f"csv-preflight: could not initialize the check ({type(error).__name__})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        render(report)
    if report["errors"]:
        return 2
    return int(args.command == "check" and report["changed_files"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
