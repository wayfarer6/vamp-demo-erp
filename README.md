# VAMP Demo ERP

A standalone synthetic order dashboard for the VAMP replay and repair showcase. It runs independently and accepts only demo data. Orders live in an in-memory SQLite database and reset on process restart.

```sh
podman build -t vamp-demo-erp .
podman run --rm -p 127.0.0.1:8080:8080 vamp-demo-erp
```

Open [localhost:8080](http://127.0.0.1:8080). Search by order ID or customer, update a pending order to Shipped, and export the orders as CSV. For a browser running inside a VirtualBox guest, publish the port on an interface reachable from that guest and keep access limited to the lab network.

```sh
curl -X POST http://127.0.0.1:8080/api/reset
curl -d layout=v2 http://127.0.0.1:8080/api/layout
curl -o orders.csv http://127.0.0.1:8080/orders.csv
```

Reset restores the original three orders and v1 layout. Switching to v2 preserves orders but moves **Update Status** into **Actions → Fulfillment** and changes its selectors. Reset before each demonstration so both layouts start with identical data.

To run without a container, use Python 3.12 and run `python app.py` from this directory.
