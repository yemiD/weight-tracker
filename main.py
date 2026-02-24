import os
from datetime import date, timedelta

import pandas as pd
import sqlite3
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

DB_FILE = os.environ.get("DB_FILE", "weight.db")

app = FastAPI()
templates = Jinja2Templates(directory="templates")


# --- DATABASE ---

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True) if os.path.dirname(DB_FILE) else None
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS log (
            Date TEXT PRIMARY KEY,
            Weight REAL
        )
    """)
    conn.commit()
    conn.close()


init_db()


# --- BUSINESS LOGIC ---

def get_data() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM log ORDER BY Date ASC", conn)
    conn.close()
    if df.empty:
        return df
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Weight"] = pd.to_numeric(df["Weight"], errors="coerce")
    df = df.dropna(subset=["Date", "Weight"])
    df = df[df["Weight"] > 0]
    df["Trend"] = df["Weight"].ewm(alpha=0.1, adjust=False).mean()
    return df


def compute_metrics(goal_weight: float) -> dict | None:
    df = get_data()
    if df.empty:
        return None

    latest = df.iloc[-1]
    lookback_idx = -7 if len(df) >= 7 else 0
    past = df.iloc[lookback_idx]

    days_diff = (latest["Date"] - past["Date"]).days
    true_weekly_rate = ((latest["Trend"] - past["Trend"]) / days_diff * 7) if days_diff > 0 else 0
    weight_change = latest["Weight"] - past["Weight"]

    projection = None
    projection_status = None

    if latest["Trend"] <= goal_weight:
        projection_status = "reached"
    elif true_weekly_rate < -0.05 and latest["Trend"] > goal_weight:
        remaining = latest["Trend"] - goal_weight
        weeks_to_go = remaining / abs(true_weekly_rate)
        arrival = date.today() + timedelta(days=weeks_to_go * 7)
        projection = {"date": arrival.strftime("%b %d"), "weeks": round(weeks_to_go, 1)}
    else:
        projection_status = "stalled"

    return {
        "current_weight": latest["Weight"],
        "weight_change": weight_change,
        "days_diff": days_diff,
        "true_weekly_rate": true_weekly_rate,
        "projection": projection,
        "projection_status": projection_status,
    }


# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, goal: float = 75.0):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "metrics": compute_metrics(goal),
        "goal": goal,
        "today": date.today().isoformat(),
    })


@app.get("/metrics", response_class=HTMLResponse)
async def get_metrics(request: Request, goal: float = 75.0):
    return templates.TemplateResponse("partials/metrics.html", {
        "request": request,
        "metrics": compute_metrics(goal),
    })


@app.post("/log", response_class=HTMLResponse)
async def log_entry(
    request: Request,
    date: str = Form(...),
    weight: float = Form(...),
    goal: float = Form(75.0),
):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO log (Date, Weight) VALUES (?, ?)", (date, weight))
    conn.commit()
    conn.close()

    response = templates.TemplateResponse("partials/metrics.html", {
        "request": request,
        "metrics": compute_metrics(goal),
    })
    response.headers["HX-Trigger"] = "chartRefresh"
    return response


@app.get("/api/data")
async def api_data():
    df = get_data()
    if df.empty:
        return {"dates": [], "weights": [], "trend": []}
    return {
        "dates": df["Date"].dt.strftime("%Y-%m-%d").tolist(),
        "weights": df["Weight"].tolist(),
        "trend": df["Trend"].round(2).tolist(),
    }
