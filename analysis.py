import pandas as pd
from pathlib import Path

DATA_FOLDER = Path("dataset")


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        return df

    out = df.copy()
    if out.index.name == "reservation_id":
        out = out.reset_index()
    elif "reservation_id" not in out.columns and "reservation_id" in out.index.names:
        out = out.reset_index(level="reservation_id")

    if isinstance(out.index, pd.MultiIndex) or out.index.name is not None:
        out = out.reset_index(drop=True)

    out.columns = [str(c).strip().lstrip("\ufeff") for c in out.columns]

    rename_map = {}
    existing_lower = {c.lower().replace(" ", "_"): c for c in out.columns}

    aliases = {
        "reservation_id": ["reservation_id", "booking_id", "id"],
        "guest_name": ["guest_name", "guest", "customer_name", "name"],
        "room_id": ["room_id", "room", "room_no", "room_number"],
        "room_category": ["room_category", "category", "room_type"],
        "check_in": ["check_in", "checkin", "check_in_date", "arrival", "arrival_date"],
        "check_out": ["check_out", "checkout", "check_out_date", "departure", "departure_date"],
        "booking_date": ["booking_date", "booked_date", "created_date"],
        "status": ["status", "booking_status", "reservation_status"],
        "cancellation_code": ["cancellation_code", "cancel_code", "cancel_reason_code"],
        "rate_plan_id": ["rate_plan_id", "rate_id", "plan_id"],
        "nightly_rate": ["nightly_rate", "rate", "rate_per_night", "price"],
    }

    for target, candidates in aliases.items():
        if target in out.columns:
            continue
        for cand in candidates:
            if cand in existing_lower:
                src = existing_lower[cand]
                if src != target and src not in rename_map:
                    rename_map[src] = target
                break

    if rename_map:
        out = out.rename(columns=rename_map)

    if "reservation_id" in out.columns:
        out["reservation_id"] = out["reservation_id"].astype(str).str.strip()

    return out


def load_datasets():
    data = {}

    files = {
        "reservations": "reservations.csv",
        "rooms": "rooms.csv",
        "rates": "rate_plans.csv",
        "cancellations": "cancellations.csv",
        "events": "calendar_events.csv"
    }

    for key, filename in files.items():
        path = DATA_FOLDER / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing file: {filename}")
        data[key] = pd.read_csv(path, sep=None, engine="python")

    data["reservations"] = _clean_df(data["reservations"])
    data["rooms"] = _clean_df(data["rooms"])
    data["rates"] = _clean_df(data["rates"])
    data["cancellations"] = _clean_df(data["cancellations"])
    data["events"] = _clean_df(data["events"])

    return data


def reconcile_reservations(data):
    df = _clean_df(data["reservations"])
    rooms = _clean_df(data["rooms"])
    rates = _clean_df(data["rates"])

    if "reservation_id" in df.columns:
        df = df.drop_duplicates(subset=["reservation_id"], keep="first").reset_index(drop=True)

    if "guest_name" not in df.columns:
        df["guest_name"] = ""

    if "status" not in df.columns:
        df["status"] = "confirmed"

    df["status"] = (
        df["status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    status_mapping = {
        "booked": "confirmed",
        "reserved": "confirmed",
        "in house": "checked_in",
        "checked in": "checked_in",
        "checked out": "checked_out",
        "completed": "checked_out",
        "cancel": "cancelled",
        "canceled": "cancelled",
        "noshow": "no_show"
    }
    df["status"] = df["status"].replace(status_mapping)

    for col in ["check_in", "check_out", "booking_date"]:
        if col not in df.columns:
            df[col] = pd.NaT
        df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    if "room_id" not in df.columns:
        df["room_id"] = ""
    if "room_id" not in rooms.columns:
        rooms["room_id"] = ""

    df["room_id"] = df["room_id"].astype(str).str.strip()
    rooms["room_id"] = rooms["room_id"].astype(str).str.strip()

    if "room_category" not in df.columns:
        df["room_category"] = pd.NA

    if not rooms.empty and {"room_id", "room_category"}.issubset(rooms.columns):
        df = df.merge(
            rooms[["room_id", "room_category"]].drop_duplicates("room_id"),
            on="room_id",
            how="left",
            suffixes=("", "_master")
        )
        df["room_category"] = df["room_category_master"].fillna(df["room_category"])
        df.drop(columns=["room_category_master"], inplace=True)

    if "nightly_rate" not in df.columns:
        df["nightly_rate"] = 0.0

    if (
        not rates.empty
        and "rate_plan_id" in df.columns
        and {"rate_plan_id", "nightly_rate"}.issubset(rates.columns)
    ):
        df["rate_plan_id"] = df["rate_plan_id"].astype(str).str.strip()
        rates["rate_plan_id"] = rates["rate_plan_id"].astype(str).str.strip()
        df = df.merge(
            rates[["rate_plan_id", "nightly_rate"]].drop_duplicates("rate_plan_id"),
            on="rate_plan_id",
            how="left",
            suffixes=("", "_rate")
        )
        if "nightly_rate_rate" in df.columns:
            df["nightly_rate"] = df["nightly_rate_rate"].fillna(df["nightly_rate"])
            df.drop(columns=["nightly_rate_rate"], inplace=True)

    df["nightly_rate"] = pd.to_numeric(df["nightly_rate"], errors="coerce").fillna(0)

    df["nights"] = (df["check_out"] - df["check_in"]).dt.days

    df["data_issue"] = ""

    invalid_dates = (
        df["check_in"].isna()
        | df["check_out"].isna()
        | (df["nights"] <= 0)
    )
    df.loc[invalid_dates, "data_issue"] = "Invalid booking dates"

    valid_rooms = set(rooms["room_id"]) - {""}
    if valid_rooms:
        invalid_rooms = ~df["room_id"].isin(valid_rooms)
        df.loc[invalid_rooms & (df["data_issue"] == ""), "data_issue"] = "Invalid room ID"

    df["estimated_revenue"] = df["nightly_rate"] * df["nights"].clip(lower=0)
    df.loc[df["status"].isin(["cancelled", "no_show"]), "estimated_revenue"] = 0

    df["overlap_flag"] = 0

    active = df[
        ~df["status"].isin(["cancelled", "no_show"])
        & df["check_in"].notna()
        & df["check_out"].notna()
        & (df["nights"] > 0)
    ].sort_values(["room_id", "check_in"])

    for _, group in active.groupby("room_id"):
        previous_end = None
        for idx, row in group.iterrows():
            if previous_end is not None and row["check_in"] < previous_end:
                df.loc[idx, "overlap_flag"] = 1
                if df.loc[idx, "data_issue"] == "":
                    df.loc[idx, "data_issue"] = "Overlapping booking"
            if previous_end is None or row["check_out"] > previous_end:
                previous_end = row["check_out"]

    return _clean_df(df)


def calculate_occupancy(df, rooms, start_date, end_date):
    df = _clean_df(df)
    if "check_in" not in df.columns:
        df["check_in"] = pd.NaT
    if "check_out" not in df.columns:
        df["check_out"] = pd.NaT
    if "nights" not in df.columns:
        df["nights"] = (pd.to_datetime(df["check_out"], errors="coerce") - pd.to_datetime(df["check_in"], errors="coerce")).dt.days

    total_rooms = len(rooms)
    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    results = []

    active = df[
        ~df["status"].isin(["cancelled", "no_show"])
        & df["check_in"].notna()
        & df["check_out"].notna()
        & (df["nights"] > 0)
    ]

    for date in dates:
        occupied = active[
            (active["check_in"] <= date)
            & (active["check_out"] > date)
        ]["room_id"].nunique()

        occupancy = (occupied / total_rooms * 100) if total_rooms > 0 else 0

        results.append({
            "Date": date,
            "Occupied Rooms": occupied,
            "Available Rooms": total_rooms,
            "Occupancy Rate": round(occupancy, 2)
        })

    return pd.DataFrame(results)


def calculate_summary(df, daily):
    df = _clean_df(df)
    total = len(df)
    cancelled = len(df[df["status"] == "cancelled"])
    revenue = df["estimated_revenue"].sum()
    cancellation_rate = (cancelled / total * 100) if total > 0 else 0
    occupancy_rate = daily["Occupancy Rate"].mean() if not daily.empty else 0
    overlaps = int(df["overlap_flag"].sum())
    issues = len(df[df["data_issue"] != ""])

    return {
        "total_reservations": total,
        "total_revenue": revenue,
        "occupancy_rate": occupancy_rate,
        "cancelled": cancelled,
        "cancellation_rate": cancellation_rate,
        "overlaps": overlaps,
        "data_issues": issues
    }


def revenue_by_category(df):
    df = _clean_df(df)
    if "room_category" not in df.columns:
        df["room_category"] = "Unknown"
    result = (
        df[~df["status"].isin(["cancelled", "no_show"])]
        .groupby("room_category")["estimated_revenue"]
        .sum()
        .reset_index()
    )
    return result


def cancellation_analysis(df):
    df = _clean_df(df)
    if "cancellation_code" not in df.columns:
        return pd.DataFrame(columns=["cancellation_code", "Total Cancellations"])

    cancelled = df[df["status"] == "cancelled"].copy()
    cancelled["cancellation_code"] = cancelled["cancellation_code"].fillna("UNKNOWN").astype(str).str.strip()
    cancelled.loc[cancelled["cancellation_code"] == "", "cancellation_code"] = "UNKNOWN"

    result = (
        cancelled.groupby("cancellation_code")
        .size()
        .reset_index(name="Total Cancellations")
    )
    return result
    
