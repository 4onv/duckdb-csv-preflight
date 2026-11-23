# DuckDB CSV Preflight

**Find the file whose CSV settings changed before it reaches your import.** Compare every export against a known-good CSV using the same DuckDB sniffer. Each result shows the inferred delimiter, header, skipped rows, date formats, and column changes for that file.

## Try the demo

Use Python 3.12 or newer. Clone this repo and install the pinned dependency in a virtual environment. The release also provides the standalone script and dependency pin.

```sh
python -m pip install -r requirements.txt
python csv_preflight.py demo
```

The demo generates three labeled synthetic CSVs locally and uses DuckDB to sniff them. In the changed file, the separator switches from comma to semicolon, `amount` changes from `BIGINT` to `VARCHAR`, and `currency` appears.

## Check your exports

```sh
python csv_preflight.py check known-good.csv monday.csv tuesday.csv
python csv_preflight.py check known-good.csv monday.csv tuesday.csv --sample-size -1 --json
```

Pass each candidate explicitly or use a shell that expands filename patterns into separate arguments. The reference is sniffed once. Candidates are checked independently and listed in argument order. JSON includes the DuckDB version, the requested sample size, and per-file changes or errors. Review filenames and inferred column names before sharing a report.

| Exit | Meaning |
| --- | --- |
| 0 | All candidates match the reference's inferred settings. The demo also exits 0 when it runs successfully. |
| 1 | At least one candidate differs. |
| 2 | A command or input error prevented a complete comparison. The report retains results for other readable files. |

The comparison covers delimiter, quote, escape, newline, skipped rows, header detection, date and timestamp formats, column names (case-sensitive), types, and the order of shared columns. Additions and removals are reported independently.

## Scope

DuckDB infers settings from a sample of 20,480 rows by default. `--sample-size -1` asks the sniffer to sample the whole file and can be slower. Inference can change with the sample or engine version, and a text-only file may be ambiguous. Use a representative reference and keep the DuckDB version pinned in CI. A match describes the sniffer's inference. Row validation, mixed dialects within a file, and checks against a separately declared schema require additional checks. The tool expects local files with literal paths. It does not expand globs itself. [DuckDB CSV auto-detection](https://duckdb.org/docs/stable/data/csv/auto_detection) · [Combining schemas](https://duckdb.org/docs/stable/data/multiple_files/combining_schemas)

```sh
python -m unittest discover -s tests -v
```

MIT license. [November 22 research and alternatives](docs/research-2026-11-22.md)
