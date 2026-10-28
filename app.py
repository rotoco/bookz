import streamlit as st
import pandas as pd
import requests
import altair as alt
from concurrent.futures import ThreadPoolExecutor
import streamlit_authenticator as stauth

from db import get_connection, init_db

# --- App Config ---
st.set_page_config(page_title="📚🛢️ bookz", page_icon="books-app-icon.png", layout="wide")

# --- DB Init ---
init_db()


# --- Credentials (from Streamlit secrets, NOT hardcoded) ---
# See the secrets.toml example at the bottom of this file.
def _to_plain(obj):
    """st.secrets is read-only; the authenticator wants plain mutable dicts."""
    if hasattr(obj, "items"):
        return {k: _to_plain(v) for k, v in obj.items()}
    return obj


credentials = _to_plain(st.secrets["credentials"])
cookie = _to_plain(st.secrets["cookie"])

authenticator = stauth.Authenticate(
    credentials,
    cookie["name"],
    cookie["key"],
    cookie["expiry_days"],
)

# --- Login gate (main page, centered) ---
st.title("📚🛢️ bookz")

_, login_col, _ = st.columns([1, 1.2, 1])
with login_col:
    authenticator.login(location="main")

auth_status = st.session_state.get("authentication_status")

if auth_status is False:
    with login_col:
        st.error("Username/password is incorrect")
if not auth_status:
    st.stop()  # nothing below runs until the user is logged in

# ---------------- MAIN APP (logged in) ----------------
username = st.session_state["username"]

st.sidebar.success(f"Welcome {st.session_state['name']}")
authenticator.logout("Logout", "sidebar")


# --- Helpers ---
def flash(message, kind="success"):
    """Queue a message that survives st.rerun()."""
    st.session_state["_flash"] = (kind, message)


def show_flash():
    item = st.session_state.pop("_flash", None)
    if item:
        kind, message = item
        getattr(st, kind)(message)


# Utility: fetch author name by key
def fetch_author_name(author_key):
    try:
        ar = requests.get(f"https://openlibrary.org{author_key}.json")
        if ar.status_code == 200:
            return ar.json().get("name", None)
    except Exception:
        return None
    return None


# Utility: fetch book details by ISBN
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
            "cover_url": f"https://covers.openlibrary.org/b/isbn/{isbn}-M.jpg",
        }
    except Exception as e:
        st.error(f"Error fetching ISBN data: {e}")
        return None


FORMATS = ["NA", "Audiobook", "Hardcover", "Paperback", "pdf"]

# Tabs
tab1, tab2, tab3 = st.tabs(["📖 bookz", "⭐ reviewz", "⚙️ manage"])

# --- BOOKS TAB ---
with tab1:
    st.header("Add a new book")

    isbn = st.text_input("ISBN (optional, press Enter to fetch details)")

    default_title = ""
    default_author = ""
    default_cover = None

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
        book_format = st.selectbox("Format", FORMATS)
        start_date = st.date_input("Start Date (optional)", value=None, key="start_date")
        end_date = st.date_input("End Date (optional)", value=None, key="end_date")
        submitted = st.form_submit_button("Add Book")

        if submitted and title and author:
            conn = get_connection()
            next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
            conn.execute(
                "INSERT INTO books (id, username, title, author, format, start_date, end_date, isbn) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [next_id, username, title, author, book_format, start_date, end_date, isbn],
            )
            conn.close()
            st.success(f"Book '{title}' added!")

    # Bulk Import CSV
    st.subheader("📥 Bulk Import Books (CSV)")
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

    # NOTE: the uploader keeps its file across reruns, so import only on an
    # explicit button click (otherwise every interaction would re-import it).
    if uploaded_file is not None and st.button("Import CSV"):
        try:
            try:
                df = pd.read_csv(uploaded_file)
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding="latin1")

            df.columns = [c.strip().lower() for c in df.columns]
            required = {"title", "author"}
            if not required.issubset(set(df.columns)):
                st.error(f"CSV must include at least: {required}")
            else:
                conn = get_connection()
                for _, row in df.iterrows():
                    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]

                    csv_start = None
                    csv_end = None
                    if "start_date" in df.columns and pd.notna(row.get("start_date")):
                        csv_start = pd.to_datetime(row["start_date"], errors="coerce")
                    if "end_date" in df.columns and pd.notna(row.get("end_date")):
                        csv_end = pd.to_datetime(row["end_date"], errors="coerce")

                    conn.execute(
                        "INSERT INTO books (id, username, title, author, format, start_date, end_date, isbn) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            next_id,
                            username,
                            row.get("title"),
                            row.get("author"),
                            row.get("format", "NA"),
                            csv_start.date() if csv_start is not None and pd.notna(csv_start) else None,
                            csv_end.date() if csv_end is not None and pd.notna(csv_end) else None,
                            row.get("isbn") if "isbn" in df.columns else None,
                        ],
                    )
                conn.close()
                st.success("✅ CSV imported successfully!")
        except Exception as e:
            st.error(f"Error importing CSV: {e}")

    # All Books
    st.subheader("📚 All Books")
    conn = get_connection()
    df_all_books = conn.execute(
        "SELECT title, author, format, start_date AS 'start date', end_date AS 'end date', isbn FROM books WHERE username = ?",
        [username],
    ).fetchdf()
    conn.close()

    if not df_all_books.empty:
        st.dataframe(df_all_books, use_container_width=True)
    else:
        st.info("No books in your collection yet.")

# --- REVIEWS TAB ---
with tab2:
    st.header("Add a review")

    conn = get_connection()
    finished_books = conn.execute(
        "SELECT id, title FROM books WHERE username = ? AND end_date IS NOT NULL", [username]
    ).fetchall()
    conn.close()

    if finished_books:
        with st.form("add_review", clear_on_submit=True):
            review_book = st.selectbox("Book", finished_books, format_func=lambda b: f"{b[1]} (id={b[0]})")
            form_score = st.slider("Form", -10, 10, 0)
            function_score = st.slider("Function", -10, 10, 0)
            comment = st.text_area("Comment")
            review_submitted = st.form_submit_button("Add Review")

            if review_submitted:
                conn = get_connection()
                next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM reviews").fetchone()[0]
                conn.execute(
                    "INSERT INTO reviews (id, username, book_id, form, function, comment) VALUES (?, ?, ?, ?, ?, ?)",
                    [next_id, username, review_book[0], form_score, function_score, comment],
                )
                conn.close()
                st.success("Review added!")

    st.subheader("All Reviews")
    conn = get_connection()
    df_reviews = conn.execute(
        """
        SELECT r.id, b.title, r.form, r.function, r.comment
        FROM reviews r
        JOIN books b ON r.book_id = b.id
        WHERE r.username = ? AND b.username = ?
        """,
        [username, username],
    ).fetchdf()
    conn.close()
    st.dataframe(df_reviews, use_container_width=True)

    # Books Read by Year Chart
    st.subheader("📊 Books Read by Year")
    conn = get_connection()
    df_done = conn.execute(
        "SELECT title, end_date FROM books WHERE username = ? AND end_date IS NOT NULL", [username]
    ).fetchdf()
    conn.close()

    if not df_done.empty:
        df_done["end_date"] = pd.to_datetime(df_done["end_date"], errors="coerce")
        df_done = df_done.dropna(subset=["end_date"])

        years = sorted(df_done["end_date"].dt.year.unique(), reverse=True)
        selected_year = st.selectbox("Select year", years, index=0)

        df_year = df_done[df_done["end_date"].dt.year == selected_year].copy()

        if not df_year.empty:
            df_year["month"] = df_year["end_date"].dt.strftime("%B")
            month_order = [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            ]
            chart = (
                alt.Chart(df_year)
                .mark_bar()
                .encode(
                    x=alt.X("month:N", sort=month_order, title="Month"),
                    y=alt.Y("count():Q", title="Books Completed"),
                    tooltip=["count()", "month"],
                )
                .properties(width=600, height=400, title=f"Books Completed in {selected_year}")
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info(f"No books completed in {selected_year}.")
    else:
        st.info("No completed books recorded.")

# --- MANAGE TAB ---
with tab3:
    st.header("⚙️ Manage Books")
    show_flash()

    # Bumping this counter gives the table a fresh key, which clears its selection
    st.session_state.setdefault("manage_gen", 0)

    conn = get_connection()
    df_manage = conn.execute("SELECT * FROM books WHERE username = ?", [username]).fetchdf()
    conn.close()

    if df_manage.empty:
        st.info("No books in your collection yet.")
    else:
        query = st.text_input(
            "Search",
            placeholder="Search by title or author...",
            key="manage_search",
        )

        filtered = df_manage
        if query:
            mask = (
                df_manage["title"].str.contains(query, case=False, na=False, regex=False)
                | df_manage["author"].str.contains(query, case=False, na=False, regex=False)
            )
            filtered = df_manage[mask]

        if filtered.empty:
            st.caption("No books match that search.")
        else:
            st.caption("Click a row to edit it.")
            event = st.dataframe(
                filtered[["title", "author", "format", "start_date", "end_date"]],
                hide_index=True,
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"manage_table_{st.session_state['manage_gen']}",
            )

            selected_rows = event.selection.rows
            if selected_rows:
                book_choice = filtered.iloc[selected_rows[0]].to_dict()
                book_id = int(book_choice["id"])

                st.divider()
                st.subheader(f"{book_choice['title']} — {book_choice['author']}")

                current_format = book_choice["format"] if book_choice["format"] in FORMATS else "NA"
                new_format = st.selectbox(
                    "Format",
                    FORMATS,
                    index=FORMATS.index(current_format),
                    key=f"fmt_{book_id}",
                )
                new_start = st.date_input(
                    "Start Date",
                    value=None if pd.isna(book_choice["start_date"]) else pd.to_datetime(book_choice["start_date"]).date(),
                    key=f"start_{book_id}",
                )
                new_end = st.date_input(
                    "End Date",
                    value=None if pd.isna(book_choice["end_date"]) else pd.to_datetime(book_choice["end_date"]).date(),
                    key=f"end_{book_id}",
                )
                new_isbn = st.text_input(
                    "ISBN",
                    value="" if pd.isna(book_choice["isbn"]) else book_choice["isbn"],
                    key=f"isbn_{book_id}",
                )

                save_col, delete_col, _ = st.columns([1, 1, 4])

                if save_col.button("💾 Save Changes", key=f"save_{book_id}"):
                    conn = get_connection()
                    conn.execute(
                        "UPDATE books SET format=?, start_date=?, end_date=?, isbn=? WHERE id=? AND username=?",
                        [new_format, new_start, new_end, new_isbn, book_id, username],
                    )
                    conn.close()
                    flash(f"Updated '{book_choice['title']}'")
                    st.session_state["manage_gen"] += 1
                    st.rerun()

                if delete_col.button("🗑️ Delete Book", key=f"delete_{book_id}"):
                    conn = get_connection()
                    conn.execute("DELETE FROM reviews WHERE book_id=? AND username=?", [book_id, username])
                    conn.execute("DELETE FROM books WHERE id=? AND username=?", [book_id, username])
                    conn.close()
                    flash(f"Deleted '{book_choice['title']}'", kind="warning")
                    st.session_state["manage_gen"] += 1
                    st.rerun()

    st.subheader("⚠️ Danger Zone")
    with st.expander("Delete ALL Books"):
        st.warning("This will remove ALL books and reviews from your library. This cannot be undone!")
        confirm = st.checkbox("Yes, I understand. Delete everything.")
        if st.button("🗑️ Delete ALL Books") and confirm:
            conn = get_connection()
            conn.execute("DELETE FROM reviews WHERE username=?", [username])
            conn.execute("DELETE FROM books WHERE username=?", [username])
            conn.close()
            flash("✅ All books and reviews have been deleted.")
            st.session_state["manage_gen"] += 1
            st.rerun()
