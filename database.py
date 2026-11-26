
import sqlite3
import pandas as pd

DB_NAME = "hotel_analysis.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def initialize_database():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            reservation_id TEXT PRIMARY KEY,
            guest_name TEXT,
            room_id TEXT,
            room_category TEXT,
            check_in TEXT,
            check_out TEXT,
            status TEXT,
            estimated_revenue REAL,
            overlap_flag INTEGER,
            data_issue TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_processed_data(df):
    conn = get_connection()

    columns = [
        "reservation_id",
        "guest_name",
        "room_id",
        "room_category",
        "check_in",
        "check_out",
        "status",
        "estimated_revenue",
        "overlap_flag",
        "data_issue"
    ]

    df[columns].to_sql(
        "reservations",
        conn,
        if_exists="replace",
        index=False
    )

    conn.close()


def load_saved_data():
    conn = get_connection()

    try:
        df = pd.read_sql_query(
            "SELECT * FROM reservations",
            conn
        )
    except Exception:
        df = pd.DataFrame()

    conn.close()
    return df
