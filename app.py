import streamlit as st
import duckdb
import pandas as pd
import requests
import altair as alt
from db import get_connection, init_db
import streamlit_authenticator as stauth
from concurrent.futures import ThreadPoolExecutor

# --- AUTH SETUP ---
# Credentials should live in .streamlit/secrets.toml
# Example:
# [credentials]
# usernames = {
#   alice = {name = "Alice Smith", password = "abc123"},
#   bob   = {name = "Bob Jones",   password = "def456"}
# }

credentials = st.secrets["credentials"]

authenticator = stauth.Authenticate(
    credentials,
    cookie_name="bookz_app",
    key="abcdef",
    cookie_expiry_days=30
)

# Render login/logout in sidebar
auth_result = authenticator.login(location="sidebar")

if auth_result is not None:
    name, authentication_status, username = auth_result
else:
    name = authentication_status = username = None

if not authentication_status:
    if authentication_status is False:
        st.error("❌ Username/password is incorrect")
    else:
        st.warning("👆 Please log in to use the app.")
    st.stop()

# User is logged in
st.sidebar.success(f"Welcome {name} 👋")
authenticator.logout(location="sidebar")

# --- APP CONFIG ---
st.set_page_config(page_title="📚🛢️ bookz", layout="wide")
init_db()
st.title("📚🛢️ bookz")


# --- ISBN FETCH HELPERS ---
def fetch_author_name(author_key):
    try:
        ar = requests.get(f"https://openlibrary.org{author_key}.json")
        if ar.status_code == 200:
            return ar.json().get("name", None)
    except:
        return None
    return None


def fetch_book_details(isbn):
    url = f"https://openlibrary.org/isbn/{isbn}.json"
    try:
        r = requests.get(url)
        if r.status_code != 200:
            return None
        data = r.json()

        # Fetch authors in parallel
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


# --- TABS ---
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

    # Bulk Import CSV
    st.subheader("📥 Bulk Import Books (CSV)")
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])
    if uploaded_file is not None:
        try:
            try:
                df = pd.read_csv(uploaded_file)
            except UnicodeDecodeError:
                df = pd.read_csv(uploaded_file, encoding="latin1")

            df.columns = [c.strip().lower() for c in df.columns]
            if not {"title", "author"}.issubset(df.columns):
                st.error("CSV must include at least: title, author")
            else:
                conn = get_connection()
                for _, row in df.iterrows():
                    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
                    start_date = pd.to_datetime(row.get("start_date"), errors="coerce") if "start_date" in df.columns else None
                    end_date = pd.to_datetime(row.get("end_date"), errors="coerce") if "end_date" in df.columns else None
                    conn.execute(
                        "INSERT INTO books (id, title, author, format, start_date, end_date, isbn, username) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            next_id,
                            row.get("title"),
                            row.get("author"),
                            row.get("format", "NA"),
                            start_date.date() if pd.notna(start_date) else None,
                            end_date.date() if pd.notna(end_date) else None,
                            row.get("isbn") if "isbn" in df.columns else None,
                            username,
                        ]
                    )
                conn.close()
                st.success("✅ CSV imported successfully!")
        except Exception as e:
            st.error(f"Error importing CSV: {e}")

    # Books Table
    st.subheader("📚 All Books")
    conn = get_connection()
    df_books = conn.execute("SELECT * FROM books WHERE username=?", [username]).fetchdf()
    conn.close()
    st.dataframe(df_books, use_container_width=True)


# --- REVIEWS TAB ---
with tab2:
    st.header("Add a review")
    conn = get_connection()
    books = conn.execute("SELECT id, title FROM books WHERE username=? AND end_date IS NOT NULL", [username]).fetchall()
    conn.close()

    if books:
        with st.form("add_review", clear_on_submit=True):
            book_choice = st.selectbox("Book", books, format_func=lambda b: f"{b[1]} (id={b[0]})")
            form_score = st.slider("Form", -10, 10, 0)
            function_score = st.slider("Function", -10, 10, 0)
            comment = st.text_area("Comment")
            submitted = st.form_submit_button("Add Review")
            if submitted:
                conn = get_connection()
                next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM reviews").fetchone()[0]
                conn.execute(
                    "INSERT INTO reviews (id, book_id, form, function, comment, username) VALUES (?, ?, ?, ?, ?, ?)",
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
        WHERE r.username=?
    """, [username]).fetchdf()
    conn.close()
    st.dataframe(df_reviews, use_container_width=True)

    # Chart
    st.subheader("📊 Books Read by Year")
    conn = get_connection()
    df_books = conn.execute("SELECT title, end_date FROM books WHERE username=? AND end_date IS NOT NULL", [username]).fetchdf()
    conn.close()

    if not df_books.empty:
        df_books["end_date"] = pd.to_datetime(df_books["end_date"], errors="coerce")
        years = sorted(df_books["end_date"].dt.year.dropna().unique(), reverse=True)
        selected_year = st.selectbox("Select year", years, index=0)
        df_year = df_books[df_books["end_date"].dt.year == selected_year]
        df_year["month"] = df_year["end_date"].dt.strftime("%B")
        chart = (
            alt.Chart(df_year)
            .mark_bar()
            .encode(
                x=alt.X("month:N", sort=list(calendar.month_name[1:]), title="Month"),
                y=alt.Y("count():Q", title="Books Completed"),
                tooltip=["count()", "month"]
            )
            .properties(width=600, height=400, title=f"Books Completed in {selected_year}")
        )
        st.altair_chart(chart, use_container_width=True)


# --- MANAGE TAB ---
with tab3:
    st.header("⚙️ Manage Books")
    conn = get_connection()
    df_books = conn.execute("SELECT * FROM books WHERE username=?", [username]).fetchdf()
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
            new_start = st.date_input("Start Date", value=pd.to_datetime(book_choice["start_date"]).date() if pd.notna(book_choice["start_date"]) else None)
            new_end = st.date_input("End Date", value=pd.to_datetime(book_choice["end_date"]).date() if pd.notna(book_choice["end_date"]) else None)
            new_isbn = st.text_input("ISBN", value="" if pd.isna(book_choice["isbn"]) else book_choice["isbn"])

            if st.button("💾 Save Changes"):
                conn = get_connection()
                conn.execute(
                    "UPDATE books SET format=?, start_date=?, end_date=?, isbn=? WHERE id=? AND username=?",
                    [new_format, new_start, new_end, new_isbn, book_id, username]
                )
                conn.close()
                st.success(f"Updated '{book_choice['title']}'")

            if st.button("🗑️ Delete Book"):
                conn = get_connection()
                conn.execute("DELETE FROM reviews WHERE book_id=? AND username=?", [book_id, username])
                conn.execute("DELETE FROM books WHERE id=? AND username=?", [book_id, username])
                conn.close()
                st.warning(f"Deleted '{book_choice['title']}'")
                st.experimental_rerun()

    else:
        st.info("No books in your collection yet.")

    st.subheader("⚠️ Danger Zone")
    with st.expander("Delete ALL Books"):
        st.warning("This will remove ALL books and reviews for your account only.")
        confirm = st.checkbox("Yes, I understand. Delete everything.")
        if st.button("🗑️ Delete ALL Books") and confirm:
            conn = get_connection()
            conn.execute("DELETE FROM reviews WHERE username=?", [username])
            conn.execute("DELETE FROM books WHERE username=?", [username])
            conn.close()
            st.success("✅ All your books and reviews have been deleted.")
            st.experimental_rerun()
