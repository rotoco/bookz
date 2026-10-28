import os

import duckdb
import streamlit as st

# ------------------------------
# Constants
# ------------------------------
STATUSES = ["wishlist", "not_started", "reading", "completed", "abandoned"]


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
    # Skip DDL entirely when the schema already exists, so normal
    # startups never open a catalog-altering transaction.
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('books', 'reviews')"
        ).fetchall()
    }
    if existing == {"books", "reviews"}:
        return

    # Books table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id BIGINT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            format TEXT,
            start_date DATE,
            end_date DATE,
            isbn TEXT,
            username TEXT NOT NULL,
            UNIQUE(title, author, username)
        )
    """)

    # Reviews table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
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


def init_db() -> None:
    """Kept so app.py's existing init_db() call still works; runs init once per process."""
    _shared_connection()


# ------------------------------
# Insert Functions
# ------------------------------
def insert_book(conn, title, author, username, format=None, start_date=None, end_date=None, isbn=None):
    """
    Inserts a new book with auto-incremented ID (Python-handled)
    """
    # Get next available ID
    result = conn.execute("SELECT MAX(id) FROM books").fetchone()
    next_id = (result[0] or 0) + 1

    conn.execute("""
        INSERT INTO books (id, title, author, username, format, start_date, end_date, isbn)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [next_id, title, author, username, format, start_date, end_date, isbn])

    return next_id


def insert_review(conn, book_id, username, form=None, function=None, comment=None):
    """
    Inserts a review for a given book ID
    """
    result = conn.execute("SELECT MAX(id) FROM reviews").fetchone()
    next_id = (result[0] or 0) + 1

    conn.execute("""
        INSERT INTO reviews (id, book_id, username, form, function, comment)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [next_id, book_id, username, form, function, comment])

    return next_id


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
        return f"'{status}' books shouldn't have dates."
    if status == "reading" and end_date:
        return "A book you're still reading shouldn't have an end date."
    if status in ("completed", "abandoned") and not end_date:
        return f"'{status}' books need an end date."
    return None
