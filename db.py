import duckdb
import streamlit as st
import os

# ------------------------------
# Connection
# ------------------------------
def get_connection():
    """
    Connect to MotherDuck (cloud) or local dev via env variable.
    """
    token = st.secrets.get("motherduck_token") or os.getenv("MOTHERDUCK_TOKEN")
    return duckdb.connect("md:bookz", config={"motherduck_token": token})


# ------------------------------
# Initialize DB
# ------------------------------
def init_db():
    conn = get_connection()

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
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
    """)

    conn.close()


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