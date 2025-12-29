from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import requests
from datetime import datetime
from geopy.geocoders import Nominatim

app = Flask(__name__)
DB_NAME = "database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# Database Initialization
with get_db_connection() as conn:
    # Existing tables
    conn.execute("CREATE TABLE IF NOT EXISTS horses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS blankets (id INTEGER PRIMARY KEY AUTOINCREMENT, horse_id INTEGER NOT NULL, name TEXT NOT NULL, min_temp INTEGER, max_temp INTEGER, FOREIGN KEY (horse_id) REFERENCES horses (id) ON DELETE CASCADE)")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, address TEXT, hay INTEGER DEFAULT 0, shavings INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS medications (id INTEGER PRIMARY KEY AUTOINCREMENT, horse_id INTEGER NOT NULL, med_name TEXT NOT NULL, dose TEXT NOT NULL, schedule_time TEXT NOT NULL, FOREIGN KEY (horse_id) REFERENCES horses (id) ON DELETE CASCADE)")
    conn.execute("CREATE TABLE IF NOT EXISTS med_log (id INTEGER PRIMARY KEY AUTOINCREMENT, med_id INTEGER NOT NULL, horse_id INTEGER NOT NULL, admin_date DATE NOT NULL, admin_time TEXT NOT NULL)")

@app.route("/")
def main_page():
    conn = get_db_connection()
    settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    today = datetime.now().strftime('%Y-%m-%d')
    weather_info = None
    recommendations = []
    
    if settings and settings['address']:
        weather_info = get_weather_data(settings['address'])
        
    horses = conn.execute("SELECT * FROM horses").fetchall()
    horse_data = []
    
    for horse in horses:
        blankets = conn.execute("SELECT * FROM blankets WHERE horse_id = ?", (horse['id'],)).fetchall()

        if weather_info and (weather_info['total_precip'] > 0.05 or weather_info['max_code'] >= 51):
            rec = "Inside (Rain/Snow)"
        elif weather_info:
            found_blanket = "No blanket needed"
            chill = weather_info['min_chill']
            for b in blankets:
                if b['min_temp'] <= chill <= b['max_temp']:
                    found_blanket = b['name']
                    break
            rec = found_blanket
        else:
            rec = "Weather unavailable"
        recommendations.append({'name': horse['name'], 'recommendation': rec})
    
        # Get meds for this horse
        meds = conn.execute("SELECT * FROM medications WHERE horse_id = ?", (horse['id'],)).fetchall()
        
        # Check which meds were already given today
        given_today = conn.execute("SELECT med_id FROM med_log WHERE horse_id = ? AND admin_date = ?", 
                                   (horse['id'], today)).fetchall()
        given_ids = [row['med_id'] for row in given_today]
        
        horse_data.append({
            'info': horse,
            'meds': meds,
            'given_ids': given_ids
        })

    conn.close()
    return render_template("main.html", settings=settings, horse_data=horse_data, weather=weather_info, recs=recommendations) 

@app.route("/add_medication/<int:horse_id>", methods=["POST"])
def add_medication(horse_id):
    name = request.form["med_name"]
    dose = request.form["dose"]
    time = request.form["schedule_time"]
    conn = get_db_connection()
    conn.execute("INSERT INTO medications (horse_id, med_name, dose, schedule_time) VALUES (?, ?, ?, ?)",
                 (horse_id, name, dose, time))
    conn.commit()
    return redirect(url_for("configure_horses"))

@app.route("/log_medication/<int:med_id>/<int:horse_id>")
def log_medication(med_id, horse_id):
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    time = now.strftime('%H:%M')
    conn = get_db_connection()
    conn.execute("INSERT INTO med_log (med_id, horse_id, admin_date, admin_time) VALUES (?, ?, ?, ?)",
                 (med_id, horse_id, today, time))
    conn.commit()
    return redirect(url_for("main_page"))

@app.route("/history/<int:horse_id>")
def view_history(horse_id):
    conn = get_db_connection()
    horse = conn.execute("SELECT name FROM horses WHERE id = ?", (horse_id,)).fetchone()
    history = conn.execute("""
        SELECT ml.admin_date, ml.admin_time, m.med_name, m.dose 
        FROM med_log ml
        JOIN medications m ON ml.med_id = m.id
        WHERE ml.horse_id = ?
        ORDER BY ml.admin_date DESC, ml.admin_time DESC
    """, (horse_id,)).fetchall()
    conn.close()
    return render_template("history.html", horse=horse, history=history)

@app.route("/update_inventory/<item>/<int:delta>")
def update_inventory(item, delta):
    if item not in ['hay', 'shavings']: return redirect(url_for("main_page"))
    
    conn = get_db_connection()
    # Using MAX(0, ...) to prevent negative inventory
    conn.execute(f"UPDATE settings SET {item} = MAX(0, {item} + ?) WHERE id = 1", (delta,))
    conn.commit()
    conn.close()
    return redirect(url_for("main_page"))

@app.route("/set_inventory", methods=["POST"])
def set_inventory():
    hay_count = request.form.get("hay", type=int)
    shavings_count = request.form.get("shavings", type=int)
    
    conn = get_db_connection()
    if hay_count is not None:
        conn.execute("UPDATE settings SET hay = ? WHERE id = 1", (hay_count,))
    if shavings_count is not None:
        conn.execute("UPDATE settings SET shavings = ? WHERE id = 1", (shavings_count,))
    conn.commit()
    conn.close()
    return redirect(url_for("main_page"))

def get_weather_data(address):
    try:
        # 1. Geocode Address to Lat/Lon
        geolocator = Nominatim(user_agent="horse_blanket_app")
        location = geolocator.geocode(address)
        if not location: return None

        # 2. Call Open-Meteo API
        # We request temperature, wind chill (apparent_temperature), and precipitation
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "hourly": "temperature_2m,apparent_temperature,precipitation,weathercode",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "forecast_days": 1,
            "timezone": "auto"
        }
        response = requests.get(url, params=params).json()
        
        # Aggregate data for the next 24 hours
        hourly = response.get('hourly', {})
        return {
            "avg_temp": sum(hourly['temperature_2m']) / 24,
            "min_chill": min(hourly['apparent_temperature']),
            "total_precip": sum(hourly['precipitation']),
            "max_code": max(hourly['weathercode']) # Codes > 50 usually indicate rain/snow
        }
    except Exception as e:
        print(f"Error fetching weather: {e}")
        return None

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
    conn.execute("DELETE FROM medications WHERE horse_id = ?", (horse_id,))
    conn.execute("DELETE FROM med_log WHERE horse_id = ?", (horse_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("configure_horses"))

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)