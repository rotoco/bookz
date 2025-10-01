import duckdb

def get_connection():
    return duckdb.connect(database="bookz.duckdb", read_only=False)

def init_db():
    conn = get_connection()

    # --- Books Table ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            author TEXT,
            format TEXT,
            start_date DATE,
            end_date DATE,
            isbn TEXT,
            username TEXT
        )
    """)

    # --- Reviews Table ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            form INTEGER,
            function INTEGER,
            comment TEXT,
            username TEXT,
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
    """)

    # --- Migration: Add username column if missing ---
    books_cols = [row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()]
    if "username" not in books_cols:
        conn.execute("ALTER TABLE books ADD COLUMN username TEXT")

    reviews_cols = [row[1] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()]
    if "username" not in reviews_cols:
        conn.execute("ALTER TABLE reviews ADD COLUMN username TEXT")

    # --- Migration: Add form/function columns if missing (defensive check) ---
    if "form" not in reviews_cols:
        conn.execute("ALTER TABLE reviews ADD COLUMN form INTEGER")
    if "function" not in reviews_cols:
        conn.execute("ALTER TABLE reviews ADD COLUMN function INTEGER")

    conn.close()
