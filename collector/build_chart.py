import os
import sys

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv
import plotly.graph_objects as go

load_dotenv()

DSN = (
    f"host=localhost port=5433 "
    f"dbname={os.getenv('POSTGRES_DB')} "
    f"user={os.getenv('POSTGRES_USER')} "
    f"password={os.getenv('POSTGRES_PASSWORD')}"
)

COLORS = {
    "patch":        "#e74c3c",
    "season_start": "#9b59b6",
    "expansion":    "#f39c12",
    "marketing":    "#95a5a6",
    "beta":         "#3498db",
}


def fetch(app_id, min_reviews):
    with psycopg.connect(DSN, row_factory=dict_row) as conn:
        game = conn.execute(
            "select game_name from marts.dim_game_current where app_id = %s",
            (app_id,),
        ).fetchone()

        daily = conn.execute(
            """
            select created_date as day,
                   count(*) as total,
                   count(*) filter (where voted_up) as positive
            from marts.review_flat
            where app_id = %s
            group by 1
            having count(*) >= %s
            order by 1
            """,
            (app_id, min_reviews),
        ).fetchall()

        events = conn.execute(
            """
            select distinct published_date as day, event_type, title
            from marts.patch_impact
            where app_id = %s and window_code = 'after_7'
              and event_type in ('patch', 'season_start', 'expansion', 'marketing', 'beta')
            order by 1
            """,
            (app_id,),
        ).fetchall()

    return game["game_name"], daily, events


def build(game_name, daily, events):
    days = [r["day"] for r in daily]
    pct = [round(100 * r["positive"] / r["total"], 1) for r in daily]
    totals = [r["total"] for r in daily]

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=days, y=pct,
        mode="lines",
        name="Позитивных, %",
        line=dict(color="#2c3e50", width=2),
        customdata=totals,
        hovertemplate="%{x|%d.%m.%Y}<br>Позитив: %{y}%<br>Отзывов: %{customdata}<extra></extra>",
    ))

    # события группируем по дню, чтобы несколько в один день не наслаивались
    by_day = {}
    for e in events:
        by_day.setdefault(e["day"], []).append(e)

    for day, items in by_day.items():
        kind = items[0]["event_type"]
        color = COLORS.get(kind, "#7f8c8d")
        label = "<br>".join(f"[{i['event_type']}] {i['title'][:60]}" for i in items)

        fig.add_vline(x=day, line=dict(color=color, width=1, dash="dot"))
        fig.add_trace(go.Scatter(
            x=[day], y=[max(pct) if pct else 100],
            mode="markers",
            marker=dict(color=color, size=9, symbol="triangle-down"),
            showlegend=False,
            hovertemplate=f"%{{x|%d.%m.%Y}}<br>{label}<extra></extra>",
        ))

    fig.update_layout(
        title=f"{game_name} — настроение отзывов и события",
        xaxis_title=None,
        yaxis_title="Позитивных отзывов, %",
        hovermode="closest",
        template="plotly_white",
        height=600,
        xaxis=dict(rangeslider=dict(visible=True)),
    )

    return fig


def main():
    app_id = int(sys.argv[1]) if len(sys.argv) > 1 else 3065800
    min_reviews = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    game_name, daily, events = fetch(app_id, min_reviews)
    if not daily:
        raise SystemExit("нет данных")

    fig = build(game_name, daily, events)
    out = f"chart_{app_id}.html"
    fig.write_html(out)
    print(f"{game_name}: {len(daily)} дней, {len(events)} событий → {out}")


if __name__ == "__main__":
    main()