import streamlit as st
import duckdb
import pandas as pd
import requests
from db import get_connection, init_db

st.set_page_config(page_title="📚🛢️ bookz", layout="wide")

# Ensure DB exists
init_db()

st.title("📚🛢️ bookz")

# --- Utility: fetch book details by ISBN ---
def fetch_book_details(isbn: str):
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

# --- Tabs ---
tab1, tab2 = st.tabs(["📖 bookz", "⭐ reviewz"])

# ------------------------------------------------------------------
# 📖 BOOKS TAB
# ------------------------------------------------------------------
with tab1:
    st.header("Add a new book")

    with st.form("add_book", clear_on_submit=True):
        isbn = st.text_input("ISBN (optional)")

        default_title = ""
        default_author = ""
        if isbn and len(isbn) in (10, 13):  # Only check valid ISBNs
            details = fetch_book_details(isbn)
            if details:
                st.success("Book details found via ISBN")
                default_title = details["title"]
                default_author = details["author"]
                st.image(f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg", width=120)

        title = st.text_input("Title", value=default_title)
        author = st.text_input("Author", value=default_author)

        book_format = st.selectbox(
            "Format",
            ["NA", "Audiobook", "Hardcover", "Paperback", "pdf"],
            index=0
        )

        start_date = st.date_input("Start Date (optional)", value=None, key="start_date")
        end_date = st.date_input("End Date (optional)", value=None, key="end_date")

        submitted = st.form_submit_button("Add Book")
        if submitted and title and author:
            conn = get_connection()
            next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
            conn.execute(
                "INSERT INTO books (id, title, author, format, start_date, end_date, isbn) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [next_id, title, author, book_format, start_date, end_date, isbn]
            )
            conn.close()
            st.success(f"Book '{title}' added!")

    # --- Bulk Import CSV ---
    st.subheader("📥 Bulk Import Books (CSV)")
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            df.columns = [c.strip().lower() for c in df.columns]

            required = {"title", "author"}
            if not required.issubset(set(df.columns)):
                st.error(f"CSV must include at least: {required}")
            else:
                conn = get_connection()
                for _, row in df.iterrows():
                    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
                    conn.execute(
                        "INSERT INTO books (id, title, author, format, start_date, end_date, isbn) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            next_id,
                            row.get("title"),
                            row.get("author"),
                            row.get("format", "NA"),
                            row.get("start_date") if pd.notna(row.get("start_date")) else None,
                            row.get("end_date") if pd.notna(row.get("end_date")) else None,
                            row.get("isbn") if "isbn" in df.columns else None,
                        ]
                    )
                conn.close()
                st.success("✅ CSV imported successfully!")
        except Exception as e:
            st.error(f"Error importing CSV: {e}")

    # --- Manage Books ---
    st.subheader("📚 Manage Books")
    conn = get_connection()
    df_books = conn.execute("SELECT * FROM books").fetchdf()
    conn.close()

    if not df_books.empty:
        st.dataframe(df_books, use_container_width=True)

        with st.form("delete_book"):
            book_to_delete = st.selectbox("Select book to delete", df_books[["id", "title"]].itertuples(index=False), format_func=lambda b: f"{b.id} - {b.title}")
            delete_btn = st.form_submit_button("Delete Book")
            if delete_btn:
                conn = get_connection()
                conn.execute("DELETE FROM books WHERE id = ?", [book_to_delete.id])
                conn.close()
                st.success(f"Book '{book_to_delete.title}' deleted!")

# ------------------------------------------------------------------
# ⭐ REVIEWS TAB
# ------------------------------------------------------------------
with tab2:
    st.header("Add a review")
    conn = get_connection()
    books = conn.execute("SELECT id, title FROM books").fetchall()
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
