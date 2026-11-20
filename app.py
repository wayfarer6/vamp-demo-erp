import csv
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import os
import signal
import sqlite3
from threading import RLock
from urllib.parse import parse_qs, urlsplit


SEED = (
    ("ORD-1001", "Bora Supply", "Pending"),
    ("ORD-1002", "Maple Office", "Pending"),
    ("ORD-1003", "Harbor Studio", "Shipped"),
)


class ERP(ThreadingHTTPServer):
    def __init__(self, address):
        super().__init__(address, Handler)
        self.lock = RLock()
        self.orders = sqlite3.connect(":memory:", check_same_thread=False)
        self.orders.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, customer TEXT, status TEXT)")
        self.reset()

    def reset(self):
        with self.lock, self.orders:
            self.orders.execute("DELETE FROM orders")
            self.orders.executemany("INSERT INTO orders VALUES (?, ?, ?)", SEED)
            self.layout = "v1"

    def snapshot(self):
        with self.lock:
            return self.layout, list(self.orders.execute("SELECT * FROM orders ORDER BY id"))

    def server_close(self):
        super().server_close()
        with self.lock:
            self.orders.close()


class Handler(BaseHTTPRequestHandler):
    def send_content(self, content, content_type, status=200, **headers):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, **value):
        self.send_content(json.dumps(value), "application/json")

    def do_GET(self):
        route = urlsplit(self.path)
        if route.path == "/style.css":
            self.send_content(STYLE, "text/css; charset=utf-8")
        elif route.path == "/orders.csv":
            output = StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow(("Order ID", "Customer", "Status"))
            _, rows = self.server.snapshot()
            writer.writerows(rows)
            self.send_content(output.getvalue(), "text/csv; charset=utf-8",
                              Content_Disposition='attachment; filename="orders.csv"')
        elif route.path == "/":
            query = parse_qs(route.query).get("q", [""])[0][:120].strip().casefold()
            layout, rows = self.server.snapshot()
            visible_rows = "".join(
                self.order_row(order, customer, status, layout)
                for order, customer, status in rows
                if query in order.casefold() or query in customer.casefold()
            )
            page = PAGE.format(query=escape(query, quote=True), rows=visible_rows)
            self.send_content(page, "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def fields(self):
        length = self.headers.get("Content-Length", "0")
        if not length.isdecimal() or len(length) > 4 or int(length) > 4096:
            raise ValueError("Request is too large.")
        return parse_qs(self.rfile.read(int(length)).decode("utf-8"), max_num_fields=8)

    def do_POST(self):
        route = urlsplit(self.path)
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            self.send_error(403)
            return
        if route.path == "/api/reset":
            self.server.reset()
            self.json_response(status="reset", layout="v1")
            return
        if route.path not in {"/api/layout", "/orders/ship"}:
            self.send_error(404)
            return
        try:
            fields = self.fields()
        except ValueError:
            self.send_error(400)
            return
        if route.path == "/api/layout":
            layout = fields.get("layout", [""])[0]
            if layout not in {"v1", "v2"}:
                self.send_error(400, "Choose v1 or v2.")
                return
            with self.server.lock:
                self.server.layout = layout
            self.json_response(layout=layout)
            return
        order = fields.get("id", [""])[0]
        with self.server.lock, self.server.orders:
            result = self.server.orders.execute(
                "UPDATE orders SET status = 'Shipped' WHERE id = ?", (order,))
        if result.rowcount == 0:
            self.send_error(404, "Order not found.")
            return
        self.send_content("", "text/plain", status=303, Location="/")

    def order_row(self, order, customer, status, layout):
        key = escape(order, quote=True)
        action = ""
        if status == "Pending":
            action = (
                f'<form method="post" action="/orders/ship">'
                f'<input type="hidden" name="id" value="{key}">'
                f'<button id="{layout}-ship-{key}" class="{layout}-order-submit">Update Status</button></form>'
            )
            if layout == "v2":
                action = f'<details><summary>Actions</summary><details><summary>Fulfillment</summary>{action}</details></details>'
        return f"<tr><th scope='row'>{key}</th><td>{escape(customer)}</td><td>{escape(status)}</td><td>{action}</td></tr>"


PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Demo ERP · Orders</title><link rel="stylesheet" href="/style.css"></head>
<body><main><header><h1>Orders</h1><a href="/orders.csv" download>Export CSV</a></header>
<form method="get" action="/"><label for="q">Order ID or customer</label>
<input id="q" name="q" value="{query}"><button>Search</button></form>
<table><thead><tr><th>Order ID</th><th>Customer</th><th>Status</th><th>Actions</th></tr></thead>
<tbody>{rows}</tbody></table>
</main></body></html>"""

STYLE = """
body { margin: 0; background: #edf2f7; color: #142233; font: 17px system-ui, sans-serif; }
main { max-width: 920px; margin: 4rem auto; padding: 1.75rem; background: #fff; border-radius: 1rem; }
header { display: flex; align-items: center; justify-content: space-between; }
table { width: 100%; border-collapse: collapse; margin-top: 1.25rem; }
th, td { text-align: left; border-block-end: 1px solid #d5dee8; padding: .65rem; }
input, button { font: inherit; padding: .4rem .65rem; }
button, summary, a { cursor: pointer; } details details { margin-left: 1rem; }
.v2-order-submit { margin: .6rem 0 0 1rem; }
"""


def stop_server(signum, frame):
    raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_server)
    with ERP((os.environ.get("ERP_BIND", "127.0.0.1"), int(os.environ.get("ERP_PORT", "8080")))) as server:
        server.serve_forever()
