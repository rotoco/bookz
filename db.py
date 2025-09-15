import duckdb

def get_connection():
    return duckdb.connect(database="bookz.duckdb", read_only=False)

def init_db():
    conn = get_connection()

    # Ensure books table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            author TEXT,
            format TEXT,
            start_date DATE,
            end_date DATE,
            isbn TEXT
        )
    """)

    # Ensure reviews table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            rating INTEGER,
            comment TEXT,
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
    """)

    # --- Migration: add isbn column if missing ---
    cols = [row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()]
    if "isbn" not in cols:
        conn.execute("ALTER TABLE books ADD COLUMN isbn TEXT")

    conn.close()
