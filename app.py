import requests
from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from geopy.geocoders import Nominatim

app = Flask(__name__)
DB_NAME = "database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

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

@app.route("/")
def main_page():
    conn = get_db_connection()
    addr_row = conn.execute("SELECT address FROM settings WHERE id = 1").fetchone()
    address = addr_row['address'] if addr_row else None
    
    weather_info = None
    recommendations = []
    
    if address:
        weather_info = get_weather_data(address)
        if weather_info:
            horses = conn.execute("SELECT * FROM horses").fetchall()
            for horse in horses:
                blankets = conn.execute("SELECT * FROM blankets WHERE horse_id = ?", (horse['id'],)).fetchall()
                
                # Logic: If significant precipitation or snow codes (e.g., code 51+)
                if weather_info['total_precip'] > 0.05 or weather_info['max_code'] >= 51:
                    rec = "Stay Inside (Precipitation Expected)"
                else:
                    # Find blanket where wind chill is within range
                    found_blanket = "No blanket needed"
                    chill = weather_info['min_chill']
                    for b in blankets:
                        if b['min_temp'] <= chill <= b['max_temp']:
                            found_blanket = b['name']
                            break
                    rec = found_blanket
                
                recommendations.append({'name': horse['name'], 'recommendation': rec})

    conn.close()
    return render_template("main.html", address=address, weather=weather_info, recs=recommendations)

# ... (Include other routes: /configure_horses, /configure_address, /add_blanket from previous step)


# Database Initialization
with get_db_connection() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS horses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
    conn.execute("""CREATE TABLE IF NOT EXISTS blankets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, horse_id INTEGER NOT NULL,
                    name TEXT NOT NULL, min_temp INTEGER, max_temp INTEGER,
                    FOREIGN KEY (horse_id) REFERENCES horses (id) ON DELETE CASCADE)""")
    # Table to store address (using ID 1 for simplicity)
    conn.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, address TEXT)")

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