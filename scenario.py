"""Reset the ERP fixture, switch its layout, or verify a downloaded report."""

import argparse
import csv
from io import StringIO, TextIOWrapper
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


EXPECTED_REPORT = {
    "ORD-1001": ("Bora Supply", "Shipped"),
    "ORD-1002": ("Maple Office", "Shipped"),
    "ORD-1003": ("Harbor Studio", "Shipped"),
}
EXPECTED_BASELINE = {
    **EXPECTED_REPORT,
    "ORD-1001": ("Bora Supply", "Pending"),
    "ORD-1002": ("Maple Office", "Pending"),
}
REPORT_HEADER = ["Order ID", "Customer", "Status"]


def change_fixture(base, route, **fields):
    address = urlsplit(base)
    if address.scheme != "http" or not address.hostname or address.username or address.password:
        raise ValueError("Provide the HTTP base URL of the demo fixture.")
    if address.path not in ("", "/") or address.query or address.fragment:
        raise ValueError("The fixture URL must contain only a host and optional port.")
    request = Request(base.rstrip("/") + route, data=urlencode(fields).encode(), method="POST")
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def read_orders(stream):
    actual = {}
    reader = csv.DictReader(stream)
    if reader.fieldnames != REPORT_HEADER:
        raise ValueError("Unexpected order report header.")
    for row in reader:
        order_id = row["Order ID"]
        if not order_id or order_id in actual or None in row or None in row.values():
            raise ValueError("The report contains a duplicate or malformed order.")
        actual[order_id] = (row["Customer"], row["Status"])
    return actual


def reset_fixture(base):
    result = change_fixture(base, "/api/reset")
    if result != {"status": "reset", "layout": "v1"}:
        raise ValueError("The fixture did not reset to v1.")
    with urlopen(base.rstrip("/") + "/orders.csv", timeout=10) as response:
        orders = read_orders(TextIOWrapper(response, encoding="utf-8-sig", newline=""))
    if orders != EXPECTED_BASELINE:
        raise ValueError("The fixture report does not match the reset order baseline.")
    return result


def switch_layout(base, layout):
    result = change_fixture(base, "/api/layout", layout=layout)
    if result != {"layout": layout}:
        raise ValueError("The requested fixture layout was not confirmed.")
    return result


def verify_csv(report):
    with report.open(encoding="utf-8-sig", newline="") as stream:
        actual = read_orders(stream)
    if actual != EXPECTED_REPORT:
        raise ValueError("The order report does not match the expected shipped orders.")
    return {"status": "verified", "orders": len(actual), "report": str(report)}


def prepare_scratch_artifact(report):
    def encode_orders(orders):
        output = StringIO(newline="")
        rows = csv.writer(output)
        rows.writerow(REPORT_HEADER)
        rows.writerows((id_, *orders[id_]) for id_ in sorted(orders))
        return output.getvalue().encode("utf-8")

    baseline = encode_orders(EXPECTED_BASELINE)
    expected = encode_orders(EXPECTED_REPORT)
    with report.open("xb") as output:
        output.write(baseline)
    return {"status": "scratch_artifact_prepared", "report": str(report),
            "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
            "expected_sha256": hashlib.sha256(expected).hexdigest()}


def serve_scratch(port):
    from app import ERP

    with ERP(("127.0.0.1", port)) as fixture:
        fixture.layout = "v2"
        print(json.dumps({"status": "scratch_erp_ready", "layout": "v2",
                          "url": f"http://127.0.0.1:{fixture.server_port}"}), flush=True)
        try:
            fixture.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reset")
    layout = commands.add_parser("layout")
    layout.add_argument("version", choices=("v1", "v2"))
    report = commands.add_parser("verify-csv")
    report.add_argument("report", type=Path)
    artifact = commands.add_parser("scratch-baseline")
    artifact.add_argument("report", type=Path)
    scratch = commands.add_parser("serve-scratch")
    scratch.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    try:
        if args.command == "reset":
            result = reset_fixture(args.url)
        elif args.command == "layout":
            result = switch_layout(args.url, args.version)
        elif args.command == "verify-csv":
            result = verify_csv(args.report)
        elif args.command == "scratch-baseline":
            result = prepare_scratch_artifact(args.report)
        else:
            serve_scratch(args.port)
            return
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
