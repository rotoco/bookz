import streamlit as st
import duckdb
import pandas as pd
import requests
import altair as alt
from db import get_connection, init_db

st.set_page_config(page_title="📚🛢️ bookz", layout="wide")

# Ensure DB is ready
init_db()

st.title("📚🛢️ bookz")

# Utility: fetch book details by ISBN
def fetch_book_details(isbn):
    url = f"https://openlibrary.org/isbn/{isbn}.json"
    try:
        r = requests.get(url)
        if r.status_code == 200:
            data = r.json()
            return {
                "title": data.get("title", ""),
                "author": ", ".join([a.get("name", "") for a in data.get("authors", [])]) if "authors" in data else "",
            }
        return None
    except Exception as e:
        st.error(f"Error fetching ISBN data: {e}")
        return None


# Tabs for Books and Reviews
tab1, tab2 = st.tabs(["📖 bookz", "⭐ reviewz"])


# --- BOOKS TAB ---
with tab1:
    st.header("Add a new book")

    with st.form("add_book", clear_on_submit=True):
        isbn = st.text_input("ISBN (optional)")

        # Prefill details if ISBN found
        default_title = ""
        default_author = ""
        if isbn:
            details = fetch_book_details(isbn)
            if details:
                st.success("Book details found via ISBN")
                default_title = details["title"]
                default_author = details["author"]

                # Show cover if available
                st.image(f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg", width=120)

        title = st.text_input("Title", value=default_title)
        author = st.text_input("Author", value=default_author)

        book_format = st.selectbox(
            "Format",
            ["NA", "Audiobook", "Hardcover", "Paperback", "pdf"],
            index=0
        )

        # Optional Start/End Dates
        start_date = st.date_input("Start Date (optional)", value=None, key="start_date")
        end_date = st.date_input("End Date (optional)", value=None, key="end_date")

        submitted = st.form_submit_button("Add Book")
        if submitted and title and author:
            conn = get_connection()
            next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
            conn.execute(
                "INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?)",
                [next_id, title, author, book_format, start_date, end_date, isbn]
            )
            conn.close()
            st.success(f"Book '{title}' added!")

    # --- Bulk Import CSV ---
    st.subheader("📥 Bulk Import Books (CSV)")
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
    if uploaded_file is not None:
        try:
            # Try utf-8, fallback to latin1
            try:
                df = pd.read_csv(uploaded_file)
            except UnicodeDecodeError:
                df = pd.read_csv(uploaded_file, encoding="latin1")

            # Normalize column names
            df.columns = [c.strip().lower() for c in df.columns]

            # Ensure required columns exist
            required = {"title", "author"}
            if not required.issubset(set(df.columns)):
                st.error(f"CSV must include at least: {required}")
            else:
                conn = get_connection()
                for _, row in df.iterrows():
                    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]

                    # Parse dates safely
                    start_date = None
                    end_date = None
                    if "start_date" in df.columns and pd.notna(row.get("start_date")):
                        start_date = pd.to_datetime(row["start_date"], errors="coerce")
                    if "end_date" in df.columns and pd.notna(row.get("end_date")):
                        end_date = pd.to_datetime(row["end_date"], errors="coerce")

                    conn.execute(
                        "INSERT INTO books (id, title, author, format, start_date, end_date, isbn) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            next_id,
                            row.get("title"),
                            row.get("author"),
                            row.get("format", "NA"),
                            start_date.date() if pd.notna(start_date) else None,
                            end_date.date() if pd.notna(end_date) else None,
                            row.get("isbn") if "isbn" in df.columns else None,
                        ]
                    )
                conn.close()
                st.success("✅ CSV imported successfully!")
        except Exception as e:
            st.error(f"Error importing CSV: {e}")

    # --- Manage Books ---
    st.subheader("⚙️ Manage Books")

    conn = get_connection()
    df_books = conn.execute("SELECT * FROM books").fetchdf()
    conn.close()

    if not df_books.empty:
        for _, row in df_books.iterrows():
            with st.expander(f"{row['title']} by {row['author']}"):
                # Format
                formats = ["NA", "Audiobook", "Hardcover", "Paperback", "pdf"]
                current_format = row["format"] if row["format"] in formats else "NA"
                new_format = st.selectbox(
                    "Format",
                    formats,
                    index=formats.index(current_format),
                    key=f"format_{row['id']}"
                )

                # Dates
                new_start = st.date_input(
                    "Start Date",
                    value=None if pd.isna(row["start_date"]) else pd.to_datetime(row["start_date"]).date(),
                    key=f"start_{row['id']}"
                )
                new_end = st.date_input(
                    "End Date",
                    value=None if pd.isna(row["end_date"]) else pd.to_datetime(row["end_date"]).date(),
                    key=f"end_{row['id']}"
                )

                # ISBN
                new_isbn = st.text_input(
                    "ISBN",
                    value="" if pd.isna(row["isbn"]) else row["isbn"],
                    key=f"isbn_{row['id']}"
                )

                # Save
                if st.button("💾 Save Changes", key=f"save_{row['id']}"):
                    conn = get_connection()
                    conn.execute(
                        """
                        UPDATE books
                        SET format=?, start_date=?, end_date=?, isbn=?
                        WHERE id=?
                        """,
                        [new_format, new_start, new_end, new_isbn, row["id"]],
                    )
                    conn.close()
                    st.success(f"Updated '{row['title']}'")

                # Delete
                if st.button("🗑️ Delete Book", key=f"delete_{row['id']}"):
                    conn = get_connection()
                    conn.execute("DELETE FROM books WHERE id=?", [row["id"]])
                    conn.close()
                    st.warning(f"Deleted '{row['title']}'")
                    st.experimental_rerun()
    else:
        st.info("No books in your collection yet.")


# --- REVIEWS TAB ---
with tab2:
    st.header("Add a review")
    conn = get_connection()
    # Only completed books (end_date not null)
    books = conn.execute("SELECT id, title FROM books WHERE end_date IS NOT NULL").fetchall()
    conn.close()

    if books:
        with st.form("add_review", clear_on_submit=True):
            book_choice = st.selectbox("Book", books, format_func=lambda b: f"{b[1]} (id={b[0]})")
            rating = st.slider("Rating", 1, 5, 3)
            comment = st.text_area("Comment")
            submitted = st.form_submit_button("Add Review")
            if submitted:
                conn = get_connection()
                next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM reviews").fetchone()[0]
                conn.execute(
                    "INSERT INTO reviews (id, book_id, rating, comment) VALUES (?, ?, ?, ?)",
                    [next_id, book_choice[0], rating, comment]
                )
                conn.close()
                st.success("Review added!")

    st.subheader("All Reviews")
    conn = get_connection()
    df_reviews = conn.execute("""
        SELECT r.id, b.title, r.rating, r.comment
        FROM reviews r
        JOIN books b ON r.book_id = b.id
    """).fetchdf()
    conn.close()
    st.dataframe(df_reviews, use_container_width=True)

    # --- Books Read by Year Chart ---
    st.subheader("📊 Books Read by Year")
    conn = get_connection()
    df_books = conn.execute("SELECT title, end_date FROM books WHERE end_date IS NOT NULL").fetchdf()
    conn.close()

    if not df_books.empty:
        df_books["end_date"] = pd.to_datetime(df_books["end_date"], errors="coerce")
        df_books = df_books.dropna(subset=["end_date"])

        years = sorted(df_books["end_date"].dt.year.unique(), reverse=True)
        selected_year = st.selectbox("Select year", years, index=0)

        df_year = df_books[df_books["end_date"].dt.year == selected_year]
        if not df_year.empty:
            df_year["month"] = df_year["end_date"].dt.strftime("%B")
            month_order = [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"
            ]

            chart = (
                alt.Chart(df_year)
                .mark_bar()
                .encode(
                    x=alt.X("month:N", sort=month_order, title="Month"),
                    y=alt.Y("count():Q", title="Books Completed"),
                    tooltip=["count()", "month"]
                )
                .properties(width=600, height=400, title=f"Books Completed in {selected_year}")
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info(f"No books completed in {selected_year}.")
    else:
        st.info("No completed books recorded.")
