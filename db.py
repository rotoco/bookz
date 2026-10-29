import os

import duckdb
import streamlit as st

# ------------------------------
# Constants
# ------------------------------
STATUSES = ["wishlist", "not_started", "reading", "completed", "abandoned"]

STATUS_LABELS = {
    "wishlist": "want to read",
    "not_started": "not started",
    "reading": "reading",
    "completed": "completed",
    "abandoned": "abandoned",
}


# ------------------------------
# Connection
# ------------------------------
@st.cache_resource
def _shared_connection() -> duckdb.DuckDBPyConnection:
    """
    One MotherDuck connection per server process, created and initialized once.
    Streamlit serializes concurrent first calls, so sessions can't race on DDL.
    """
    token = st.secrets.get("motherduck_token") or os.getenv("MOTHERDUCK_TOKEN")
    conn = duckdb.connect("md:bookz", config={"motherduck_token": token})
    _create_tables(conn)
    return conn


def get_connection() -> duckdb.DuckDBPyConnection:
    """
    Returns a per-call cursor on the shared connection.
    Safe to close(); that only closes the cursor, not the shared connection.
    """
    return _shared_connection().cursor()


# ------------------------------
# Initialize DB
# ------------------------------
def _create_tables(conn: duckdb.DuckDBPyConnection) -> None:
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog = current_database() "
            "AND table_name IN ('books', 'reviews')"
        ).fetchall()
    }

    if "books" not in existing:
        conn.execute("""
            CREATE TABLE books (
                id BIGINT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                format TEXT,
                start_date DATE,
                end_date DATE,
                isbn TEXT,
                username TEXT NOT NULL,
                status TEXT,
                UNIQUE(title, author, username)
            )
        """)

    if "reviews" not in existing:
        conn.execute("""
            CREATE TABLE reviews (
                id BIGINT PRIMARY KEY,
                book_id BIGINT NOT NULL,
                form INTEGER,
                function INTEGER,
                comment TEXT,
                username TEXT NOT NULL,
                status TEXT,
                FOREIGN KEY (book_id) REFERENCES books(id)
            )
        """)

    _migrate_book_status(conn)


def _migrate_book_status(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Idempotent: adds books.status if missing, then backfills NULLs from dates.
    A no-op (two cheap reads) once the column exists and is fully populated.
    """
    cols = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_catalog = current_database() AND table_name = 'books'"
        ).fetchall()
    }
    if "status" not in cols:
        conn.execute("ALTER TABLE books ADD COLUMN status TEXT")

    pending = conn.execute("SELECT COUNT(*) FROM books WHERE status IS NULL").fetchone()[0]
    if pending:
        conn.execute("""
            UPDATE books
            SET status = CASE
                WHEN end_date IS NOT NULL THEN 'completed'
                WHEN start_date IS NOT NULL THEN 'reading'
                ELSE 'not_started'
            END
            WHERE status IS NULL
        """)


def init_db() -> None:
    """Kept so app.py's init_db() call still works; runs init once per process."""
    _shared_connection()


# ------------------------------
# Insert Functions
# ------------------------------
def insert_book(
    conn,
    title,
    author,
    username,
    format=None,
    start_date=None,
    end_date=None,
    isbn=None,
    status=None,
):
    """
    Inserts a new book with auto-incremented ID (Python-handled).
    If status is None it is inferred from the dates.
    """
    if status is None:
        status = infer_status(start_date, end_date)

    next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM books").fetchone()[0]

    conn.execute("""
        INSERT INTO books (id, title, author, username, format, start_date, end_date, isbn, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [next_id, title, author, username, format, start_date, end_date, isbn, status])

    return next_id


def insert_review(conn, book_id, username, form=None, function=None, comment=None):
    """
    Inserts a review for a given book ID
    """
    next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM reviews").fetchone()[0]

    conn.execute("""
        INSERT INTO reviews (id, book_id, username, form, function, comment)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [next_id, book_id, username, form, function, comment])

    return next_id


# ------------------------------
# Status rules
# ------------------------------
def infer_status(start_date, end_date) -> str:
    """Same rules as the one-time backfill; used for CSV rows with no status."""
    if end_date is not None:
        return "completed"
    if start_date is not None:
        return "reading"
    return "not_started"


def date_error(status: str, start_date, end_date) -> str | None:
    """Return a message if the dates don't fit the status, else None."""
    if status in ("wishlist", "not_started") and (start_date or end_date):
        return f"'{STATUS_LABELS[status]}' books shouldn't have dates."
    if status == "reading" and end_date:
        return "A book you're still reading shouldn't have an end date."
    if status in ("completed", "abandoned") and not end_date:
        return f"'{STATUS_LABELS[status]}' books need an end date."
    return None
