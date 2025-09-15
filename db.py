import duckdb

def get_connection():
    return duckdb.connect(database="bookz.duckdb", read_only=False)

def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            author TEXT,
            format TEXT,
            start_date DATE,
            end_date DATE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            rating INTEGER,
            comment TEXT,
            FOREIGN KEY (book_id) REFERENCES books(id)
        )
    """)

    conn.execute("""
        CREATE TABLE reviews_new (
            id INTEGER PRIMARY KEY,
            book_id INTEGER NOT NULL,
            rating INTEGER,
            comment TEXT,
            FOREIGN KEY(book_id) REFERENCES books(id)
                );
    """)
    conn.execute("""
                 DROP TABLE reviews;
                 """)
    conn.execute("""
                 ALTER TABLE reviews_new RENAME TO reviews;
                 """)
    conn.close()