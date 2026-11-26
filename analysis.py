import pandas as pd
from pathlib import Path

DATA_FOLDER = Path("dataset")


def _normalize_reservation_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure reservation_id is a standard column rather than an index."""
    if not isinstance(df, pd.DataFrame):
        return df

    out = df.copy()

    if out.index.name == "reservation_id":
        out = out.reset_index()
    elif "reservation_id" not in out.columns and "reservation_id" in out.index.names:
        out = out.reset_index(level="reservation_id")

    # Reset generic or leftover index so .loc[index, ...] always aligns cleanly
    if isinstance(out.index, pd.MultiIndex) or out.index.name is not None:
        out = out.reset_index(drop=True)

    if "reservation_id" in out.columns:
        out["reservation_id"] = out["reservation_id"].astype(str).str.strip()

    return out


# Load all hotel datasets
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

        data[key] = pd.read_csv(path)

    data["reservations"] = _normalize_reservation_df(data["reservations"])

    return data


# Clean and reconcile reservation records
def reconcile_reservations(data):

    df = _normalize_reservation_df(data["reservations"])

    rooms = data["rooms"].copy()
    rates = data["rates"].copy()

    # Remove duplicate reservation IDs
    if "reservation_id" in df.columns:
        df = df.drop_duplicates(
            subset=["reservation_id"],
            keep="first"
        ).reset_index(drop=True)

    # Standardize status
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

    # Convert date columns
    for col in ["check_in", "check_out", "booking_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(
                df[col],
                errors="coerce"
            )

    # Standardize IDs
    df["room_id"] = df["room_id"].astype(str).str.strip()
    rooms["room_id"] = rooms["room_id"].astype(str).str.strip()

    # Merge room information
    df = df.merge(
        rooms[["room_id", "room_category"]],
        on="room_id",
        how="left",
        suffixes=("", "_master")
    )

    if "room_category_master" in df.columns:
        if "room_category" in df.columns:
            df["room_category"] = df["room_category_master"].fillna(
                df["room_category"]
            )
        else:
            df["room_category"] = df["room_category_master"]
        df.drop(columns=["room_category_master"], inplace=True)

    # Merge rate plan information
    df = df.merge(
        rates[["rate_plan_id", "nightly_rate"]],
        on="rate_plan_id",
        how="left"
    )

    df["nightly_rate"] = pd.to_numeric(
        df["nightly_rate"],
        errors="coerce"
    ).fillna(0)

    # Calculate stay duration
    df["nights"] = (
        df["check_out"] - df["check_in"]
    ).dt.days

    # Detect data problems
    df["data_issue"] = ""

    invalid_dates = (
        df["check_in"].isna()
        | df["check_out"].isna()
        | (df["nights"] <= 0)
    )

    df.loc[
        invalid_dates,
        "data_issue"
    ] = "Invalid booking dates"

    # Detect invalid room IDs
    valid_rooms = set(rooms["room_id"])

    invalid_rooms = ~df["room_id"].isin(valid_rooms)

    df.loc[
        invalid_rooms & (df["data_issue"] == ""),
        "data_issue"
    ] = "Invalid room ID"

    # Calculate estimated revenue
    df["estimated_revenue"] = (
        df["nightly_rate"] * df["nights"].clip(lower=0)
    )

    df.loc[
        df["status"].isin(["cancelled", "no_show"]),
        "estimated_revenue"
    ] = 0

    # Identify overlapping reservations
    df["overlap_flag"] = 0

    active = df[
        ~df["status"].isin(["cancelled", "no_show"])
        & df["check_in"].notna()
        & df["check_out"].notna()
        & (df["nights"] > 0)
    ].sort_values(["room_id", "check_in"])

    for room, group in active.groupby("room_id"):

        previous_end = None

        for index, row in group.iterrows():

            if (
                previous_end is not None
                and row["check_in"] < previous_end
            ):

                df.loc[index, "overlap_flag"] = 1

                if df.loc[index, "data_issue"] == "":
                    df.loc[index, "data_issue"] = (
                        "Overlapping booking"
                    )

            if (
                previous_end is None
                or row["check_out"] > previous_end
            ):
                previous_end = row["check_out"]

    return _normalize_reservation_df(df)


# Calculate daily occupancy
def calculate_occupancy(df, rooms, start_date, end_date):

    df = _normalize_reservation_df(df)
    total_rooms = len(rooms)

    dates = pd.date_range(
        start=start_date,
        end=end_date,
        freq="D"
    )

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

        occupancy = (
            occupied / total_rooms * 100
            if total_rooms > 0 else 0
        )

        results.append({
            "Date": date,
            "Occupied Rooms": occupied,
            "Available Rooms": total_rooms,
            "Occupancy Rate": round(occupancy, 2)
        })

    return pd.DataFrame(results)


# Calculate summary measures
def calculate_summary(df, daily):

    df = _normalize_reservation_df(df)
    total = len(df)

    cancelled = len(
        df[df["status"] == "cancelled"]
    )

    revenue = df["estimated_revenue"].sum()

    cancellation_rate = (
        cancelled / total * 100
        if total > 0 else 0
    )

    occupancy_rate = (
        daily["Occupancy Rate"].mean()
        if not daily.empty else 0
    )

    overlaps = int(df["overlap_flag"].sum())

    issues = len(
        df[df["data_issue"] != ""]
    )

    return {
        "total_reservations": total,
        "total_revenue": revenue,
        "occupancy_rate": occupancy_rate,
        "cancelled": cancelled,
        "cancellation_rate": cancellation_rate,
        "overlaps": overlaps,
        "data_issues": issues
    }


# Revenue by room category
def revenue_by_category(df):

    df = _normalize_reservation_df(df)

    result = (
        df[~df["status"].isin(["cancelled", "no_show"])]
        .groupby("room_category")["estimated_revenue"]
        .sum()
        .reset_index()
    )

    return result


# Cancellation analysis
def cancellation_analysis(df):

    df = _normalize_reservation_df(df)

    cancelled = df[
        df["status"] == "cancelled"
    ]

    result = (
        cancelled.groupby("cancellation_code")
        .size()
        .reset_index(name="Total Cancellations")
    )

    return result
