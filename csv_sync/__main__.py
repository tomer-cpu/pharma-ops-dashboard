"""CLI entry point.

    python -m csv_sync run         # poll forever (service mode)
    python -m csv_sync once        # single sync cycle; exit code 1 if a delivery failed
    python -m csv_sync check       # validate configuration and source access, send nothing
    python -m csv_sync validate F  # validate one local CSV file and print the errors
    python -m csv_sync status      # show what the state database has recorded
"""

import argparse
import json
import logging
import sys

from csv_sync.config import ConfigError, SyncConfig, load_dotenv


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="csv_sync", description="Windows CSV -> Base44 sync")
    parser.add_argument("command", choices=["run", "once", "check", "validate", "status"])
    parser.add_argument("file", nargs="?", help="CSV file for the validate command")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv(args.env_file)
    cfg = SyncConfig.from_env()

    if args.command == "validate":
        from csv_sync.validator import CSVValidator
        if not args.file:
            parser.error("validate needs a file path")
        with open(args.file, "rb") as fh:
            result = CSVValidator(cfg).validate(fh.read())
        print(json.dumps({
            "file_error": result.file_error,
            "total_rows": result.total_rows,
            "valid_rows": len(result.records),
            "warnings": result.warnings,
            "errors": [{"line": e.line, "message": e.message} for e in result.errors],
        }, indent=2, ensure_ascii=False))
        return 0 if not result.file_error and not result.errors else 1

    if args.command == "status":
        from csv_sync.state import SyncState
        print(json.dumps(SyncState(cfg.state_db_path).summary(), indent=2))
        return 0

    try:
        cfg.validate()
    except ConfigError as exc:
        logging.error("Invalid configuration: %s", exc)
        return 2

    from csv_sync.service import SyncService
    service = SyncService(cfg)

    if args.command == "check":
        files = service.source.list_files()
        print(f"Configuration OK. {len(files)} file(s) visible at the source.")
        return 0
    if args.command == "once":
        report = service.run_once()
        print(f"Sent {report.sent} record(s) from {len(report.files)} file(s).")
        return 1 if report.failed else 0
    service.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
