from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)
DB_NAME = "database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# Database Initialization
with get_db_connection() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS horses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
    conn.execute("""CREATE TABLE IF NOT EXISTS blankets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, horse_id INTEGER NOT NULL,
                    name TEXT NOT NULL, min_temp INTEGER, max_temp INTEGER,
                    FOREIGN KEY (horse_id) REFERENCES horses (id) ON DELETE CASCADE)""")
    # Table to store address (using ID 1 for simplicity)
    conn.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, address TEXT)")

@app.route("/")
def main_page():
    conn = get_db_connection()
    addr_row = conn.execute("SELECT address FROM settings WHERE id = 1").fetchone()
    address = addr_row['address'] if addr_row else "No address set"
    conn.close()
    return render_template("main.html", address=address)

@app.route("/configure_horses", methods=["GET", "POST"])
def configure_horses():
    conn = get_db_connection()
    if request.method == "POST":
        horse_name = request.form["horse_name"]
        if horse_name:
            conn.execute("INSERT INTO horses (name) VALUES (?)", (horse_name,))
            conn.commit()
        return redirect(url_for("configure_horses"))

    horses = conn.execute("SELECT * FROM horses").fetchall()
    horse_data = []
    for horse in horses:
        blankets = conn.execute("SELECT * FROM blankets WHERE horse_id = ?", (horse['id'],)).fetchall()
        horse_data.append({'horse': horse, 'blankets': blankets})
    conn.close()
    return render_template("configure_horses.html", horse_data=horse_data)

@app.route("/configure_address", methods=["GET", "POST"])
def configure_address():
    conn = get_db_connection()
    if request.method == "POST":
        new_address = request.form["address"]
        # Use INSERT OR REPLACE to always update the single address row
        conn.execute("INSERT OR REPLACE INTO settings (id, address) VALUES (1, ?)", (new_address,))
        conn.commit()
        return redirect(url_for("main_page"))
    
    addr_row = conn.execute("SELECT address FROM settings WHERE id = 1").fetchone()
    current_address = addr_row['address'] if addr_row else ""
    conn.close()
    return render_template("configure_address.html", current_address=current_address)

@app.route("/add_blanket/<int:horse_id>", methods=["POST"])
def add_blanket(horse_id):
    name, min_t, max_t = request.form["blanket_name"], request.form["min_temp"], request.form["max_temp"]
    conn = get_db_connection()
    conn.execute("INSERT INTO blankets (horse_id, name, min_temp, max_temp) VALUES (?, ?, ?, ?)", (horse_id, name, min_t, max_t))
    conn.commit()
    conn.close()
    return redirect(url_for("configure_horses"))

@app.route("/delete_horse/<int:horse_id>")
def delete_horse(horse_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM horses WHERE id = ?", (horse_id,))
    conn.execute("DELETE FROM blankets WHERE horse_id = ?", (horse_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("configure_horses"))

if __name__ == "__main__":
    app.run(debug=True)