import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="📚🛢️ bookz", layout="wide")

# Initialize session state
if "books" not in st.session_state:
    st.session_state.books = pd.DataFrame(columns=[
        "Title", "Author", "Format", "Start Date", "End Date", "X", "Y"
    ])

st.title("📚🛢️ bookz")

# --- ADD A BOOK ---
with st.form("add_book"):
    title = st.text_input("Title")
    author = st.text_input("Author")
    book_format = st.selectbox("Format", ["NA", "Audiobook", "Hardcover", "Paperback", "PDF"], index=0)
    start_date = st.date_input("Start Date", value=None)
    end_date = st.date_input("End Date", value=None)

    submitted = st.form_submit_button("Add Book")
    if submitted and title and author:
        new_book = pd.DataFrame([{
            "Title": title,
            "Author": author,
            "Format": book_format,
            "Start Date": start_date,
            "End Date": end_date,
            "X": None,
            "Y": None,
        }])
        st.session_state.books = pd.concat([st.session_state.books, new_book], ignore_index=True)
        st.success(f"Book '{title}' added!")

# --- RATE A BOOK WITH QUADRANT ---
if not st.session_state.books.empty:
    st.subheader("Rate a Book")

    book_choice = st.selectbox("Select Book", st.session_state.books["Title"])

    # Make quadrant chart
    fig = px.scatter(x=[0], y=[0])  # blank chart
    fig.update_layout(
        xaxis=dict(range=[-10, 10], zeroline=True),
        yaxis=dict(range=[-10, 10], zeroline=True),
        title="Click anywhere to rate (X=Enjoyment, Y=Difficulty)",
        width=500, height=500
    )

    # Display Plotly chart with click capture
    click = st.plotly_chart(fig, on_select="ignore")  # shows chart

    st.info("👉 Streamlit doesn’t capture clicks natively in Plotly yet. As a workaround, use the sliders below.")
    x = st.slider("Enjoyment (X)", -10, 10, 0)
    y = st.slider("Difficulty (Y)", -10, 10, 0)

    if st.button("Save Rating"):
        st.session_state.books.loc[
            st.session_state.books["Title"] == book_choice, ["X", "Y"]
        ] = [x, y]
        st.success(f"Saved rating for {book_choice}: ({x}, {y})")

# --- SHOW ALL BOOKS ---
st.subheader("All Books")
st.dataframe(st.session_state.books, use_container_width=True)
