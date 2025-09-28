import streamlit as st
import duckdb
import pandas as pd
import requests
import altair as alt
from concurrent.futures import ThreadPoolExecutor
import streamlit_authenticator as stauth

from db import get_connection, init_db

st.set_page_config(page_title="📚🛢️ bookz", layout="wide")

# ---------------- AUTHENTICATION ----------------

# Load credentials from secrets.toml
auth_secrets = st.secrets["auth"]

credentials = {
    "usernames": {
        username: {
            "name": username,
            "password": password
        } for username, password in auth_secrets["users"].items()
    }
}

# Authenticator (v0.11+)
authenticator = stauth.Authenticate(
    credentials=credentials,
    cookie_name="bookz_cookie",
    cookie_key=auth_secrets["cookie_key"],  # secure secret from secrets.toml
    cookie_expiry_days=30
)

# Login screen (location must be one of "main", "sidebar", "unrendered")
name, authentication_status, username = authenticator.login("Login", location="main")

if authentication_status is False:
    st.error("❌ Username/password is incorrect")
elif authentication_status is None:
    st.warning("⚠️ Please enter your username and password")
else:
    st.success(f"Welcome {name}!")

    # ---------------- DB INIT ----------------
    init_db()
    st.title("📚🛢️ bookz")

    # --- Utilities ---
    def fetch_author_name(author_key):
        try:
            ar = requests.get(f"https://openlibrary.org{author_key}.json")
            if ar.status_code == 200:
                return ar.json().get("name", None)
        except:
            return None
        return None

    def fetch_book_details(isbn):
        try:
            r = requests.get(f"https://openlibrary.org/isbn/{isbn}.json")
            if r.status_code != 200:
                return None
            data = r.json()

            authors = []
            with ThreadPoolExecutor() as executor:
                futures = [executor.submit(fetch_author_name, a.get("key")) for a in data.get("authors", []) if a.get("key")]
                for f in futures:
                    n = f.result()
                    if n:
                        authors.append(n)

            return {
                "title": data.get("title", "Unknown Title"),
                "author": ", ".join(authors) if authors else "Unknown Author",
                "cover_url": f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
            }
        except Exception as e:
            st.error(f"Error fetching ISBN data: {e}")
            return None

    # ---------------- Tabs ----------------
    tab1, tab2, tab3 = st.tabs(["📖 bookz", "⭐ reviewz", "⚙️ manage"])

    # --- BOOKS TAB ---
    with tab1:
        st.header("Add a new book")
        isbn = st.text_input("ISBN (optional, press Enter to fetch details)")
        default_title, default_author, default_cover = "", "", None

        if isbn:
            details = fetch_book_details(isbn)
            if details:
                st.success("✅ Book details found via ISBN")
                default_title = details["title"]
                default_author = details["author"]
                default_cover = details["cover_url"]
                st.image(default_cover, width=120)
            else:
                st.warning("⚠️ No details found for that ISBN.")

        with st.form("add_book", clear_on_submit=True):
            title = st.text_input("Title", value=default_title)
            author = st.text_input("Author", value=default_author)
            book_format = st.selectbox("Format", ["NA", "Audiobook", "Hardcover", "Paperback", "pdf"], index=0)
            start_date = st.date_input("Start Date (optional)", value=None, key="start_date")
            end_date = st.date_input("End Date (optional)", value=None, key="end_date")
            submitted = st.form_submit_button("Add Book")
            if submitted and title and author:
                conn = get_connection()
                next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
                conn.execute(
                    "INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [next_id, title, author, book_format, start_date, end_date, isbn, username]
                )
                conn.close()
                st.success(f"Book '{title}' added!")

        # --- All Books Table ---
        st.subheader("📚 All Books")
        conn = get_connection()
        df_books = conn.execute("SELECT * FROM books WHERE user_id=?", [username]).fetchdf()
        conn.close()
        if not df_books.empty:
            st.dataframe(df_books, use_container_width=True)
        else:
            st.info("No books in your collection yet.")

    # --- REVIEWS TAB ---
    with tab2:
        st.header("Add a review")
        conn = get_connection()
        books = conn.execute("SELECT id, title FROM books WHERE end_date IS NOT NULL AND user_id=?", [username]).fetchall()
        conn.close()

        if books:
            with st.form("add_review", clear_on_submit=True):
                book_choice = st.selectbox("Book", books, format_func=lambda b: f"{b[1]} (id={b[0]})")

                form_score = st.slider("🎨 Form", -10, 10, 0)
                function_score = st.slider("⚙️ Function", -10, 10, 0)

                comment = st.text_area("Comment")
                submitted = st.form_submit_button("Add Review")
                if submitted:
                    conn = get_connection()
                    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM reviews").fetchone()[0]
                    conn.execute(
                        "INSERT INTO reviews (id, book_id, form, function, comment, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                        [next_id, book_choice[0], form_score, function_score, comment, username]
                    )
                    conn.close()
                    st.success("Review added!")

        st.subheader("All Reviews")
        conn = get_connection()
        df_reviews = conn.execute("""
            SELECT r.id, b.title, r.form, r.function, r.comment
            FROM reviews r
            JOIN books b ON r.book_id = b.id
            WHERE r.user_id=? AND b.user_id=?
        """, [username, username]).fetchdf()
        conn.close()
        st.dataframe(df_reviews, use_container_width=True)
