import streamlit as st
import pandas as pd
import sqlite3
import altair as alt
from datetime import date

# --- CONFIGURATION ---
DB_FILE = "/data/weight.db"
st.set_page_config(
    page_title="Weight Tracker",
    page_icon="⚖️",
    layout="centered",
    initial_sidebar_state="expanded"
)

# --- DATABASE FUNCTIONS ---
def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS log (
            Date TEXT PRIMARY KEY,
            Weight REAL
        )
    ''')
    conn.commit()
    conn.close()

# Initialize DB on startup
init_db()

# --- FETCH DATA ---
conn = get_connection()
df = pd.read_sql("SELECT * FROM log ORDER BY Date ASC", conn)

if not df.empty:
    # Clean Data: Convert to Date/Numeric and drop junk
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df['Weight'] = pd.to_numeric(df['Weight'], errors='coerce')
    df = df.dropna(subset=['Date', 'Weight'])
    df = df[df['Weight'] > 0]
    
    # Recalculate Trend (EMA)
    df['Trend'] = df['Weight'].ewm(alpha=0.1, adjust=False).mean()

# --- SIDEBAR (GOALS & INPUT) ---
with st.sidebar:
    st.header("🎯 Goals")
    # We define this HERE so it can be used in the dashboard below
    goal_weight = st.number_input("Target Weight (kg)", value=75.0, step=0.5)
    
    st.divider()
    
    st.header("📝 Log Entry")
    with st.form("entry_form", clear_on_submit=True):
        d = st.date_input("Date", date.today())
        w = st.number_input("Weight (kg)", step=0.1, format="%.1f")
        submitted = st.form_submit_button("Save Weight")

    if submitted:
        try:
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO log (Date, Weight) VALUES (?, ?)", (str(d), w))
            conn.commit()
            st.success(f"Saved {w}kg for {d}")
            st.rerun()
        except Exception as e:
            st.error(f"Error saving to DB: {e}")

# --- DASHBOARD METRICS ---
st.title("⚖️ Daily Tracker")

if not df.empty:
    latest = df.iloc[-1]
    
    # 1. SMART LOOKBACK: Find a data point from ~7 entries ago
    lookback_idx = -7 if len(df) >= 7 else 0
    past_data = df.iloc[lookback_idx]
    
    # 2. TIME NORMALIZATION: Calculate actual days passed
    days_diff = (latest['Date'] - past_data['Date']).days
    trend_diff = latest['Trend'] - past_data['Trend']
    
    # 3. Calculate True Weekly Speed
    if days_diff > 0:
        true_weekly_rate = (trend_diff / days_diff) * 7
    else:
        true_weekly_rate = 0

    # Layout: 3 Columns
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Calculate absolute weight change vs 7 entries ago
        weight_change = latest['Weight'] - past_data['Weight']
        
        # Create a label that explains the timeline
        # e.g. "-1.2 kg (7 days)"
        delta_label = f"{weight_change:.1f} kg over past {days_diff} days"

        st.metric(
            "Current Weight", 
            f"{latest['Weight']} kg", 
            delta=delta_label,
            delta_color="inverse"
        )
    with col2:
            # We remove the 'delta' parameter entirely to avoid the confusing arrows.
            # We just show the current speed clearly.
            st.metric(
                label="Wkly Speed", 
                value=f"{true_weekly_rate:.2f} kg", 
                help=f"Calculated over the last {days_diff} days"
            )
            
    with col3:
        # PROJECTION LOGIC
        if true_weekly_rate < -0.05 and latest['Trend'] > goal_weight:
            remaining = latest['Trend'] - goal_weight
            weeks_to_go = remaining / abs(true_weekly_rate)
            days_to_go = weeks_to_go * 7
            
            arrival_date = date.today() + pd.Timedelta(days=days_to_go)
            
            st.metric(
                "Est.   val", 
                arrival_date.strftime("%b %d"), 
                f"{weeks_to_go:.1f} weeks",
                delta_color="inverse"
            )
        elif latest['Trend'] <= goal_weight:
            st.metric("Status", "Goal Reached!", "Congrats!", delta_color="normal")
        else:
            st.metric("Status", "Stalled", "No Trend", delta_color="off")
    
    st.divider()

    # --- ALTAIR CHART ---
    st.write("### Progress")
    base = alt.Chart(df).encode(x='Date:T')
    
    points = base.mark_circle(size=60, color="#6c757d").encode(
        y=alt.Y('Weight', scale=alt.Scale(zero=False), title='Weight'),
        tooltip=['Date', 'Weight']
    )
    
    line = base.mark_line(color="#ff4b4b", strokeWidth=3).encode(y='Trend')
    
    st.altair_chart((points + line).interactive(), use_container_width=True)