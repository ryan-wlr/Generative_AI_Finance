"""Minimal app: only first screen. Run: streamlit run app_minimal.py"""
import streamlit as st

st.set_page_config(page_title="Stock Analysis", page_icon=":chart_with_upwards_trend:")
st.title("📊 Financial Performance Analysis")
st.markdown("This app allows you to upload a CSV with your financial assets.")
st.markdown("## 📁 Upload your CSV file")
uploaded_file = st.file_uploader("Upload your CSV file", type=["csv"])
st.write("If you see this text, the app is working.")
