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


# Page configuration
st.set_page_config(
    page_title="Hotel Revenue Analytics",
    page_icon="🏨",
    layout="wide"
)


# Custom Styling
st.markdown("""
<style>

/* Main background */
.stApp {
    background-color: #f3f7fc;
}

/* Main headings */
h1, h2, h3 {
    color: #102a43 !important;
    font-weight: 700 !important;
}

/* Paragraph text */
p, label, span {
    color: #243b53;
}

/* Executive Dashboard heading */
h2 {
    font-size: 28px !important;
}

/* Metric cards */
[data-testid="stMetric"] {
    background-color: #ffffff;
    padding: 20px;
    border-radius: 12px;
    border: 1px solid #cbd5e1;
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    overflow: hidden;
}

/* Metric labels */
[data-testid="stMetricLabel"] {
    color: #334155 !important;
    font-weight: 600 !important;
}

/* Metric values: prevent truncation with ellipsis */
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] > div {
    color: #102a43 !important;
    font-weight: 700 !important;
    font-size: clamp(1.1rem, 1.8vw, 1.85rem) !important;
    white-space: nowrap !important;
    overflow: visible !important;
    text-overflow: clip !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #e8f0fa;
}

</style>
""", unsafe_allow_html=True)


# Initialize database
initialize_database()


# Sidebar
st.sidebar.title("🏨 Hotel Analytics")

page = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Upcoming Bookings",
        "Reservation Records",
        "Occupancy Analysis",
        "Revenue Analysis",
        "Cancellation Analysis",
        "Data Quality & Reconciliation"
    ]
)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Hotel Revenue, Occupancy and Cancellation Analysis"
)


# Load and process datasets
try:

    data = load_datasets()

    df = ensure_reservation_id_column(reconcile_reservations(data))

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

    save_processed_data(df[save_columns])

except Exception as error:

    st.error(f"Dataset processing error: {error}")

    st.info(
        "Please check that all five CSV files are inside the dataset folder."
    )

    st.stop()


# Date selection (from today onward for stay selection)
valid_check_in = df["check_in"].dropna()
valid_check_out = df["check_out"].dropna()

if valid_check_in.empty or valid_check_out.empty:

    st.error("No valid reservation dates found.")
    st.stop()

today_date = pd.Timestamp.today().normalize().date()
dataset_min_date = valid_check_in.min().date()
dataset_max_date = (valid_check_out.max() - pd.Timedelta(days=1)).date()

min_allowed_date = today_date
max_allowed_date = max(dataset_max_date, min_allowed_date)

st.sidebar.subheader("Date Filter")

date_range = st.sidebar.date_input(
    "Select stay period",
    value=(min_allowed_date, max_allowed_date),
    min_value=min_allowed_date,
    max_value=max_allowed_date
)

if isinstance(date_range, (tuple, list)):

    if len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date = end_date = date_range[0]

else:

    start_date = end_date = date_range


# Filter reservation records by overlapping stay period
filtered_df = df[
    df["check_in"].notna()
    & df["check_out"].notna()
    & (df["check_out"] > pd.Timestamp(start_date))
    & (df["check_in"] <= pd.Timestamp(end_date))
].copy()

# Use full dataset for analytics when selected future dates have no records yet
analytics_df = filtered_df if not filtered_df.empty else df.copy()
occ_start = start_date if not filtered_df.empty else dataset_min_date
occ_end = end_date if not filtered_df.empty else dataset_max_date


# Calculate analytics
daily = calculate_occupancy(
    df,
    data["rooms"],
    occ_start,
    occ_end
)

summary = calculate_summary(
    analytics_df,
    daily
)

category_data = revenue_by_category(analytics_df)

cancellation_data = cancellation_analysis(analytics_df)


# Dashboard
st.title("🏨 Hotel Revenue, Occupancy and Cancellation Analysis")

st.write(
    "Analyze hotel reservations, room occupancy, revenue and cancellations."
)


if page == "Dashboard":

    st.header("Executive Dashboard")

    col1, col2, col3, col4 = st.columns([1, 1.35, 1, 1])

    col1.metric(
        "Total Reservations",
        summary["total_reservations"]
    )

    col2.metric(
        "Total Revenue",
        f"₹{summary['total_revenue']:,.0f}"
    )

    col3.metric(
        "Average Occupancy",
        f"{summary['occupancy_rate']:.1f}%"
    )

    col4.metric(
        "Cancellation Rate",
        f"{summary['cancellation_rate']:.1f}%"
    )

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

        fig.update_layout(
            yaxis_range=[0, 100]
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

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

            st.plotly_chart(
                fig,
                use_container_width=True
            )

    st.markdown("---")

    st.subheader("Key Findings")

    st.write(
        f"• The hotel recorded {summary['total_reservations']} reservations."
    )

    st.write(
        f"• Estimated revenue is ₹{summary['total_revenue']:,.0f}."
    )

    st.write(
        f"• Average room occupancy is {summary['occupancy_rate']:.2f}%."
    )

    st.write(
        f"• {summary['cancelled']} reservations were cancelled."
    )

    st.write(
        f"• {summary['overlaps']} overlapping bookings were identified."
    )

    st.write(
        f"• {summary['data_issues']} records have data-quality issues."
    )

    status_data = (
        analytics_df["status"]
        .value_counts()
        .reset_index()
    )

    status_data.columns = ["Status", "Count"]

    fig = px.pie(
        status_data,
        names="Status",
        values="Count",
        hole=0.4,
        title="Reservation Status Distribution"
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )


# Upcoming Bookings
elif page == "Upcoming Bookings":

    st.header("📅 Upcoming Hotel Bookings")

    today = pd.Timestamp.today().normalize()

    future_end = today + pd.Timedelta(days=365)

    date_range = st.date_input(
        "Select Upcoming Booking Period",
        value=(today.date(), future_end.date()),
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
        ].copy()

        upcoming = upcoming.sort_values("check_in")

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


# Reservation Records
elif page == "Reservation Records":

    st.header("Reservation Records")

    search = st.text_input(
        "Search by reservation ID, guest name or room ID"
    )

    if search:

        mask = (
            filtered_df["reservation_id"].astype(str).str.contains(
                search, case=False, na=False
            )
            |
            filtered_df["guest_name"].astype(str).str.contains(
                search, case=False, na=False
            )
            |
            filtered_df["room_id"].astype(str).str.contains(
                search, case=False, na=False
            )
        )

        display_df = filtered_df[mask]

    else:

        display_df = filtered_df

    statuses = ["All"] + sorted(
        display_df["status"].dropna().unique().tolist()
    )

    selected_status = st.selectbox(
        "Filter by reservation status",
        statuses
    )

    if selected_status != "All":

        display_df = display_df[
            display_df["status"] == selected_status
        ]

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


# Occupancy Analysis
elif page == "Occupancy Analysis":

    st.header("Room Occupancy Analysis")

    col1, col2 = st.columns(2)

    col1.metric(
        "Average Occupancy",
        f"{summary['occupancy_rate']:.2f}%"
    )

    col2.metric(
        "Total Room Inventory",
        len(data["rooms"])
    )

    fig = px.area(
        daily,
        x="Date",
        y="Occupancy Rate",
        title="Daily Hotel Occupancy"
    )

    fig.update_layout(
        yaxis_range=[0, 100]
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

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


# Revenue Analysis
elif page == "Revenue Analysis":

    st.header("Hotel Revenue Analysis")

    st.metric(
        "Total Estimated Revenue",
        f"₹{summary['total_revenue']:,.0f}"
    )

    st.subheader("Revenue by Room Category")

    if not category_data.empty:

        fig = px.bar(
            category_data,
            x="room_category",
            y="estimated_revenue",
            color="room_category",
            title="Room Category Revenue"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.dataframe(
            category_data,
            use_container_width=True,
            hide_index=True
        )

    monthly = analytics_df[
        ~analytics_df["status"].isin(["cancelled", "no_show"])
    ].copy()

    monthly["Month"] = monthly["check_in"].dt.to_period(
        "M"
    ).astype(str)

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

        st.plotly_chart(
            fig,
            use_container_width=True
        )


# Cancellation Analysis
elif page == "Cancellation Analysis":

    st.header("Cancellation Analysis")

    col1, col2 = st.columns(2)

    col1.metric(
        "Cancelled Reservations",
        summary["cancelled"]
    )

    col2.metric(
        "Cancellation Rate",
        f"{summary['cancellation_rate']:.2f}%"
    )

    st.subheader("Cancellation Reasons")

    cancellation_data = cancellation_data.merge(
        data["cancellations"],
        on="cancellation_code",
        how="left"
    )

    if not cancellation_data.empty:

        fig = px.bar(
            cancellation_data,
            x="cancellation_code",
            y="Total Cancellations",
            color="cancellation_code",
            hover_data=["cancellation_reason"],
            title="Cancellation by Reason"
        )

        st.plotly_chart(
            fig,
            use_container_width=True
        )

        st.dataframe(
            cancellation_data,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.success(
            "No cancelled reservations in this date range."
        )


# Data Quality and Reconciliation
elif page == "Data Quality & Reconciliation":

    st.header("Data Quality and Reconciliation")

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Overlapping Bookings",
        summary["overlaps"]
    )

    col2.metric(
        "Data Quality Issues",
        summary["data_issues"]
    )

    col3.metric(
        "Total Reservations",
        summary["total_reservations"]
    )

    st.markdown("---")

    st.subheader("Overlapping Reservations")

    overlaps = analytics_df[
        analytics_df["overlap_flag"] == 1
    ]

    if not overlaps.empty:

        st.warning(
            "Overlapping reservations were identified."
        )

        st.dataframe(
            overlaps,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.success(
            "No overlapping reservations found."
        )

    st.subheader("Data Quality Problems")

    issues = analytics_df[
        analytics_df["data_issue"] != ""
    ]

    if not issues.empty:

        st.dataframe(
            issues[
                [
                    "reservation_id",
                    "room_id",
                    "status",
                    "data_issue"
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

    else:

        st.success(
            "No data-quality problems found."
        )

    st.subheader("Reservation Audit Summary")

    audit = (
        analytics_df.groupby("status")
        .agg(
            Total_Reservations=("reservation_id", "count"),
            Estimated_Revenue=("estimated_revenue", "sum"),
            Overlapping_Bookings=("overlap_flag", "sum")
        )
        .reset_index()
    )

    st.dataframe(
        audit,
        use_container_width=True,
        hide_index=True
    )

    st.download_button(
        "Download Audit Report",
        audit.to_csv(index=False).encode("utf-8"),
        "hotel_audit_report.csv",
        "text/csv"
    )


# Footer
st.markdown("---")

st.caption(
    "Hotel Revenue Analytics | Individual Mini Project | "
    "Python • Streamlit • SQLite • Pandas • Plotly"
)
