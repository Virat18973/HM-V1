"""Hospet Cost Studio: sinter model, MBF model and the combined hot metal cost model in one app.
Run:  streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Hospet Cost Studio", page_icon=":material/local_fire_department:", layout="wide",
                   initial_sidebar_state="expanded")

import views  # noqa: E402  (after set_page_config)

views.bootstrap()

pages = {
    "Combined": [st.Page(views.page_combined, title="Hot metal cost", icon=":material/account_tree:", url_path="hot-metal-cost", default=True)],
    "Sinter model": [st.Page(views.page_sinter, title="Sinter model", icon=":material/factory:", url_path="sinter-model"),
                     st.Page(views.page_sinter_materials, title="Sinter materials", icon=":material/table_chart:", url_path="sinter-materials")],
    "MBF model": [st.Page(views.page_mbf, title="MBF model", icon=":material/local_fire_department:", url_path="mbf-model"),
                  st.Page(views.page_mbf_materials, title="MBF materials", icon=":material/table_chart:", url_path="mbf-materials")],
    "Data": [st.Page(views.page_data, title="Upload and shared materials", icon=":material/upload_file:", url_path="upload")],
}
st.navigation(pages).run()
