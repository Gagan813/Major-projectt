import sqlite3

conn = sqlite3.connect("poultry.db")
c = conn.cursor()

# --- Patch 'transactions' table ---
try:
    c.execute("ALTER TABLE transactions ADD COLUMN total REAL DEFAULT 0")
    print("Added column 'total'")
except sqlite3.OperationalError:
    print("Column 'total' already exists")

try:
    c.execute("ALTER TABLE transactions ADD COLUMN profit REAL DEFAULT 0")
    print("Added column 'profit'")
except sqlite3.OperationalError:
    print("Column 'profit' already exists")

# --- Ensure 'dealers' table exists ---
c.execute("""
CREATE TABLE IF NOT EXISTS dealers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    website TEXT
)
""")
print("Ensured 'dealers' table exists")

conn.commit()
conn.close()
print("Database update complete!")