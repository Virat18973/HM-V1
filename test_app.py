"""Drives every page of the dashboard with Streamlit's test harness. Run:  pytest -q tests/test_app.py"""
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)


def page(fn):
    src = f"import sys\nsys.path.insert(0, {ROOT!r})\nimport views\nviews.bootstrap()\nviews.{fn}()\n"
    return AppTest.from_string(src, default_timeout=180)


def clean(at):
    assert not at.exception, [e.value for e in at.exception]


def button(at, key):
    return [b for b in at.button if b.key == key][0]


def test_full_app_loads_default_page():
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120).run()
    clean(at)
    assert any("Run combined" in b.label for b in at.button)


def test_combined_page_run_and_analyses():
    at = page("page_combined").run()
    clean(at)
    assert "Run the combined model" in " ".join(m.value for m in at.markdown)
    button(at, "run_combined").click().run()
    clean(at)
    assert not at.error
    html = " ".join(m.value for m in at.markdown)
    assert "Hot metal cost report" in html and "How this number was built" in html and "Cost per tHM, Rs" in html
    assert len(at.dataframe) >= 4
    # second run shows change badges
    at.number_input(key="c_om").set_value(1000.0).run()
    assert "Out of date" in " ".join(m.value for m in at.markdown)
    button(at, "run_combined").click().run()
    clean(at)
    assert "Change since last run" in " ".join(m.value for m in at.markdown) and "Sinter price effect" in " ".join(m.value for m in at.markdown)
    button(at, "run_scan").click().run()
    clean(at)
    button(at, "run_drv").click().run()
    clean(at)
    button(at, "sc_save").click().run()
    button(at, "sc_export").click().run()
    clean(at)
    assert [d for d in at.get("download_button")]


def test_combined_page_reports_a_failed_run():
    at = page("page_combined").run()
    sdf = at.session_state["sdf"]
    at.session_state["s_on"] = {m: (str(sdf.loc[m, "Group"]) != "Fuel") for m in sdf.index}     # no fuel for the sinter plant
    button(at, "run_combined").click().run()
    clean(at)
    assert at.error and "sinter model" in at.error[0].value.lower()
    assert "Run failed" in " ".join(m.value for m in at.markdown)


def test_sinter_page():
    at = page("page_sinter").run()
    clean(at)
    button(at, "run_sinter").click().run()
    clean(at)
    html = " ".join(m.value for m in at.markdown)
    assert "Sinter cost and chemistry" in html and "Quality goals" in html and len(at.dataframe) >= 2


def test_out_of_range_settings_are_clamped_not_fatal():
    at = page("page_sinter").run()
    at.session_state["s_set"].iol_pct = 30.0
    at.run()
    clean(at)
    assert at.session_state["s_set"].iol_pct == 8.0


def test_mbf_page():
    at = page("page_mbf").run()
    clean(at)
    button(at, "run_mbf").click().run()
    clean(at)
    html = " ".join(m.value for m in at.markdown)
    assert "Hot metal cost report" in html and len(at.dataframe) >= 2


def test_materials_pages_and_data_page():
    for fn, key in (("page_sinter_materials", "s_mat_apply"), ("page_mbf_materials", "m_mat_apply")):
        at = page(fn).run()
        clean(at)
        button(at, key).click().run()
        clean(at)
        assert at.success
    at = page("page_data").run()
    clean(at)
    assert any("Shared materials" in m.value for m in at.markdown)
    assert len(at.session_state["pairs"]) == 2


def test_shared_choice_changes_the_result():
    at = page("page_data").run()
    at.radio(key="pc_0").set_value("mbf").run()
    clean(at)
    assert at.session_state["pairs"][0].choice == "mbf"
