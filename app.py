from flask import Flask, jsonify, render_template, Response, request
import random
import datetime
import sqlite3
import csv
import io
import threading
import time

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect("poultry.db")
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
            category TEXT,
            quantity REAL DEFAULT 0,
            unit TEXT,
            reorder_level REAL DEFAULT 0,
            last_updated TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def save_reading(data):
    conn = sqlite3.connect("poultry.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO readings (timestamp, temperature, humidity, ammonia, light)
        VALUES (?, ?, ?, ?, ?)
    """, (data["timestamp"], data["temperature"], data["humidity"],
          data["ammonia"], data["light"]))
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

@app.route("/api/latest")
def latest():
    conn = sqlite3.connect("poultry.db")
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
    conn = sqlite3.connect("poultry.db")
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

@app.route("/download_csv")
def download_csv():
    conn = sqlite3.connect("poultry.db")
    c = conn.cursor()
    c.execute("SELECT timestamp, temperature, humidity, ammonia, light FROM readings ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Timestamp", "Temperature (°C)", "Humidity (%)", "Ammonia (ppm)", "Light (lux)"])
        yield buffer.getvalue()
        buffer.seek(0); buffer.truncate(0)
        for row in rows:
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0); buffer.truncate(0)

    return Response(generate(),
                    mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=poultry_data.csv"})

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/erp")
def erp_home():
    conn = sqlite3.connect("poultry.db")
    c = conn.cursor()
    c.execute("SELECT id, name, category, quantity, unit, reorder_level, last_updated FROM inventory")
    rows = c.fetchall()
    conn.close()

    low_stock = sum(1 for r in rows if r[3] <= r[5])
    return render_template("erp.html", inventory=rows, low_stock=low_stock)

@app.route("/erp/inventory/add", methods=["POST"])
def erp_add():
    name = request.form.get("name")
    category = request.form.get("category")
    quantity = float(request.form.get("quantity") or 0)
    unit = request.form.get("unit")
    reorder_level = float(request.form.get("reorder_level") or 0)
    timestamp = datetime.datetime.now().isoformat()

    conn = sqlite3.connect("poultry.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO inventory (name, category, quantity, unit, reorder_level, last_updated)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, category, quantity, unit, reorder_level, timestamp))
    conn.commit()
    conn.close()

    return "Item added successfully! <a href='/erp'>Go back</a>"

@app.route("/erp/inventory/delete/<int:item_id>", methods=["POST"])
def erp_delete(item_id):
    conn = sqlite3.connect("poultry.db")
    c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return "Deleted! <a href='/erp'>Go back</a>"

@app.route("/erp/inventory/increase/<int:item_id>", methods=["POST"])
def erp_increase(item_id):
    delta = float(request.form.get("delta") or 0)
    conn = sqlite3.connect("poultry.db")
    c = conn.cursor()
    c.execute("UPDATE inventory SET quantity = quantity + ?, last_updated = ? WHERE id=?",
              (delta, datetime.datetime.now().isoformat(), item_id))
    conn.commit()
    conn.close()
    return "Quantity updated! <a href='/erp'>Go back</a>"

@app.route("/erp/inventory/decrease/<int:item_id>", methods=["POST"])
def erp_decrease(item_id):
    delta = float(request.form.get("delta") or 0)
    conn = sqlite3.connect("poultry.db")
    c = conn.cursor()
    c.execute("UPDATE inventory SET quantity = quantity - ?, last_updated = ? WHERE id=?",
              (delta, datetime.datetime.now().isoformat(), item_id))
    conn.commit()
    conn.close()
    return "Quantity updated! <a href='/erp'>Go back</a>"

if __name__ == "__main__":
    threading.Thread(target=auto_generate_data, daemon=True).start()
    app.run(debug=True)