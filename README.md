# VAMP Demo ERP

A standalone synthetic order dashboard for the VAMP replay and repair showcase. It runs independently and accepts only demo data. Orders live in an in-memory SQLite database and reset on process restart.

```sh
podman build -t vamp-demo-erp .
podman run --rm -p 127.0.0.1:8080:8080 vamp-demo-erp
```

Open [localhost:8080](http://127.0.0.1:8080). Search by order ID or customer, update a pending order to Shipped, and export the orders as CSV. For a browser running inside a VirtualBox guest, publish the port on an interface reachable from that guest and keep access limited to the lab network.

The fixture was also verified with rootless Podman inside a Debian VirtualBox guest. If the test guest lacks Podman's rootless network helper, run a guest-only smoke test with `podman run --rm --network=host -e ERP_BIND=127.0.0.1 vamp-demo-erp` and open the URL from that same guest.

```sh
curl -X POST http://127.0.0.1:8080/api/reset
curl -d layout=v2 http://127.0.0.1:8080/api/layout
curl -o orders.csv http://127.0.0.1:8080/orders.csv
```

Reset restores the original three orders and v1 layout. Switching to v2 preserves orders but moves **Update Status** into **Actions → Fulfillment** and changes its selectors. Reset before each demonstration so both layouts start with identical data.

To run without a container, use Python 3.12 and run `python app.py` from this directory.

## Repeatable replay and repair fixture

1. Run `python scenario.py reset` before replay. The ERP starts in v1 with two pending orders.
2. In the guest browser, ship both pending orders and download the CSV. Run `python scenario.py verify-csv <downloaded-file>` against that artifact.
3. Run `python scenario.py reset` followed by `python scenario.py layout v2`. Run the original replay against the relocated action and retain its failure result.
4. After repairing and reviewing the replay, reset and select v2 again. Run the revised replay and verify the freshly downloaded CSV.

Use a fresh download path on every run so an earlier successful report cannot be passed off as a new result. If the fixture runs on another lab endpoint, pass `--url http://host:port` before the command.

### Replay against a VirtualBox browser guest

Use a disposable Windows VM named `VAMP-Issue17-<name>`, with Guest Additions and a **1920×1080** guest framebuffer. Open the demo ERP in an English-language Edge window with translation and download popups dismissed. Use a fresh browser profile or an empty download directory.

Expose the fixture to the host on loopback and to the browser guest on the controlled lab network. For example, a VirtualBox NAT guest configured to reach the host loopback can use `http://10.0.2.2:18080` when the host fixture is bound to `127.0.0.1:18080`.

From the demo repository, run the script with the VAMP host Python that has the VirtualBox SDK and OCR configured:

```text
python virtualbox_demo.py --vamp-repo <VAMP-checkout> --vm <disposable-VM-UUID> --guest-user <fixture-user> --guest-password-file <private-host-file> --v1-download <guest-path-to-orders.csv> --v2-download <guest-path-to-orders-(1).csv>
```

The script drives the guest browser through the v1 controls, checks that the old action stops on v2, then locates the v2 controls with local OCR. It checks that both absolute CSV paths inside the guest are unused before replay and checks each path again immediately before export. Each new CSV must match the fixture report.

For a Robot Framework report, set the following environment variables in the same terminal and run the suite with that VAMP host Python. Use fresh guest download paths and keep the password file on the host.

| Environment variable | Value |
| --- | --- |
| `VAMP_DEMO_REPO` | VAMP checkout path |
| `VAMP_DEMO_VM` | Disposable Windows VirtualBox VM UUID |
| `VAMP_DEMO_GUEST_USER` | Guest test account |
| `VAMP_DEMO_GUEST_PASSWORD_FILE` | Host path to the test account password file |
| `VAMP_DEMO_V1_DOWNLOAD` and `VAMP_DEMO_V2_DOWNLOAD` | Distinct paths inside the guest for the two downloads |
| `VAMP_DEMO_HOST_URL` and `VAMP_DEMO_GUEST_URL` | Optional fixture URLs. Defaults are the loopback and NAT URLs above. |

```text
python -m robot --outputdir qa virtualbox_demo.robot
```

Robot writes `report.html`, `log.html` and `output.xml` under `qa/`. A pass requires both verified downloads with the same SHA-256 and zero actions from the outdated replay against v2. The suite exercises the scripted fixture. The manual VSIX and AI chat walkthrough is tracked in [VAMP #19](https://github.com/wayfarer6/vamp-mcp/issues/19).
