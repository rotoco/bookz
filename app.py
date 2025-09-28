import streamlit as st
import duckdb
import pandas as pd
import requests
import altair as alt
import copy
from db import get_connection, init_db
from concurrent.futures import ThreadPoolExecutor
import streamlit_authenticator as stauth

st.set_page_config(page_title="📚🛢️ bookz", layout="wide")

# --- Load credentials from .streamlit/secrets.toml ---
credentials = st.secrets["credentials"]

# Initialize authenticator
authenticator = stauth.Authenticate(
    credentials,
    cookie_name="bookz_cookie",
    # key="random_signature_key",  # ⚠️ replace with secure secret in production
    cookie_expiry_days=30
)

# Login widget
name, authentication_status, username = authenticator.login("main")

# Ensure DB is ready
init_db()

if authentication_status is False:
    st.error("Username/password is incorrect")
elif authentication_status is None:
    st.warning("Please enter your username and password")
elif authentication_status:
    # Show logout
    authenticator.logout("Logout", "sidebar")

    st.title(f"📚🛢️ bookz — Welcome {name}!")

    # --- Utility: fetch author name by key ---
    def fetch_author_name(author_key):
        try:
            ar = requests.get(f"https://openlibrary.org{author_key}.json")
            if ar.status_code == 200:
                return ar.json().get("name", None)
        except:
            return None
        return None

    # --- Utility: fetch book details by ISBN ---
    def fetch_book_details(isbn):
        url = f"https://openlibrary.org/isbn/{isbn}.json"
        try:
            r = requests.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            authors = []
            with ThreadPoolExecutor() as executor:
                futures = []
                for a in data.get("authors", []):
                    key = a.get("key")
                    if key:
                        futures.append(executor.submit(fetch_author_name, key))
                for f in futures:
                    name = f.result()
                    if name:
                        authors.append(name)

            return {
                "title": data.get("title", "Unknown Title"),
                "author": ", ".join(authors) if authors else "Unknown Author",
                "cover_url": f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg"
            }
        except Exception as e:
            st.error(f"Error fetching ISBN data: {e}")
            return None

    # Tabs
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
            book_format = st.selectbox(
                "Format",
                ["NA", "Audiobook", "Hardcover", "Paperback", "pdf"],
                index=0
            )
            start_date = st.date_input("Start Date (optional)", value=None)
            end_date = st.date_input("End Date (optional)", value=None)

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

        # Bulk Import
        st.subheader("📥 Bulk Import Books (CSV)")
        uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
        if uploaded_file is not None:
            try:
                try:
                    df = pd.read_csv(uploaded_file)
                except UnicodeDecodeError:
                    df = pd.read_csv(uploaded_file, encoding="latin1")
                df.columns = [c.strip().lower() for c in df.columns]
                required = {"title", "author"}
                if not required.issubset(set(df.columns)):
                    st.error(f"CSV must include at least: {required}")
                else:
                    conn = get_connection()
                    for _, row in df.iterrows():
                        next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
                        start_date = pd.to_datetime(row.get("start_date"), errors="coerce") if "start_date" in df.columns else None
                        end_date = pd.to_datetime(row.get("end_date"), errors="coerce") if "end_date" in df.columns else None
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

        # All Books Table
        st.subheader("📚 All Books")
        conn = get_connection()
        df_books = conn.execute("SELECT * FROM books").fetchdf()
        conn.close()
        if not df_books.empty:
            st.dataframe(df_books, use_container_width=True)
        else:
            st.info("No books in your collection yet.")

    # --- REVIEWS TAB ---
    with tab2:
        st.header("Add a review")
        conn = get_connection()
        books = conn.execute("SELECT id, title FROM books WHERE end_date IS NOT NULL").fetchall()
        conn.close()

        if books:
            with st.form("add_review", clear_on_submit=True):
                book_choice = st.selectbox("Book", books, format_func=lambda b: f"{b[1]} (id={b[0]})")

                # Two sliders (-10 to 10)
                form_score = st.slider("Form", -10, 10, 0)
                function_score = st.slider("Function", -10, 10, 0)

                comment = st.text_area("Comment")

                submitted = st.form_submit_button("Add Review")
                if submitted:
                    conn = get_connection()
                    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM reviews").fetchone()[0]
                    conn.execute(
                        "INSERT INTO reviews (id, book_id, form, function, comment) VALUES (?, ?, ?, ?, ?)",
                        [next_id, book_choice[0], form_score, function_score, comment]
                    )
                    conn.close()
                    st.success("Review added!")

        st.subheader("All Reviews")
        conn = get_connection()
        df_reviews = conn.execute("""
            SELECT r.id, b.title, r.form, r.function, r.comment
            FROM reviews r
            JOIN books b ON r.book_id = b.id
        """).fetchdf()
        conn.close()
        if not df_reviews.empty:
            st.dataframe(df_reviews, use_container_width=True)
        else:
            st.info("No reviews yet.")

    # --- MANAGE TAB ---
    with tab3:
        st.header("⚙️ Manage Books")
        conn = get_connection()
        df_books = conn.execute("SELECT * FROM books").fetchdf()
        conn.close()

        if not df_books.empty:
            book_choice = st.selectbox(
                "Select a book to manage",
                df_books.to_dict("records"),
                format_func=lambda b: f"{b['title']} by {b['author']}" if b else "Select...",
            )
            if book_choice:
                book_id = book_choice["id"]
                formats = ["NA", "Audiobook", "Hardcover", "Paperback", "pdf"]
                current_format = book_choice["format"] if book_choice["format"] in formats else "NA"
                new_format = st.selectbox("Format", formats, index=formats.index(current_format))
                new_start = st.date_input("Start Date",
                    value=None if pd.isna(book_choice["start_date"]) else pd.to_datetime(book_choice["start_date"]).date())
                new_end = st.date_input("End Date",
                    value=None if pd.isna(book_choice["end_date"]) else pd.to_datetime(book_choice["end_date"]).date())
                new_isbn = st.text_input("ISBN",
                    value="" if pd.isna(book_choice["isbn"]) else book_choice["isbn"])

                if st.button("💾 Save Changes"):
                    conn = get_connection()
                    conn.execute(
                        "UPDATE books SET format=?, start_date=?, end_date=?, isbn=? WHERE id=?",
                        [new_format, new_start, new_end, new_isbn, book_id],
                    )
                    conn.close()
                    st.success(f"Updated '{book_choice['title']}'")

                if st.button("🗑️ Delete Book"):
                    conn = get_connection()
                    conn.execute("DELETE FROM reviews WHERE book_id=?", [book_id])
                    conn.execute("DELETE FROM books WHERE id=?", [book_id])
                    conn.close()
                    st.warning(f"Deleted '{book_choice['title']}'")
                    st.experimental_rerun()
        else:
            st.info("No books in your collection yet.")

        st.subheader("⚠️ Danger Zone")
        with st.expander("Delete ALL Books"):
            st.warning("This will remove ALL books and reviews. Cannot be undone!")
            confirm = st.checkbox("Yes, I understand. Delete everything.")
            if st.button("🗑️ Delete ALL Books") and confirm:
                conn = get_connection()
                conn.execute("DELETE FROM reviews")
                conn.execute("DELETE FROM books")
                conn.close()
                st.success("✅ All books and reviews deleted.")
                st.experimental_rerun()
