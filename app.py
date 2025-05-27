from flask import Flask, request, jsonify, send_file, send_from_directory
from datetime import datetime
import sqlite3
import os
import calendar
import requests
from dateutil import parser as date_parser
from io import BytesIO
from weasyprint import HTML

app = Flask(__name__, static_folder='static')

DB_PATH = os.environ.get("TIMESHEET_DB", "timesheet.db")
holiday_cache = {}
HOLIDAY_COUNTRY = os.environ.get("TIMESHEET_COUNTRY", "FR")

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory('static', path)

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS events (
            date TEXT PRIMARY KEY,
            status TEXT NOT NULL
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS locked_months (
            year INTEGER,
            month INTEGER,
            PRIMARY KEY (year, month)
        )''')

@app.route('/event', methods=['POST'])
def register_event():
    data = request.json
    day = data['date']
    status = data['status']

    with sqlite3.connect(DB_PATH) as conn:
        if status:
            conn.execute('REPLACE INTO events (date, status) VALUES (?, ?)', (day, status))
        else:
            conn.execute('DELETE FROM events WHERE date = ?', (day,))
        conn.commit()

    return jsonify({'success': True})

@app.route('/events')
def get_events():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute('SELECT date, status FROM events').fetchall()
    return jsonify([{'date': d, 'status': s} for d, s in rows])

@app.route('/lock', methods=['POST'])
def lock_month():
    data = request.json
    year, month = int(data['year']), int(data['month'])
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT OR IGNORE INTO locked_months (year, month) VALUES (?, ?)', (year, month))
    return jsonify({'locked': True})

@app.route('/unlock', methods=['POST'])
def unlock_month():
    data = request.json
    year, month = int(data['year']), int(data['month'])
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM locked_months WHERE year = ? AND month = ?', (year, month))
    return jsonify({'locked': False})

@app.route('/locked', methods=['GET'])
def is_month_locked():
    year = int(request.args.get('year'))
    month = int(request.args.get('month'))
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute('SELECT 1 FROM locked_months WHERE year = ? AND month = ?', (year, month)).fetchone()
    return jsonify({'locked': row is not None})

@app.route('/holidays')
def get_holidays():
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    if not start_date or not end_date:
        return jsonify([])

    try:
        start = date_parser.parse(start_date).date()
        end = date_parser.parse(end_date).date()
    except Exception:
        return jsonify([])

    years = set([start.year, end.year])
    all_holidays = []

    for year in years:
        year_str = str(year)
        if year_str not in holiday_cache:
            response = requests.get(f'https://date.nager.at/api/v3/PublicHolidays/{year}/{HOLIDAY_COUNTRY}')
            holiday_cache[year_str] = response.json() if response.status_code == 200 else []
        all_holidays.extend(holiday_cache[year_str])

    visible_holidays = [
        {'date': h['date'], 'name': h['localName']}
        for h in all_holidays
        if start <= date_parser.parse(h['date']).date() < end
    ]

    return jsonify(visible_holidays)

@app.route('/summary')
def get_summary():
    year = int(request.args.get('year'))
    month = int(request.args.get('month'))
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events WHERE status = 'work' AND strftime('%Y', date) = ? AND strftime('%m', date) = ?", (str(year), f'{month:02}'))
        count = cursor.fetchone()[0]
    return jsonify({'workdays': count})

@app.route('/export')
def export_pdf():
    user_title = os.environ.get("TIMESHEET_TITLE", "")
    year = int(request.args.get('year'))
    month = int(request.args.get('month'))

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT date, status FROM events")
        all_events = [
            (d, s) for d, s in cursor.fetchall()
            if datetime.strptime(d, '%Y-%m-%d').year == year and datetime.strptime(d, '%Y-%m-%d').month == month
        ]

    event_map = {d: s for d, s in all_events}

    if str(year) not in holiday_cache:
        response = requests.get(f'https://date.nager.at/api/v3/PublicHolidays/{year}/FR')
        holiday_cache[str(year)] = response.json() if response.status_code == 200 else []

    holiday_dates = set(h['date'] for h in holiday_cache[str(year)] if int(h['date'][5:7]) == month)

    weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    cal_matrix = calendar.monthcalendar(year, month)
    rows = ''
    for week in cal_matrix:
        rows += '<tr>'
        for i, day in enumerate(week):
            if day == 0:
                rows += '<td></td>'
                continue
            date_key = f"{year}-{month:02}-{day:02}"
            status = event_map.get(date_key, '')
            is_holiday = date_key in holiday_dates
            color = '#16a34a' if status == 'work' else '#dc2626' if status == 'absence' else 'transparent'
            bar = f'<div style="width: 6px; height: 1em; background-color: {color}; margin-right: 6px;"></div>' if color != 'transparent' else ''
            content = f'<div style="display: flex; align-items: flex-start;">{bar}<div><strong>{day}</strong><br>{status}</div></div>'
            bg = '#e5e7eb' if is_holiday else '#fef9c3' if i >= 5 else 'white'
            rows += f'<td style="background-color: {bg};">{content}</td>'
        rows += '</tr>'

    workdays = sum(1 for _, s in all_events if s == 'work')
    html = f"""
    <html>
    <head>
    <style>
    @page {{ size: A4 landscape; margin: 1cm; }}
    body {{ font-family: sans-serif; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td {{ width: 14.28%; border: 1px solid #ccc; vertical-align: top; padding: 5px; height: 100px; }}
    th {{ background-color: #f3f4f6; padding: 6px; }}
    .footer {{ margin-top: 20px; font-size: 1rem; }}
    </style>
    </head>
    <body>
    <h2>Timesheet Calendar{f' - {user_title}' if user_title else ''} – {year}-{month:02}</h2>
    <table>
      <thead><tr>{''.join(f'<th>{wd}</th>' for wd in weekdays)}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <div class='footer'><strong>Total work days:</strong> {workdays}</div>
    </body></html>
    """

    pdf = HTML(string=html).write_pdf()
    filename = f"timesheet_{user_title.strip().replace(' ', '_') + '_' if user_title else ''}{year}_{month:02}.pdf"
    return send_file(BytesIO(pdf), as_attachment=True, download_name=filename, mimetype='application/pdf')

@app.route('/health')
def health():
    return 'OK', 200

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8080)
