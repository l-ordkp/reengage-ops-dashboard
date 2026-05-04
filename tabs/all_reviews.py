"""All Reviews tab — global review browser with filters and pagination."""

import streamlit as st

from config import PRIORITY_ICON, STATUS_ICON

PAGE_SIZE = 50


def render(df_all, chains, platforms):
    c1, c2, c3, c4 = st.columns(4)
    f_ch = c1.selectbox("Chain",    ["All"] + chains,                             key="fc")
    f_pl = c2.selectbox("Platform", ["All"] + platforms,                           key="fp")
    f_st = c3.selectbox("Status",   ["All", "PENDING", "RESPONDED", "EXPIRED"],    key="fs")
    f_pr = c4.selectbox("Priority", ["All", "CRITICAL", "URGENT", "NORMAL"],       key="fpr")

    df_filt = df_all.copy()
    if f_ch != "All": df_filt = df_filt[df_filt["chain_name"] == f_ch]
    if f_pl != "All": df_filt = df_filt[df_filt["platform"]   == f_pl]
    if f_st != "All": df_filt = df_filt[df_filt["status"]     == f_st]
    if f_pr != "All": df_filt = df_filt[df_filt["priority"]   == f_pr]

    # Reset page when filters change
    filter_key = f"{f_ch}|{f_pl}|{f_st}|{f_pr}"
    if st.session_state.get("ar_prev_filters") != filter_key:
        st.session_state["ar_page"] = 0
        st.session_state["ar_prev_filters"] = filter_key

    total = len(df_filt)
    total_pages = max(1, (total - 1) // PAGE_SIZE + 1)
    page = min(st.session_state.get("ar_page", 0), total_pages - 1)

    st.caption(f"{total:,} reviews")

    if not df_filt.empty:
        show_cols = [
            "review_uid", "order_id", "review_id",
            "priority", "status", "days_left",
            "chain_name", "brand_name", "b_name_id", "platform",
            "slug", "store_id",
            "customer_name", "customer_id", "customer_type", "orders_count",
            "rating_display", "rating_value",
            "order_value", "items",
            "review_text", "response_text",
            "review_date", "portal_link",
        ]
        disp = df_filt[[c for c in show_cols if c in df_filt.columns]].copy()
        disp["priority"] = disp["priority"].map(lambda x: f"{PRIORITY_ICON.get(x,'')} {x}")
        disp["status"]   = disp["status"].map(lambda x: f"{STATUS_ICON.get(x,'')} {x}")

        # Pagination
        start = page * PAGE_SIZE
        page_df = disp.iloc[start:start + PAGE_SIZE]

        st.dataframe(
            page_df, use_container_width=True, hide_index=True,
            column_config={
                "days_left":      st.column_config.NumberColumn("Days", width="small"),
                "portal_link":    st.column_config.LinkColumn("Portal"),
                "review_text":    st.column_config.TextColumn("Review", width="medium"),
                "response_text":  st.column_config.TextColumn("AI Response", width="medium"),
                "items":          st.column_config.TextColumn("Items", width="medium"),
                "order_value":    st.column_config.NumberColumn("Order $", format="$%.0f"),
                "orders_count":   st.column_config.NumberColumn("Orders"),
            },
        )

        # Page controls
        col_prev, col_info, col_next = st.columns([1, 2, 1])
        with col_prev:
            if st.button("Previous", disabled=page == 0, key="ar_prev"):
                st.session_state["ar_page"] = page - 1
                st.rerun()
        with col_info:
            st.caption(f"Page {page + 1} of {total_pages} ({total:,} total)")
        with col_next:
            if st.button("Next", disabled=page >= total_pages - 1, key="ar_next"):
                st.session_state["ar_page"] = page + 1
                st.rerun()

        st.download_button("Download CSV", df_filt.to_csv(index=False),
                           file_name="reengage_reviews.csv", mime="text/csv")
