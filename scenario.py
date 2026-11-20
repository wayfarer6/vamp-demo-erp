"""Reset the ERP fixture, switch its layout, or verify a downloaded report."""

import argparse
import csv
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


EXPECTED_REPORT = {
    "ORD-1001": ("Bora Supply", "Shipped"),
    "ORD-1002": ("Maple Office", "Shipped"),
    "ORD-1003": ("Harbor Studio", "Shipped"),
}


def change_fixture(base, route, **fields):
    address = urlsplit(base)
    if address.scheme != "http" or not address.hostname or address.username or address.password:
        raise ValueError("Provide the HTTP base URL of the demo fixture.")
    if address.path not in ("", "/") or address.query or address.fragment:
        raise ValueError("The fixture URL must contain only a host and optional port.")
    request = Request(base.rstrip("/") + route, data=urlencode(fields).encode(), method="POST")
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def verify_csv(report):
    actual = {}
    with report.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["Order ID", "Customer", "Status"]:
            raise ValueError("Unexpected order report header.")
        for row in reader:
            order_id = row["Order ID"]
            if not order_id or order_id in actual or None in row:
                raise ValueError("The report contains a duplicate or malformed order.")
            actual[order_id] = (row["Customer"], row["Status"])
    if actual != EXPECTED_REPORT:
        raise ValueError("The order report does not match the expected shipped orders.")
    return {"status": "verified", "orders": len(actual), "report": str(report)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reset")
    layout = commands.add_parser("layout")
    layout.add_argument("version", choices=("v1", "v2"))
    report = commands.add_parser("verify-csv")
    report.add_argument("report", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "reset":
            result = change_fixture(args.url, "/api/reset")
            if result != {"status": "reset", "layout": "v1"}:
                raise ValueError("The fixture did not reset to v1.")
        elif args.command == "layout":
            result = change_fixture(args.url, "/api/layout", layout=args.version)
            if result != {"layout": args.version}:
                raise ValueError("The requested fixture layout was not confirmed.")
        else:
            result = verify_csv(args.report)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
