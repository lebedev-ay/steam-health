import os

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request

load_dotenv()

DSN = (
    f"host=localhost port=5433 "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)

app = Flask(__name__)


def query(sql, params=()):
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


@app.route("/")
def index():
    games = query("""
        select app_id, game_name
        from marts.dim_game_current
        order by game_name
    """)
    return render_template("index.html", games=games)


@app.route("/api/data")
def data():
    app_id = int(request.args.get("app_id"))
    smoothing = request.args.get("smoothing", "auto")

    raw_daily = query("""
        select created_date as day,
               count(*) as total,
               count(*) filter (where voted_up) as positive
        from marts.review_flat
        where app_id = %s
        group by 1
        order by 1
    """, (app_id,))

    if not raw_daily:
        return jsonify({"daily": [], "events": [], "window": 0})

    # ширина окна: обратно пропорциональна медианному объёму
    volumes = sorted(r["total"] for r in raw_daily)
    median = volumes[len(volumes) // 2]

    if smoothing == "off":
        half = 0
    elif smoothing == "auto":
        if median >= 100:
            half = 1      # окно 3 дня
        elif median >= 30:
            half = 3      # окно 7 дней
        elif median >= 10:
            half = 7      # окно 15 дней
        else:
            half = 14     # окно 29 дней
    else:
        half = int(smoothing) // 2

    smoothed = []
    for i, row in enumerate(raw_daily):
        lo = max(0, i - half)
        hi = min(len(raw_daily), i + half + 1)
        window = raw_daily[lo:hi]

        pos = sum(w["positive"] for w in window)
        tot = sum(w["total"] for w in window)

        smoothed.append({
            "day": row["day"].isoformat(),
            "total": row["total"],
            "pct": round(100 * pos / tot, 1) if tot else None,
            "window_n": tot,
        })

    events = query("""
        select distinct published_date as day, event_type, title
        from marts.patch_impact
        where app_id = %s and window_code = 'after_7'
          and event_type in ('patch','season_start','expansion','marketing','beta')
        order by 1
    """, (app_id,))

    return jsonify({
        "daily": smoothed,
        "window": half * 2 + 1,
        "median_volume": median,
        "events": [
            {"day": r["day"].isoformat(), "type": r["event_type"], "title": r["title"]}
            for r in events
        ],
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)