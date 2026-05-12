"""
Minimal Streamlit app to verify the app runs (no dependencies on Yahoo, CSV, etc.).
Run: streamlit run hello_world.py
"""
import streamlit as st

st.set_page_config(page_title="Hello", page_icon="👋", layout="centered")
st.title("Hello World")
st.write("If you see this, Streamlit is working.")
st.success("Success: your app launched correctly.")
