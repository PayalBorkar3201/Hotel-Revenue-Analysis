from datetime import timedelta
import streamlit as st
import pandas as pd
import plotly.express as px

from analysis import (
    load_datasets,
    reconcile_reservations,
    calculate_occupancy,
    calculate_summary,
    revenue_by_category,
    cancellation_analysis
)

from database import (
    initialize_database,
    save_processed_data
)


def ensure_reservation_id_column(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        return frame
    result = frame.copy()
    if result.index.name == "reservation_id":
        result = result.reset_index()
    elif "reservation_id" not in result.columns and "reservation_id" in result.index.names:
        result = result.reset_index(level="reservation_id")
    return result


st.set_page_config(
    page_title="Hotel Revenue Analytics",
    page_icon="🏨",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background-color: #f3f7fc;
}
h1, h2, h3 {
    color: #102a43 !important;
    font-weight: 700 !important;
}
p, label, span {
    color: #243b53;
}
h2 {
    font-size: 28px !important;
}
[data-testid="stMetric"] {
    background-color: #ffffff;
    padding: 20px;
    border-radius: 12px;
    border: 1px solid #cbd5e1;
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    overflow: hidden;
}
[data-testid="stMetricLabel"] {
    color: #334155 !important;
    font-weight: 600 !important;
}
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] > div {
    color: #102a43 !important;
    font-weight: 700 !important;
    font-size: clamp(1.1rem, 1.8vw, 1.85rem) !important;
    white-space: nowrap !important;
    overflow: visible !important;
    text-overflow: clip !important;
}
[data-testid="stSidebar"] {
    background-color: #e8f0fa;
}
</style>
""", unsafe_allow_html=True)

initialize_database()

if "active_page" not in st.session_state:
    st.session_state.active_page = "Dashboard"

if "custom_bookings" not in st.session_state:
    st.session_state.custom_bookings = []

st.sidebar.title("🏨 Hotel Analytics")

nav_options = [
    "Dashboard",
    "Book Hotel",
    "Upcoming Bookings",
    "Reservation Records",
    "Occupancy Analysis",
    "Revenue Analysis",
    "Cancellation Analysis",
    "Data Quality & Reconciliation"
]

selected_nav = st.sidebar.radio(
    "Navigation",
    nav_options,
    index=nav_options.index(st.session_state.active_page)
    if st.session_state.active_page in nav_options else 0
)
st.session_state.active_page = selected_nav

today_date = pd.Timestamp.today().normalize().date()
far_future_date = today_date + timedelta(days=365 * 5)

st.sidebar.subheader("Date & Booking Controls")
selected_booking_date = st.sidebar.date_input(
    "Select booking / stay date",
    value=today_date,
    min_value=today_date,
    max_value=far_future_date
)

if st.sidebar.button("Book Hotel", type="primary", use_container_width=True):
    st.session_state.active_page = "Book Hotel"
    st.rerun()

page = st.session_state.active_page

st.sidebar.markdown("---")
st.sidebar.caption("Hotel Revenue, Occupancy and Cancellation Analysis")

try:
    data = load_datasets()
    df = ensure_reservation_id_column(reconcile_reservations(data))

    if st.session_state.custom_bookings:
        extra_df = pd.DataFrame(st.session_state.custom_bookings)
        for col in ["check_in", "check_out", "booking_date"]:
            if col in extra_df.columns:
                extra_df[col] = pd.to_datetime(extra_df[col], errors="coerce")
        df = pd.concat([df, extra_df], ignore_index=True)

    save_columns = [
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
    for c in save_columns:
        if c not in df.columns:
            df[c] = ""

    save_processed_data(df[save_columns])

except Exception as error:
    st.error(f"Dataset processing error: {error}")
    st.info("Please check that all five CSV files are inside the dataset folder.")
    st.stop()

valid_check_in = df["check_in"].dropna()
valid_check_out = df["check_out"].dropna()

if valid_check_in.empty or valid_check_out.empty:
    st.error("No valid reservation dates found.")
    st.stop()

occ_start = min(valid_check_in.min().date(), selected_booking_date)
occ_end = max(valid_check_out.max().date(), selected_booking_date)

daily = calculate_occupancy(
    df,
    data["rooms"],
    occ_start,
    occ_end
)

summary = calculate_summary(
    df,
    daily
)

category_data = revenue_by_category(df)
cancellation_data = cancellation_analysis(df, data.get("cancellations"))

st.title("🏨 Hotel Revenue, Occupancy and Cancellation Analysis")
st.write("Analyze hotel reservations, room occupancy, revenue and cancellations.")


if page == "Dashboard":
    st.header("Executive Dashboard")

    col1, col2, col3, col4 = st.columns([1, 1.35, 1, 1])
    col1.metric("Total Reservations", summary["total_reservations"])
    col2.metric("Total Revenue", f"₹{summary['total_revenue']:,.0f}")
    col3.metric("Average Occupancy", f"{summary['occupancy_rate']:.1f}%")
    col4.metric("Cancellation Rate", f"{summary['cancellation_rate']:.1f}%")

    st.markdown("---")
    st.subheader("Hotel Performance")

    left, right = st.columns(2)

    with left:
        fig = px.line(
            daily,
            x="Date",
            y="Occupancy Rate",
            markers=True,
            title="Daily Occupancy Trend"
        )
        fig.update_layout(yaxis_range=[0, 100])
        st.plotly_chart(fig, use_container_width=True)

    with right:
        if not category_data.empty:
            fig = px.bar(
                category_data,
                x="room_category",
                y="estimated_revenue",
                color="room_category",
                title="Revenue by Room Category",
                labels={
                    "room_category": "Room Category",
                    "estimated_revenue": "Revenue (₹)"
                }
            )
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.subheader("Key Findings")

    st.write(f"• The hotel recorded {summary['total_reservations']} reservations.")
    st.write(f"• Estimated revenue is ₹{summary['total_revenue']:,.0f}.")
    st.write(f"• Average room occupancy is {summary['occupancy_rate']:.2f}%.")
    st.write(f"• {summary['cancelled']} reservations were cancelled.")
    st.write(f"• {summary['overlaps']} overlapping bookings were identified.")
    st.write(f"• {summary['data_issues']} records have data-quality issues.")

    status_data = df["status"].value_counts().reset_index()
    status_data.columns = ["Status", "Count"]

    fig = px.pie(
        status_data,
        names="Status",
        values="Count",
        hole=0.4,
        title="Reservation Status Distribution"
    )
    st.plotly_chart(fig, use_container_width=True)


elif page == "Book Hotel":
    st.header("🏨 Book Hotel")

    chosen_date = st.date_input(
        "Selected Stay Date",
        value=selected_booking_date,
        min_value=today_date,
        max_value=far_future_date,
        key="book_hotel_date_picker"
    )

    st.subheader(f"Bookings on {chosen_date.strftime('%d-%m-%Y')}")

    day_ts = pd.Timestamp(chosen_date)
    date_bookings = df[
        df["check_in"].notna()
        & df["check_out"].notna()
        & (df["check_in"] <= day_ts)
        & (df["check_out"] > day_ts)
    ].copy()

    rooms_df = data.get("rooms", pd.DataFrame())
    total_rooms = len(rooms_df)
    active_on_day = date_bookings[~date_bookings["status"].isin(["cancelled", "no_show"])]
    occupied_on_day = int(active_on_day["room_id"].nunique()) if not active_on_day.empty else 0
    available_on_day = max(total_rooms - occupied_on_day, 0)

    m1, m2, m3 = st.columns(3)
    m1.metric("Bookings on Selected Date", len(date_bookings))
    m2.metric("Occupied Rooms", occupied_on_day)
    m3.metric("Rooms Available", available_on_day)

    if not date_bookings.empty:
        st.dataframe(
            date_bookings[
                [
                    "reservation_id",
                    "guest_name",
                    "room_id",
                    "room_category",
                    "check_in",
                    "check_out",
                    "status",
                    "estimated_revenue"
                ]
            ],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info(f"No existing bookings found on {chosen_date.strftime('%d-%m-%Y')}. You can add a new booking below.")

    st.markdown("---")
    st.subheader("Create New Booking")

    room_options = (
        rooms_df["room_id"].astype(str).tolist()
        if not rooms_df.empty and "room_id" in rooms_df.columns
        else ["101", "102", "201", "202", "301"]
    )

    with st.form("new_booking_form"):
        c1, c2 = st.columns(2)
        guest_name = c1.text_input("Guest Name", placeholder="Enter guest name")
        room_id = c2.selectbox("Room ID", room_options)

        c3, c4 = st.columns(2)
        check_out_date = c3.date_input(
            "Check-Out Date",
            value=chosen_date + timedelta(days=1),
            min_value=chosen_date + timedelta(days=1),
            max_value=far_future_date
        )
        nightly_rate = c4.number_input("Nightly Rate (₹)", min_value=500, max_value=100000, value=3500, step=500)

        submitted = st.form_submit_button("Confirm Booking")

        if submitted:
            nights = max((check_out_date - chosen_date).days, 1)
            next_num = 1001 + len(df)
            new_row = {
                "reservation_id": f"R{next_num}",
                "guest_name": guest_name.strip() if guest_name.strip() else "Walk-In Guest",
                "room_id": str(room_id),
                "room_category": "Standard",
                "check_in": pd.Timestamp(chosen_date),
                "check_out": pd.Timestamp(check_out_date),
                "booking_date": pd.Timestamp.today().normalize(),
                "status": "confirmed",
                "cancellation_code": "",
                "rate_plan_id": "BAR",
                "estimated_revenue": nightly_rate * nights,
                "overlap_flag": 0,
                "data_issue": ""
            }
            st.session_state.custom_bookings.append(new_row)
            st.success(f"Booking {new_row['reservation_id']} created for {chosen_date.strftime('%d-%m-%Y')} to {check_out_date.strftime('%d-%m-%Y')}.")
            st.rerun()


elif page == "Upcoming Bookings":
    st.header("📅 Upcoming Hotel Bookings")

    today = pd.Timestamp.today().normalize()
    future_end = today + pd.Timedelta(days=365 * 5)

    date_range = st.date_input(
        "Select Upcoming Booking Period",
        value=(selected_booking_date, future_end.date()),
        min_value=today.date(),
        max_value=future_end.date()
    )

    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        start_date, end_date = date_range

        upcoming = df[
            df["check_in"].notna()
            & (df["check_in"] >= pd.Timestamp(start_date))
            & (df["check_in"] <= pd.Timestamp(end_date))
            & (~df["status"].isin(["cancelled", "no_show"]))
        ].copy().sort_values("check_in")

        st.metric("Upcoming Reservations", len(upcoming))

        if not upcoming.empty:
            st.dataframe(
                upcoming[
                    [
                        "reservation_id",
                        "guest_name",
                        "room_id",
                        "room_category",
                        "check_in",
                        "check_out",
                        "status",
                        "estimated_revenue"
                    ]
                ],
                use_container_width=True,
                hide_index=True
            )

            st.download_button(
                "Download Upcoming Bookings",
                upcoming.to_csv(index=False).encode("utf-8"),
                "upcoming_bookings.csv",
                "text/csv"
            )
        else:
            st.info("No upcoming bookings found for the selected dates.")


elif page == "Reservation Records":
    st.header("Reservation Records")

    display_df = df.copy()

    search = st.text_input("Search by reservation ID, guest name or room ID")
    if search:
        mask = (
            display_df["reservation_id"].astype(str).str.contains(search, case=False, na=False)
            | display_df["guest_name"].astype(str).str.contains(search, case=False, na=False)
            | display_df["room_id"].astype(str).str.contains(search, case=False, na=False)
        )
        display_df = display_df[mask]

    statuses = ["All"] + sorted(display_df["status"].dropna().unique().tolist())
    selected_status = st.selectbox("Filter by reservation status", statuses)
    if selected_status != "All":
        display_df = display_df[display_df["status"] == selected_status]

    st.metric("Showing Records", len(display_df))

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True
    )

    st.download_button(
        "Download Reservation Records",
        display_df.to_csv(index=False).encode("utf-8"),
        "reservation_records.csv",
        "text/csv"
    )


elif page == "Occupancy Analysis":
    st.header("Room Occupancy Analysis")

    latest_row = daily.iloc[-1] if not daily.empty else None
    remaining_rooms = int(latest_row["Available Rooms"]) if latest_row is not None else len(data["rooms"])

    col1, col2, col3 = st.columns(3)
    col1.metric("Average Occupancy", f"{summary['occupancy_rate']:.2f}%")
    col2.metric("Total Room Inventory", len(data["rooms"]))
    col3.metric("Rooms Available (Latest Day)", remaining_rooms)

    fig = px.area(
        daily,
        x="Date",
        y="Occupancy Rate",
        title="Daily Hotel Occupancy"
    )
    fig.update_layout(yaxis_range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Daily Occupancy Details")
    st.dataframe(
        daily,
        use_container_width=True,
        hide_index=True
    )

    st.download_button(
        "Download Occupancy Report",
        daily.to_csv(index=False).encode("utf-8"),
        "occupancy_report.csv",
        "text/csv"
    )


elif page == "Revenue Analysis":
    st.header("Hotel Revenue Analysis")

    st.metric("Total Estimated Revenue", f"₹{summary['total_revenue']:,.0f}")

    st.subheader("Revenue by Room Category")
    if not category_data.empty:
        fig = px.bar(
            category_data,
            x="room_category",
            y="estimated_revenue",
            color="room_category",
            title="Room Category Revenue"
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(category_data, use_container_width=True, hide_index=True)

    monthly = df[~df["status"].isin(["cancelled", "no_show"])].copy()
    monthly["Month"] = monthly["check_in"].dt.to_period("M").astype(str)
    monthly_data = (
        monthly.groupby("Month")["estimated_revenue"]
        .sum()
        .reset_index()
    )

    st.subheader("Monthly Revenue Trend")
    if not monthly_data.empty:
        fig = px.line(
            monthly_data,
            x="Month",
            y="estimated_revenue",
            markers=True,
            title="Monthly Revenue"
        )
        st.plotly_chart(fig, use_container_width=True)


elif page == "Cancellation Analysis":
    st.header("Cancellation Analysis")

    col1, col2 = st.columns(2)
    col1.metric("Cancelled Reservations", summary["cancelled"])
    col2.metric("Cancellation Rate", f"{summary['cancellation_rate']:.2f}%")

    st.subheader("Cancellation Reasons")

    if not cancellation_data.empty:
        fig = px.bar(
            cancellation_data,
            x="cancellation_reason",
            y="Total Cancellations",
            color="cancellation_reason",
            hover_data=["cancellation_code"],
            title="Cancellation by Reason"
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            cancellation_data[["cancellation_reason", "cancellation_code", "Total Cancellations"]],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success("No cancelled reservations found.")


elif page == "Data Quality & Reconciliation":
    st.header("Data Quality and Reconciliation")

    col1, col2, col3 = st.columns(3)
    col1.metric("Overlapping Bookings", summary["overlaps"])
    col2.metric("Data Quality Issues", summary["data_issues"])
    col3.metric("Total Reservations", summary["total_reservations"])

    st.markdown("---")
    st.subheader("Overlapping Reservations")

    overlaps = df[df["overlap_flag"] == 1]
    if not overlaps.empty:
        st.warning("Overlapping reservations were identified.")
        st.dataframe(overlaps, use_container_width=True, hide_index=True)
    else:
        st.success("No overlapping reservations found.")

    st.subheader("Data Quality Problems")

    issues = df[df["data_issue"] != ""]
    if not issues.empty:
        st.dataframe(
            issues[["reservation_id", "room_id", "status", "data_issue"]],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success("No data-quality problems found.")

    st.subheader("Reservation Audit Summary")

    audit = (
        df.groupby("status")
        .agg(
            Total_Reservations=("reservation_id", "count"),
            Estimated_Revenue=("estimated_revenue", "sum"),
            Overlapping_Bookings=("overlap_flag", "sum")
        )
        .reset_index()
    )

    st.dataframe(audit, use_container_width=True, hide_index=True)

    st.download_button(
        "Download Audit Report",
        audit.to_csv(index=False).encode("utf-8"),
        "hotel_audit_report.csv",
        "text/csv"
    )


st.markdown("---")
st.caption(
    "Hotel Revenue Analytics | Individual Mini Project | "
    "Python • Streamlit • SQLite • Pandas • Plotly"
)
