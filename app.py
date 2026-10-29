import streamlit as st
import pandas as pd
import requests
import altair as alt
from concurrent.futures import ThreadPoolExecutor
import streamlit_authenticator as stauth

from db import (
    STATUSES,
    STATUS_LABELS,
    date_error,
    get_connection,
    infer_status,
    init_db,
    insert_book,
    insert_review,
)

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


def status_label(status):
    return STATUS_LABELS.get(status, status)


def csv_date(value):
    """Parse a CSV cell into a date, or None."""
    if value is None or pd.isna(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


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
        book_status = st.selectbox(
            "Status",
            STATUSES,
            index=STATUSES.index("not_started"),
            format_func=status_label,
        )
        start_date = st.date_input("Start Date (optional)", value=None, key="start_date")
        end_date = st.date_input("End Date (optional)", value=None, key="end_date")
        submitted = st.form_submit_button("Add Book")

        if submitted and title and author:
            problem = date_error(book_status, start_date, end_date)
            if problem:
                st.error(problem)
            else:
                conn = get_connection()
                insert_book(
                    conn,
                    title,
                    author,
                    username,
                    format=book_format,
                    start_date=start_date,
                    end_date=end_date,
                    isbn=isbn,
                    status=book_status,
                )
                conn.close()
                st.success(f"Book '{title}' added as {status_label(book_status)}!")

    # Bulk Import CSV
    st.subheader("📥 Bulk Import Books (CSV)")
    st.caption(
        "Required columns: title, author. Optional: format, status, start_date, end_date, isbn. "
        "Rows without a valid status get one inferred from the dates."
    )
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
                imported = 0
                skipped = []

                for i, row in df.iterrows():
                    row_title = row.get("title")
                    row_author = row.get("author")
                    if pd.isna(row_title) or pd.isna(row_author):
                        skipped.append(f"row {i + 2}: missing title or author")
                        continue

                    csv_start = csv_date(row.get("start_date"))
                    csv_end = csv_date(row.get("end_date"))

                    raw_status = row.get("status")
                    row_status = (
                        str(raw_status).strip().lower().replace(" ", "_")
                        if raw_status is not None and pd.notna(raw_status)
                        else ""
                    )
                    if row_status not in STATUSES:
                        row_status = infer_status(csv_start, csv_end)

                    problem = date_error(row_status, csv_start, csv_end)
                    if problem:
                        skipped.append(f"row {i + 2} ({row_title}): {problem}")
                        continue

                    row_format = row.get("format")
                    if not isinstance(row_format, str) or row_format not in FORMATS:
                        row_format = "NA"

                    raw_isbn = row.get("isbn")
                    row_isbn = None if raw_isbn is None or pd.isna(raw_isbn) else str(raw_isbn)

                    insert_book(
                        conn,
                        row_title,
                        row_author,
                        username,
                        format=row_format,
                        start_date=csv_start,
                        end_date=csv_end,
                        isbn=row_isbn,
                        status=row_status,
                    )
                    imported += 1
                conn.close()

                st.success(f"✅ Imported {imported} book(s).")
                if skipped:
                    st.warning(f"Skipped {len(skipped)} row(s):\n\n" + "\n".join(f"- {s}" for s in skipped))
        except Exception as e:
            st.error(f"Error importing CSV: {e}")

    # All Books
    st.subheader("📚 All Books")
    conn = get_connection()
    df_all_books = conn.execute(
        "SELECT title, author, status, format, start_date AS 'start date', end_date AS 'end date', isbn "
        "FROM books WHERE username = ?",
        [username],
    ).fetchdf()
    conn.close()

    if not df_all_books.empty:
        status_filter = st.selectbox(
            "Filter by status",
            ["all"] + STATUSES,
            format_func=lambda s: "all" if s == "all" else status_label(s),
            key="all_books_status_filter",
        )
        if status_filter != "all":
            df_all_books = df_all_books[df_all_books["status"] == status_filter]
        df_all_books = df_all_books.assign(status=df_all_books["status"].map(status_label))

        if df_all_books.empty:
            st.info("No books with that status.")
        else:
            st.dataframe(df_all_books, hide_index=True, use_container_width=True)
    else:
        st.info("No books in your collection yet.")

# --- REVIEWS TAB ---
with tab2:
    st.header("Add a review")

    # Completed or abandoned books are the ones with a finished story to review
    conn = get_connection()
    finished_books = conn.execute(
        "SELECT id, title FROM books WHERE username = ? AND status IN ('completed', 'abandoned')",
        [username],
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
                insert_review(
                    conn,
                    review_book[0],
                    username,
                    form=form_score,
                    function=function_score,
                    comment=comment,
                )
                conn.close()
                st.success("Review added!")
    else:
        st.info("Completed or abandoned books will show up here for review.")

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

    # Books Read by Year Chart (completed only; abandoned books don't count as read)
    st.subheader("📊 Books Read by Year")
    conn = get_connection()
    df_done = conn.execute(
        "SELECT title, end_date FROM books "
        "WHERE username = ? AND status = 'completed' AND end_date IS NOT NULL",
        [username],
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
            table_view = filtered[["title", "author", "status", "format", "start_date", "end_date"]].copy()
            table_view["status"] = table_view["status"].map(status_label)
            event = st.dataframe(
                table_view,
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

                current_start = None if pd.isna(book_choice["start_date"]) else pd.to_datetime(book_choice["start_date"]).date()
                current_end = None if pd.isna(book_choice["end_date"]) else pd.to_datetime(book_choice["end_date"]).date()

                current_status = book_choice.get("status")
                if current_status not in STATUSES:
                    current_status = infer_status(current_start, current_end)
                new_status = st.selectbox(
                    "Status",
                    STATUSES,
                    index=STATUSES.index(current_status),
                    format_func=status_label,
                    key=f"status_{book_id}",
                )

                current_format = book_choice["format"] if book_choice["format"] in FORMATS else "NA"
                new_format = st.selectbox(
                    "Format",
                    FORMATS,
                    index=FORMATS.index(current_format),
                    key=f"fmt_{book_id}",
                )
                new_start = st.date_input("Start Date", value=current_start, key=f"start_{book_id}")
                new_end = st.date_input("End Date", value=current_end, key=f"end_{book_id}")
                new_isbn = st.text_input(
                    "ISBN",
                    value="" if pd.isna(book_choice["isbn"]) else book_choice["isbn"],
                    key=f"isbn_{book_id}",
                )

                save_col, delete_col, _ = st.columns([1, 1, 4])

                if save_col.button("💾 Save Changes", key=f"save_{book_id}"):
                    problem = date_error(new_status, new_start, new_end)
                    if problem:
                        st.error(problem)
                    else:
                        conn = get_connection()
                        conn.execute(
                            "UPDATE books SET status=?, format=?, start_date=?, end_date=?, isbn=? "
                            "WHERE id=? AND username=?",
                            [new_status, new_format, new_start, new_end, new_isbn, book_id, username],
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


# =====================================================================
# secrets.toml example
# ---------------------------------------------------------------------
# Local: .streamlit/secrets.toml  (make sure it's in .gitignore!)
# Streamlit Cloud: App settings -> Secrets
#
# Generate a bcrypt hash for each password with:
#   python -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt()).decode())"
#
# [cookie]
# name = "bookz_cookie"
# key = "paste-a-long-random-string-here"   # e.g. python -c "import secrets; print(secrets.token_hex(32))"
# expiry_days = 30
#
# [credentials.usernames.alice]
# name = "Alice Smith"
# password = "$2b$12$...hash..."
#
# [credentials.usernames.roto]
# name = "roto"
# password = "$2b$12$...hash..."
#
# (keep your existing MotherDuck token wherever db.py already reads it from)
# =====================================================================
