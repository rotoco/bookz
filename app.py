import streamlit as st
import pandas as pd
from db import get_connection, init_db
import plotly.express as px

st.set_page_config(page_title="📚🛢️ bookz", layout="wide")

# Initialize session state
if "books" not in st.session_state:
    st.session_state.books = pd.DataFrame(columns=[
        "Title", "Author", "Format", "Start Date", "End Date", "X", "Y"
    ])

# Ensure DB is ready
init_db()
st.title("📚🛢️ bookz")

# Tabs for Books and Reviews
tab1, tab2 = st.tabs(["📖 bookz", "⭐ reviewz"])



# --- BOOKS ---
with tab1:
    st.header("Add a new book")
    # --- Add Book Form ---
    with st.form("add_book"):
        title = st.text_input("Title")
        author = st.text_input("Author")

        book_format = st.selectbox(
            "Format",
            ["Audiobook", "Hardcover", "NA", "Paperback", "pdf"],
            index=2  # default to "NA"
        )

        start_date = st.date_input("Start Date", value=None)
        end_date = st.date_input("End Date", value=None)

        submitted = st.form_submit_button("Add Book")
        if submitted and title and author:
            conn = get_connection()
            next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
            conn.execute(
                "INSERT INTO books VALUES (?, ?, ?, ?, ?, ?)",
                [
                    next_id,
                    title,
                    author,
                    book_format,
                    start_date if start_date else None,
                    end_date if end_date else None,
                ]
            )
            conn.close()
            st.success(f"Book '{title}' added!")

    # --- Bulk CSV Upload ---
    st.subheader("Bulk Upload Books via CSV")
    csv_file = st.file_uploader("Upload a CSV file", type=["csv"])
    if csv_file:
        try:
            df = pd.read_csv(csv_file)
            st.dataframe(df)  # preview

            if st.button("Import Books"):
                conn = get_connection()
                for _, row in df.iterrows():
                    title = row.get("title")
                    author = row.get("author")
                    book_format = row.get("format", "NA") or "NA"
                    start_date = row.get("start_date")
                    end_date = row.get("end_date")

                    start_date = pd.to_datetime(start_date).date() if pd.notna(start_date) else None
                    end_date = pd.to_datetime(end_date).date() if pd.notna(end_date) else None

                    next_id = conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM books").fetchone()[0]
                    conn.execute(
                        "INSERT INTO books VALUES (?, ?, ?, ?, ?, ?)",
                        [next_id, title, author, book_format, start_date, end_date]
                    )
                conn.close()
                st.success(f"Imported {len(df)} books successfully!")
        except Exception as e:
            st.error(f"Error importing CSV: {e}")

    # --- All Books Table ---
    st.subheader("All Books")
    conn = get_connection()
    df_books = conn.execute("""
        SELECT 
            id, 
            title, 
            author, 
            format, 
            start_date, 
            end_date,
            CASE
                WHEN start_date IS NULL THEN 'Not Started'
                WHEN end_date IS NULL THEN 'In Progress'
                ELSE 'Completed'
            END AS status
        FROM books
    """).fetchdf()
    conn.close()
    st.dataframe(df_books, use_container_width=True)

    # --- Manage Books ---
    st.subheader("Manage Books")
    conn = get_connection()
    books = conn.execute("SELECT id, title, format, start_date, end_date FROM books").fetchall()
    conn.close()

    if books:
        book_to_update = st.selectbox(
            "Select a book",
            books,
            format_func=lambda b: f"{b[1]} (Format: {b[2]}, Start: {b[3]}, End: {b[4]})"
        )

        current_format = book_to_update[2]
        current_start = book_to_update[3]
        current_end = book_to_update[4]

        with st.form("update_book"):
            new_format = st.selectbox(
                "New Format",
                ["Audiobook", "Hardcover", "NA", "Paperback", "pdf"],
                index=["Audiobook", "Hardcover", "NA", "Paperback", "pdf"].index(current_format)
                if current_format in ["Audiobook", "Hardcover", "NA", "Paperback", "pdf"] else 2
            )

            new_start_date = st.date_input(
                "Start Date",
                value=pd.to_datetime(current_start).date() if current_start else None
            )
            new_end_date = st.date_input(
                "End Date",
                value=pd.to_datetime(current_end).date() if current_end else None
            )

            update_submitted = st.form_submit_button("Update Book")
            if update_submitted:
                conn = get_connection()
                conn.execute(
                    "UPDATE books SET format = ?, start_date = ?, end_date = ? WHERE id = ?",
                    [
                        new_format,
                        new_start_date if new_start_date else None,
                        new_end_date if new_end_date else None,
                        book_to_update[0]
                    ]
                )
                conn.close()
                st.success(f"Updated '{book_to_update[1]}'")

    # --- Remove Book ---
    st.subheader("Remove a Book")
    conn = get_connection()
    books = conn.execute("SELECT id, title FROM books").fetchall()
    conn.close()

    if books:
        book_to_delete = st.selectbox(
            "Select a book to remove",
            books,
            format_func=lambda b: f"{b[1]} (id={b[0]})"
        )

        if st.button("Delete Book"):
            conn = get_connection()
            # Delete any reviews first
            conn.execute("DELETE FROM reviews WHERE book_id = ?", [book_to_delete[0]])
            # Delete the book
            conn.execute("DELETE FROM books WHERE id = ?", [book_to_delete[0]])
            conn.close()
            st.success(f"Deleted '{book_to_delete[1]}'")



# --- REVIEWS ---
with tab2:
    st.header("Add a review")
    conn = get_connection()
    books = conn.execute("SELECT id, title FROM books").fetchall()
    conn.close()

    if books:
        with st.form("add_review"):
            book_choice = st.selectbox("Book", books, format_func=lambda b: f"{b[1]} (id={b[0]})")
            rating = st.slider("Rating", 1, 5, 3)
            comment = st.text_area("Comment")
            submitted = st.form_submit_button("Add Review")
            if submitted:
                conn = get_connection()
                conn.execute("INSERT INTO reviews VALUES (?, ?, ?, ?)",
                             [conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM reviews").fetchone()[0],
                              book_choice[0], rating, comment])
                conn.close()
                st.success("Review added!")

    st.subheader("All Reviews")
    conn = get_connection()
    df_reviews = conn.execute("""
        SELECT r.id, b.title, r.rating, r.comment
        FROM reviews r
        JOIN books b ON r.book_id = b.id
    """).fetchdf()
    conn.close()
    st.dataframe(df_reviews, use_container_width=True)
