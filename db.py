import duckdb
import os
import streamlit as st

def get_connection():
    token = None

    # Try Streamlit secrets first (for deployment)
    if "motherduck_token" in st.secrets:
        token = st.secrets["motherduck_token"]
    else:
        # Fallback for local development
        token = os.getenv("MOTHERDUCK_TOKEN")

    return duckdb.connect(
        "md:bookz",
        config={
            "motherduck_token": token
        }
    )

def init_db():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            book_id BIGINT NOT NULL,
            form INTEGER,
            function INTEGER,
            comment TEXT,
            username TEXT NOT NULL,
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
    """)

    conn.close()