from flask import Flask, jsonify, render_template, Response, request, redirect, url_for, send_file
import random
import datetime
import sqlite3
import threading
import time
import re
import io
from openpyxl import Workbook

app = Flask(__name__)

# -------------------- DATABASE --------------------
def db():
    return sqlite3.connect("poultry.db", check_same_thread=False)

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            temperature REAL,
            humidity REAL,
            ammonia INTEGER,
            light INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sku TEXT,
            category TEXT,
            unit TEXT,
            unit_factor REAL DEFAULT 1,
            quantity REAL DEFAULT 0,
            reorder_level REAL DEFAULT 0,
            target_level REAL DEFAULT 0,
            avg_cost REAL DEFAULT 0,
            last_updated TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            item_id INTEGER,
            type TEXT,
            quantity REAL,
            unit_price REAL,
            total REAL DEFAULT 0,
            profit REAL DEFAULT 0,
            party TEXT,
            note TEXT,
            FOREIGN KEY(item_id) REFERENCES inventory(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS dealers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            website TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

# -------------------- AUTOMATIC SENSOR DATA --------------------
def save_reading(data):
    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO readings (timestamp, temperature, humidity, ammonia, light)
        VALUES (?, ?, ?, ?, ?)
    """, (data["timestamp"], data["temperature"], data["humidity"], data["ammonia"], data["light"]))
    conn.commit()
    conn.close()

def make_reading():
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "temperature": round(random.uniform(25, 35), 1),
        "humidity": round(random.uniform(50, 80), 1),
        "ammonia": random.randint(200, 400),
        "light": random.randint(300, 800)
    }

def auto_generate_data():
    while True:
        data = make_reading()
        save_reading(data)
        time.sleep(5)

# -------------------- DASHBOARD --------------------
@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/latest")
def latest():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT timestamp, temperature, humidity, ammonia, light FROM readings ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "No data available"}), 404

    latest = {"timestamp": row[0], "temperature": row[1], "humidity": row[2], "ammonia": row[3], "light": row[4]}
    alerts = []
    if latest["temperature"] > 32:
        alerts.append(f"🔥 High Temperature Alert: {latest['temperature']} °C")
    if latest["humidity"] > 80:
        alerts.append(f"💧 High Humidity Alert: {latest['humidity']} %")
    if latest["ammonia"] > 350:
        alerts.append(f"☠️ High Ammonia Alert: {latest['ammonia']} ppm")
    return jsonify({**latest, "alerts": alerts})

@app.route("/api/history")
def history():
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT timestamp, temperature, humidity, ammonia, light
        FROM (
            SELECT timestamp, temperature, humidity, ammonia, light, id
            FROM readings
            ORDER BY id DESC
            LIMIT 50
        )
        ORDER BY id ASC
    """)
    rows = c.fetchall()
    conn.close()
    history_data = [
        {"timestamp": r[0], "temperature": r[1], "humidity": r[2], "ammonia": r[3], "light": r[4]}
        for r in rows
    ]
    return jsonify(history_data)

# -------------------- ERP HELPERS --------------------
def slugify(s):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s.upper()

def suggest_sku(name):
    base = slugify(name)[:8] or "ITEM"
    conn = db()
    c = conn.cursor()
    like = f"{base}%"
    c.execute("SELECT sku FROM inventory WHERE sku LIKE ? ORDER BY sku DESC LIMIT 1", (like,))
    row = c.fetchone()
    conn.close()
    if not row:
        return f"{base}-001"
    m = re.search(r"(\d+)$", row[0] or "")
    n = int(m.group(1)) + 1 if m else 1
    return f"{base}-{n:03d}"

def get_item(item_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id,name,sku,category,unit,unit_factor,quantity,reorder_level,target_level,avg_cost,last_updated FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    conn.close()
    return row

def set_item_qty_cost(item_id, new_qty, new_avg_cost):
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE inventory SET quantity=?, avg_cost=?, last_updated=? WHERE id=?",
              (new_qty, new_avg_cost, datetime.datetime.now().isoformat(), item_id))
    conn.commit()
    conn.close()

def record_tx(item_id, tx_type, qty, unit_price, profit, party, note):
    conn = db()
    c = conn.cursor()
    total = (qty or 0) * (unit_price or 0)
    c.execute("""
        INSERT INTO transactions (timestamp, item_id, type, quantity, unit_price, total, profit, party, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (datetime.datetime.now().isoformat(), item_id, tx_type, qty, unit_price, total, profit, party, note))
    conn.commit()
    conn.close()

# -------------------- ERP HOME --------------------
@app.route("/erp", methods=["GET"])
def erp_home():
    q = (request.args.get("q") or "").strip()
    conn = db()
    c = conn.cursor()
    if q:
        like = f"%{q}%"
        c.execute("""
            SELECT id,name,sku,category,unit,unit_factor,quantity,reorder_level,target_level,avg_cost,last_updated
            FROM inventory
            WHERE name LIKE ? OR sku LIKE ? OR category LIKE ?
            ORDER BY name COLLATE NOCASE
        """, (like, like, like))
    else:
        c.execute("""
            SELECT id,name,sku,category,unit,unit_factor,quantity,reorder_level,target_level,avg_cost,last_updated
            FROM inventory
            ORDER BY name COLLATE NOCASE
        """)
    items = c.fetchall()

    total_items = len(items)
    low_stock = sum(1 for r in items if (r[6] or 0) <= (r[7] or 0))
    inv_value = sum((r[6] or 0) * (r[9] or 0) for r in items)

    c.execute("""
        SELECT t.id, t.timestamp, i.name, i.sku, t.type, t.quantity, t.unit_price, t.total, t.profit, t.party, t.note
        FROM transactions t
        LEFT JOIN inventory i ON i.id = t.item_id
        ORDER BY t.id DESC
        LIMIT 50
    """)
    last_tx = c.fetchall()
    conn.close()

    return render_template("erp.html",
                           items=items,
                           total_items=total_items,
                           low_stock=low_stock,
                           inv_value=inv_value,
                           last_tx=last_tx,
                           query=q)

# -------------------- DEALERS --------------------
@app.route('/erp/order')
def erp_order_page():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, name, phone, website FROM dealers ORDER BY name COLLATE NOCASE")
    dealers = [{"id": r[0], "name": r[1], "phone": r[2], "website": r[3]} for r in c.fetchall()]
    conn.close()
    return render_template("order.html", dealers=dealers)

@app.route('/erp/dealer/add', methods=['POST'])
def add_dealer():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    website = request.form.get("website", "").strip()
    if name:
        conn = db()
        c = conn.cursor()
        c.execute("INSERT INTO dealers (name, phone, website) VALUES (?, ?, ?)", (name, phone, website))
        conn.commit()
        conn.close()
    return redirect(url_for('erp_order_page'))

@app.route('/erp/dealer/edit/<int:id>', methods=['POST'])
def edit_dealer(id):
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    website = request.form.get("website", "").strip()
    conn = db()
    c = conn.cursor()
    c.execute("UPDATE dealers SET name=?, phone=?, website=? WHERE id=?", (name, phone, website, id))
    conn.commit()
    conn.close()
    return redirect(url_for('erp_order_page'))

@app.route('/erp/dealer/delete/<int:dealer_id>', methods=['POST'])
def delete_dealer(dealer_id):
    conn = db()
    c = conn.cursor()
    c.execute("DELETE FROM dealers WHERE id=?", (dealer_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('erp_order_page'))

# -------------------- EXPORT EXCEL --------------------
@app.route("/erp/inventory/export_excel")
def erp_inventory_export_excel():
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT id,name,sku,category,unit,unit_factor,quantity,reorder_level,target_level,avg_cost,last_updated
        FROM inventory ORDER BY name COLLATE NOCASE
    """)
    rows = c.fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"
    ws.append(["ID","Name","Item Code","Category","Unit","Unit Factor","Qty","Reorder Level","Target Level","Avg Cost","Value","Last Updated"])

    for r in rows:
        qty = r[6] or 0
        avg = r[9] or 0
        value = qty * avg
        ws.append([r[0], r[1], r[2] or "", r[3] or "", r[4] or "", r[5] or 1,
                   round(qty,4), round((r[7] or 0),4), round((r[8] or 0),4),
                   round(avg,2), round(value,2), r[10] or ""])

    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    return send_file(file_stream,
                     download_name="inventory.xlsx",
                     as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/erp/transactions/export_excel")
def erp_tx_export_excel():
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT t.id, t.timestamp, i.name, i.sku, t.type, t.quantity, t.unit_price, t.total, t.profit, t.party, t.note
        FROM transactions t
        LEFT JOIN inventory i ON i.id = t.item_id
        ORDER BY t.id DESC
    """)
    rows = c.fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(["ID","Time","Item","Item Code","Type","Qty","Unit Price","Total","Profit","Party","Note"])

    for r in rows:
        ws.append([r[0], r[1], r[2], r[3] or "", r[4],
                   round((r[5] or 0),4), round((r[6] or 0),2), round((r[7] or 0),2),
                   round((r[8] or 0),2), r[9] or "", r[10] or ""])

    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    return send_file(file_stream,
                     download_name="transactions.xlsx",
                     as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# -------------------- ERP ITEM ROUTES --------------------
@app.route("/erp/inventory/add", methods=["POST"])
def erp_inventory_add():
    name = request.form.get("name").strip()
    sku = request.form.get("sku") or suggest_sku(name)
    category = request.form.get("category")
    unit = request.form.get("unit")
    unit_factor = float(request.form.get("unit_factor") or 1)
    quantity = float(request.form.get("quantity") or 0)
    avg_cost = float(request.form.get("avg_cost") or 0)
    reorder_level = float(request.form.get("reorder_level") or 0)
    target_level = float(request.form.get("target_level") or 0)

    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO inventory
        (name, sku, category, unit, unit_factor, quantity, avg_cost, reorder_level, target_level, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, sku, category, unit, unit_factor, quantity, avg_cost, reorder_level, target_level, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return redirect(url_for("erp_home"))

@app.route("/erp/inventory/edit/<int:item_id>", methods=["POST"])
def erp_inventory_edit(item_id):
    name = request.form.get("name").strip()
    sku = request.form.get("sku")
    category = request.form.get("category")
    unit = request.form.get("unit")
    unit_factor = float(request.form.get("unit_factor") or 1)
    reorder_level = float(request.form.get("reorder_level") or 0)
    target_level = float(request.form.get("target_level") or 0)
    avg_cost = float(request.form.get("avg_cost") or 0)

    conn = db()
    c = conn.cursor()
    c.execute("""
        UPDATE inventory
        SET name=?, sku=?, category=?, unit=?, unit_factor=?, reorder_level=?, target_level=?, avg_cost=?, last_updated=?
        WHERE id=?
    """, (name, sku, category, unit, unit_factor, reorder_level, target_level, avg_cost, datetime.datetime.now().isoformat(), item_id))
    conn.commit()
    conn.close()
    return redirect(url_for("erp_home"))

@app.route("/erp/inventory/delete/<int:item_id>", methods=["POST"])
def erp_inventory_delete(item_id):
    conn = db()
    c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("erp_home"))

@app.route("/erp/inventory/increase/<int:item_id>", methods=["POST"])
def erp_inventory_increase(item_id):
    delta = float(request.form.get("delta") or 0)
    price = float(request.form.get("unit_price") or 0)
    item = get_item(item_id)
    if item:
        new_qty = (item[6] or 0) + delta
        new_avg = ((item[6] or 0)*(item[9] or 0) + delta*price)/max(new_qty,1)
        set_item_qty_cost(item_id, new_qty, new_avg)
        record_tx(item_id, "purchase", delta, price, 0, request.form.get("party"), request.form.get("note"))
    return redirect(url_for("erp_home"))

@app.route("/erp/inventory/decrease/<int:item_id>", methods=["POST"])
def erp_inventory_decrease(item_id):
    delta = float(request.form.get("delta") or 0)
    price = float(request.form.get("unit_price") or 0)
    item = get_item(item_id)
    if item:
        new_qty = max((item[6] or 0) - delta, 0)
        profit = delta * ((price or 0) - (item[9] or 0))
        set_item_qty_cost(item_id, new_qty, item[9] or 0)
        record_tx(item_id, "sale", delta, price, profit, request.form.get("party"), request.form.get("note"))
    return redirect(url_for("erp_home"))

@app.route("/erp/transactions/add", methods=["POST"])
def erp_tx_add():
    item_id = int(request.form.get("item_id"))
    tx_type = request.form.get("type")
    qty = float(request.form.get("quantity") or 0)
    unit_price = float(request.form.get("unit_price") or 0)
    party = request.form.get("party")
    note = request.form.get("note")

    item = get_item(item_id)
    if item:
        if tx_type=="purchase":
            new_qty = (item[6] or 0) + qty
            new_avg = ((item[6] or 0)*(item[9] or 0) + qty*unit_price)/max(new_qty,1)
            set_item_qty_cost(item_id, new_qty, new_avg)
            profit = 0
        elif tx_type=="sale":
            new_qty = max((item[6] or 0) - qty, 0)
            profit = qty * (unit_price - (item[9] or 0))
            set_item_qty_cost(item_id, new_qty, item[9] or 0)
        else:  # adjustment
            new_qty = (item[6] or 0) + qty
            profit = 0
            set_item_qty_cost(item_id, new_qty, item[9] or 0)
        record_tx(item_id, tx_type, qty, unit_price, profit, party, note)
    return redirect(url_for("erp_home"))

# -------------------- START AUTO THREAD --------------------
threading.Thread(target=auto_generate_data, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)