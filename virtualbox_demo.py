"""Run the ERP replay and layout-change demo on a disposable VirtualBox guest."""

import argparse
import asyncio
from base64 import b64encode
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
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


def download_path(value):
    path = PureWindowsPath(value)
    if (not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive)
            or not path.name or ".." in path.parts or path.suffix.lower() != ".csv"
            or any(char in value[2:] for char in '*?<>|":\r\n\x00')):
        raise argparse.ArgumentTypeError("Use an absolute path to a CSV in the Windows guest.")
    return path


def require_fresh_download(vbox, vm, username, password_file, path, *, execute=subprocess.run):
    powershell = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    parent = str(path.parent).replace("'", "''")
    name = path.name.replace("'", "''")
    script = (
        "$ErrorActionPreference = 'Stop'; "
        f"$found = Get-ChildItem -LiteralPath '{parent}' -Force | "
        f"Where-Object {{ $_.Name -ieq '{name}' }}; "
        "if ($found) { 'VAMP_DOWNLOAD_EXISTS' } else { 'VAMP_DOWNLOAD_ABSENT' }"
    )
    encoded = b64encode(script.encode("utf-16-le")).decode("ascii")
    result = execute(
        [vbox, "guestcontrol", vm, "run", f"--username={username}",
         f"--passwordfile={password_file}", f"--exe={powershell}", "--", powershell,
         "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=30,
    )
    status = result.stdout.strip() if result.returncode == 0 else ""
    if status == "VAMP_DOWNLOAD_EXISTS":
        raise ValueError(f"The target download already exists in the guest: {path}")
    if status != "VAMP_DOWNLOAD_ABSENT":
        raise ValueError("Could not confirm that the guest download target is absent.")


async def run_demo(args):
    sys.path.insert(0, str(args.vamp_repo.resolve()))
    from backends.library.replay import (
        StartScreenBlocked, VBox, normalized_text, recognize_start_screen, replay,
    )
    from backends.library.scratch import scratch_artifact_hash, show_vm
    from backends.virtualbox.provision import executable

    if urlsplit(args.host_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The host ERP fixture URL must be loopback.")
    vm = str(args.vm)
    configuration = show_vm(vm)
    if (configuration.get("UUID") != vm or configuration.get("VMState") != "running"
            or not configuration.get("name", "").startswith("VAMP-Issue17-")):
        raise ValueError("Select a running disposable VM named VAMP-Issue17-… by UUID.")
    password_file = args.guest_password_file.resolve(strict=True)
    vbox = executable()
    for target in (args.v1_download, args.v2_download):
        require_fresh_download(vbox, vm, args.guest_user, password_file, target)

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
        actual = scratch_artifact_hash(vm, (str(guest_path), args.guest_user, password_file, "", ""))
        if actual != expected:
            raise ValueError("The guest download differs from the verified ERP report.")
        return actual

    async def export_report(guest_path):
        require_fresh_download(vbox, vm, args.guest_user, password_file, guest_path)
        await click("Export CSV", 175)
        digest = check_download(guest_path)
        # Edge can leave its downloads flyout over the order actions.
        await dispatch({"op": "press", "keys": ["esc"], "presses": 1, "interval": 0})
        return digest

    def report(stage, started, **results):
        print(json.dumps({"stage": stage, "elapsed_seconds": round(perf_counter() - started, 3),
                          **results}), flush=True)

    started = perf_counter()
    change_fixture(args.host_url, "/api/reset")
    first_click = None
    for order in PENDING_ORDERS:
        await visit(order)
        action = await locate("Update Status", 370)
        if first_click is None:
            first_click = action
        await dispatch(action, {"op": "wait", "seconds": 1}, start_text="Update Status")
    v1_hash = await export_report(args.v1_download)
    report("v1_download_verified", started, sha256=v1_hash)

    started = perf_counter()
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
    report("v1_replay_blocked_on_v2", started, actions_completed=0)

    started = perf_counter()
    for order in PENDING_ORDERS:
        await visit(order)
        for label in ("Actions", "Fulfillment", "Update Status"):
            await click(label)
    v2_hash = await export_report(args.v2_download)
    report("v2_download_verified", started, sha256=v2_hash)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vamp-repo", required=True, type=Path)
    parser.add_argument("--vm", required=True, type=UUID)
    parser.add_argument("--host-url", type=parse_origin, default="http://127.0.0.1:18080")
    parser.add_argument("--guest-url", type=parse_origin, default="http://10.0.2.2:18080")
    parser.add_argument("--guest-user", required=True)
    parser.add_argument("--guest-password-file", required=True, type=Path)
    parser.add_argument("--v1-download", required=True, type=download_path)
    parser.add_argument("--v2-download", required=True, type=download_path)
    args = parser.parse_args()
    if args.v1_download == args.v2_download:
        parser.error("Use distinct fresh guest download paths.")
    asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()
