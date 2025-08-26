import sqlite3

conn = sqlite3.connect("poultry.db")
c = conn.cursor()

# Add 'total' column if it doesn't exist
try:
    c.execute("ALTER TABLE transactions ADD COLUMN total REAL DEFAULT 0")
    print("Added column 'total'")
except sqlite3.OperationalError:
    print("Column 'total' already exists")

# Add 'profit' column if it doesn't exist
try:
    c.execute("ALTER TABLE transactions ADD COLUMN profit REAL DEFAULT 0")
    print("Added column 'profit'")
except sqlite3.OperationalError:
    print("Column 'profit' already exists")

conn.commit()
conn.close()
print("Database update complete!")