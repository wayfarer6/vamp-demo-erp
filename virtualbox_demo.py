"""Run the ERP replay and layout-change demo on a disposable VirtualBox guest."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen
from uuid import UUID

from scenario import change_fixture, verify_csv


RESOLUTION = [1920, 1080]
PENDING_ORDERS = ("ORD-1001", "ORD-1002")


def parse_origin(value):
    origin = urlsplit(value)
    if (origin.scheme != "http" or not origin.hostname or origin.username or origin.password
            or origin.path not in ("", "/") or origin.query or origin.fragment):
        raise argparse.ArgumentTypeError("Use an HTTP origin with a host and optional port.")
    return value.rstrip("/")


async def run_demo(args):
    sys.path.insert(0, str(args.vamp_repo.resolve()))
    from backends.library.replay import (
        StartScreenBlocked, VBox, normalized_text, recognize_start_screen, replay,
    )
    from backends.library.scratch import scratch_artifact_hash, show_vm

    if urlsplit(args.host_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The host ERP fixture URL must be loopback.")
    vm = str(args.vm)
    configuration = show_vm(vm)
    if (configuration.get("UUID") != vm or configuration.get("VMState") != "running"
            or not configuration.get("name", "").startswith("VAMP-Issue17-")):
        raise ValueError("Select a running disposable VM named VAMP-Issue17-… by UUID.")
    password_file = args.guest_password_file.resolve(strict=True)

    async def dispatch(*actions, start_text=None, outcome_text=None):
        return await replay(VBox(vm), list(actions), RESOLUTION,
                            start_text=start_text, outcome_text=outcome_text)

    async def visit(order=None):
        suffix = "/?" + urlencode({"q": order}) if order else "/"
        await dispatch(
            {"op": "hotkey", "keys": ["ctrl", "l"]},
            {"op": "write", "text": args.guest_url + suffix, "interval": 0.03},
            {"op": "press", "keys": ["enter"], "presses": 1, "interval": 0},
            {"op": "wait", "seconds": 3},
            outcome_text="Export CSV",
        )

    async def locate(label, min_y):
        with TemporaryDirectory(prefix="vamp-erp-screen-") as folder:
            path = Path(folder) / "screen.png"
            driver = VBox(vm)
            try:
                if driver.geometry() != RESOLUTION:
                    raise ValueError("The guest framebuffer must be 1920×1080.")
                await driver.capture(path, RESOLUTION)
            finally:
                driver.close()
            lines = await asyncio.to_thread(recognize_start_screen, path, label)
        boxes = [line["xyxy"] for line in lines if float(line["confidence"]) >= 0.8
                 and normalized_text(line["text"]) == normalized_text(label)
                 and line["xyxy"][1] >= min_y]
        if len(boxes) != 1:
            raise ValueError(f"Expected one visible {label!r} control.")
        left, top, right, bottom = boxes[0]
        return {"op": "click", "x": (left + right) // 2, "y": (top + bottom) // 2,
                "button": "left", "clicks": 1, "interval": 0}

    async def click(label, min_y=370):
        await dispatch(await locate(label, min_y), {"op": "wait", "seconds": 1})

    def check_download(guest_path):
        with TemporaryDirectory(prefix="vamp-erp-report-") as folder:
            report = Path(folder) / "orders.csv"
            with urlopen(args.host_url + "/orders.csv", timeout=5) as response:
                report.write_bytes(response.read())
            verify_csv(report)
            expected = hashlib.sha256(report.read_bytes()).hexdigest()
        actual = scratch_artifact_hash(vm, (guest_path, args.guest_user, password_file, "", ""))
        if actual != expected:
            raise ValueError("The guest download differs from the verified ERP report.")
        return actual

    change_fixture(args.host_url, "/api/reset")
    first_click = None
    for order in PENDING_ORDERS:
        await visit(order)
        action = await locate("Update Status", 370)
        if first_click is None:
            first_click = action
        await dispatch(action, {"op": "wait", "seconds": 1}, start_text="Update Status")
    await click("Export CSV", 175)
    v1_hash = check_download(args.v1_download)
    print(json.dumps({"stage": "v1_download_verified", "sha256": v1_hash}), flush=True)

    change_fixture(args.host_url, "/api/reset")
    change_fixture(args.host_url, "/api/layout", layout="v2")
    await visit(PENDING_ORDERS[0])
    try:
        await dispatch(first_click, start_text="Update Status")
    except StartScreenBlocked as error:
        if "mismatch" not in str(error).lower():
            raise
    else:
        raise ValueError("The v1 action was dispatched despite the layout change.")
    print(json.dumps({"stage": "v1_replay_blocked_on_v2", "actions_completed": 0}), flush=True)

    for order in PENDING_ORDERS:
        await visit(order)
        for label in ("Actions", "Fulfillment", "Update Status"):
            await click(label)
    await click("Export CSV", 175)
    v2_hash = check_download(args.v2_download)
    print(json.dumps({"stage": "v2_download_verified", "sha256": v2_hash}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vamp-repo", required=True, type=Path)
    parser.add_argument("--vm", required=True, type=UUID)
    parser.add_argument("--host-url", type=parse_origin, default="http://127.0.0.1:18080")
    parser.add_argument("--guest-url", type=parse_origin, default="http://10.0.2.2:18080")
    parser.add_argument("--guest-user", required=True)
    parser.add_argument("--guest-password-file", required=True, type=Path)
    parser.add_argument("--v1-download", required=True)
    parser.add_argument("--v2-download", required=True)
    args = parser.parse_args()
    if args.v1_download == args.v2_download:
        parser.error("Use distinct fresh guest download paths.")
    asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()
