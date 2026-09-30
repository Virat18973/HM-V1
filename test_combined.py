"""Tests for combined.py. Run:  pytest -q tests/test_combined.py
The main promise being tested: the chain reproduces the standalone engines exactly, and a change in a sinter
input reaches the hot metal cost."""
import copy
import io
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import combined as C          # noqa: E402
import optimiser as M         # noqa: E402
import optimizer as S         # noqa: E402


@pytest.fixture(scope="module")
def base():
    sdf, mdf = C.demo_sinter_df(), C.demo_mbf_df()
    on = {m: True for m in sdf.index}
    pairs = C.detect_shared(sdf, mdf)
    args = (sdf, on, mdf, C.SinterSettings(), M.Config(), C.Plan(), pairs)
    return args, C.run_chain(*args)


def rerun(args, **over):
    sdf, on, mdf, ss, cfg, plan, pairs = [copy.deepcopy(a) for a in args]
    return C.run_chain(sdf, on, mdf, ss, cfg, plan, pairs, **over)


# ---------------------------------------------------------------- engines and templates
def test_engine_versions():
    assert S.VERSION == "v42.0" and M.ENGINE_VERSION.startswith("14.0")


def test_templates_round_trip():
    d = C.demo_sinter_df()
    back = C.load_sinter_master(C.sinter_template_bytes(), "t.xlsx")
    assert list(back.index) == list(d.index)
    for c in ["Fe", "SiO2", "Al2O3", "CaO", "MgO", "LOI", "Price_Rs_t", "Available_Tonnes"]:
        assert np.allclose(back[c].astype(float), d[c].astype(float))
    m, notes = C.load_mbf_master(C.mbf_template_bytes())
    assert list(m.index) == list(C.demo_mbf_df().index)


def test_detect_shared_finds_flux():
    pairs = C.detect_shared(C.demo_sinter_df(), C.demo_mbf_df())
    assert {(p.sinter, p.mbf) for p in pairs} == {("DOLOMITE", "Dolomite"), ("LIMESTONE", "Limestone")}


# ---------------------------------------------------------------- shared materials
def test_apply_shared_choices():
    sdf, mdf = C.demo_sinter_df(), C.demo_mbf_df()
    p = C.SharedPair("LIMESTONE", "Limestone", "mbf")
    s2, m2, _ = C.apply_shared(sdf, mdf, [p])
    assert s2.loc["LIMESTONE", "CaO"] == mdf.loc["Limestone", "CaO"] == m2.loc["Limestone", "CaO"]
    assert s2.loc["LIMESTONE", "Price_Rs_t"] == mdf.loc["Limestone", "Price_Rs_t"]
    p = C.SharedPair("LIMESTONE", "Limestone", "custom", {"CaO": 50.0, "Price_Rs_t": 999.0, "Stock_t": 1234.0})
    s2, m2, _ = C.apply_shared(sdf, mdf, [p])
    assert s2.loc["LIMESTONE", "CaO"] == m2.loc["Limestone", "CaO"] == 50.0
    assert s2.loc["LIMESTONE", "Available_Tonnes"] == m2.loc["Limestone", "RM_Stock"] == 1234.0
    assert sdf.loc["LIMESTONE", "Price_Rs_t"] != 999.0            # the caller's tables are untouched
    _, _, notes = C.apply_shared(sdf, mdf, [C.SharedPair("NOPE", "Limestone")])
    assert notes and "skipped" in notes[0]


def test_compare_pair_flags_differences():
    sdf, mdf = C.demo_sinter_df(), C.demo_mbf_df()
    cmp_ = C.compare_pair(sdf, mdf, C.SharedPair("LIMESTONE", "Limestone")).set_index("Field")
    assert bool(cmp_.loc["CaO", "Differs"]) == (sdf.loc["LIMESTONE", "CaO"] != mdf.loc["Limestone", "CaO"])


# ---------------------------------------------------------------- the chain
def test_chain_runs_and_hands_off(base):
    args, r = base
    assert r.ok and r.stage == "done", r.message
    a = r.sinter.achieved
    row = r.furnace_df.loc[r.row]
    for k in C.HANDOFF_FIELDS:
        assert abs(row[k] - a[k]) < 1e-9
    assert abs(row["Price_Rs_t"] - (r.sinter.rm_cost + r.sinter.om_cost)) < 1e-6
    assert pd.isna(row["RM_Stock"]) and bool(row["Available"])
    original = args[2].loc[r.row]
    assert row["Mn"] == original["Mn"] and row["S"] == original["S"]      # trace elements carried over


def test_chain_equals_standalone_engines(base):
    """Same inputs run by hand through the two engines give the same numbers."""
    args, r = base
    sdf, on, mdf, ss, cfg, plan, pairs = args
    s2, m2, _ = C.apply_shared(sdf, mdf, pairs)
    direct_s = C.solve_sinter(C.sinter_active(s2, on), ss, r.sinter.prod_t)
    assert abs(direct_s.total_cost - r.sinter.total_cost) < 1e-9
    fdf = C.build_furnace_df(m2, r.row, direct_s, plan.sinter_moisture)
    direct_m = M.solve(fdf, C.furnace_config(cfg, plan))
    assert direct_m[0] == "Optimal" and abs(direct_m[2] - r.f_cost) < 1e-9


def test_breakdown_adds_up_to_cost(base):
    _, r = base
    assert abs(r.breakdown["Rs/tHM"].sum() - r.f_cost) < 1e-6
    assert abs(r.breakdown["Share %"].sum() - 100.0) < 1e-6
    assert r.kpis["sinter_rs_thm"] > 0 and abs(r.kpis["plan_cost"] - r.f_cost * r.plan.plan_thm) < 1e-6


def test_inputs_are_not_modified(base):
    args, _ = base
    before = [a.copy() if hasattr(a, "copy") and isinstance(a, pd.DataFrame) else a for a in args[:3]]
    sdf, on, mdf, ss, cfg, plan, pairs = [copy.deepcopy(a) for a in args]
    snap = (sdf.copy(), mdf.copy(), copy.deepcopy(ss), copy.deepcopy(cfg))
    C.run_chain(sdf, on, mdf, ss, cfg, plan, pairs)
    assert sdf.equals(snap[0]) and mdf.equals(snap[1]) and ss == snap[2]
    assert cfg.__dict__ == snap[3].__dict__


def test_sinter_price_change_reaches_hot_metal_cost(base):
    args, r0 = base
    heavy = r0.sinter.recipe.drop(index="TOTAL").sort_values("Dry Cost (Rs/t)", ascending=False).index[0]

    def dearer(s2, m2, st):
        s2.loc[heavy, "Price_Rs_t"] *= 1.20
    r1 = rerun(args, tweak=dearer)
    assert r1.ok and r1.kpis["cost_thm"] > r0.kpis["cost_thm"] + 1.0
    assert r1.kpis["sinter_rs_t"] > r0.kpis["sinter_rs_t"]


def test_om_change_is_a_pure_price_effect(base):
    """O&M changes the sinter price but not its chemistry, so the split has a known shape."""
    args, r0 = base

    def more_om(s2, m2, st):
        st.om_cost += 250.0
    r1 = rerun(args, tweak=more_om)
    d = C.compare_runs(r0, r1)
    assert abs(r1.kpis["sinter_rs_t"] - r0.kpis["sinter_rs_t"] - 250.0) < 1e-6
    assert abs(d["price_effect"] - 250.0 * r0.kpis["sinter_kg_thm"] / 1000.0) < 1e-6
    assert d["furnace_response"] <= 1e-6                       # re-optimising can only save money
    assert abs(d["price_effect"] + d["furnace_response"] - d["total"]) < 1e-9
    assert abs(d["d_fe"]) < 1e-9                               # chemistry did not move


def test_quality_change_moves_the_furnace(base):
    args, r0 = base

    def basic(s2, m2, st):
        st.targets["Basicity_min"], st.targets["Basicity_max"] = 2.0, 2.1
    r1 = rerun(args, tweak=basic)
    assert r1.ok and r1.kpis["sinter_B2"] > r0.kpis["sinter_B2"] + 0.05


def test_sinter_failure_stops_before_the_furnace():
    sdf, mdf = C.demo_sinter_df(), C.demo_mbf_df()
    on = {m: (str(sdf.loc[m, "Group"]) != "Fuel") for m in sdf.index}     # no fuel for the sinter plant
    r = C.run_chain(sdf, on, mdf, C.SinterSettings(), M.Config(), C.Plan(), C.detect_shared(sdf, mdf))
    assert not r.ok and r.stage == "sinter" and r.f_cost is None and "sinter model" in r.message.lower()


def test_furnace_failure_is_reported():
    sdf, mdf = C.demo_sinter_df(), C.demo_mbf_df()
    for m in mdf.index:
        if mdf.loc[m, "Group"] == "Fuel_Coke":
            mdf.loc[m, "Available"] = False
    r = C.run_chain(sdf, {m: True for m in sdf.index}, mdf, C.SinterSettings(), M.Config(), C.Plan(), [])
    assert not r.ok and r.stage == "furnace" and "furnace model" in r.message.lower()
    assert r.sinter is not None and r.sinter.total_cost > 0


def test_bad_inputs_stop_early():
    sdf, mdf = C.demo_sinter_df(), C.demo_mbf_df()
    r = C.run_chain(sdf, {}, mdf, C.SinterSettings(iol_pct=30.0), M.Config(), C.Plan(), [])
    assert not r.ok and r.stage == "input" and "IOL" in r.message
    r = C.run_chain(sdf, {}, mdf, C.SinterSettings(), M.Config(), C.Plan(plan_thm=0.0), [])
    assert not r.ok and "plan" in r.message.lower()
    with pytest.raises(ValueError):
        C.sinter_row_name(mdf.drop(index=["Sinter1", "Sinter2"]), C.Plan())


def test_sinter_tonnage_settles(base):
    _, r = base
    need, assumed = r.kpis["sinter_t_needed"], r.sinter.prod_t
    assert abs(need - assumed) / assumed <= 0.03 or any("stock caps may be slightly off" in n for n in r.notes)
    assert 1 <= r.passes <= 3


def test_grade_flags(base):
    _, r = base
    assert r.decision_grade == (r.sinter.status == "Optimal" and r.f_status == "Optimal")
    assert r.grade_text in ("Decision grade", "Sinter within approved tolerance", "Not decision grade")


# ---------------------------------------------------------------- stock
def test_shared_flux_needs_add_both_sides(base):
    _, r = base
    sh = r.stock[r.stock["Side"] == "Shared"]
    assert len(sh) >= 1
    assert np.allclose(sh["Need t"], sh["Sinter plant t"] + sh["Furnace t"])


def test_stock_row_status():
    r = C._stock_row("X", "Shared", 700.0, 400.0, 1000.0, 7.0)
    assert r["Status"] == "Short by 100 t" and abs(r["Cover %"] - 90.909) < 0.01 and abs(r["Days of cover"] - 1000 / (1100 / 7)) < 1e-9
    assert C._stock_row("X", "Furnace", 0.0, 500.0, 500.0, 7.0)["Status"] == "Covered"
    assert C._stock_row("X", "Furnace", 0.0, 500.0, np.nan, 7.0)["Status"] == "No stock entered"


# ---------------------------------------------------------------- scans, scenarios, export
def test_basicity_scan(base):
    args, r0 = base
    sdf, on, mdf, ss, cfg, plan, pairs = args
    d = C.basicity_scan(sdf, on, mdf, ss, cfg, plan, pairs, centres=[1.90, 2.00])
    assert list(d["Basicity target"]) == [1.90, 2.00] and d["Cost Rs/tHM"].notna().all()
    assert d.attrs["best"] in (1.90, 2.00)
    best = d.loc[d["Cost Rs/tHM"].idxmin(), "Basicity target"]
    if d["Decision grade"].all():
        assert d.attrs["best"] == best
    assert abs(d.loc[d["Basicity target"] == 1.90, "Cost Rs/tHM"].iloc[0] - r0.kpis["cost_thm"]) < 25.0    # base run sits near 1.9


def test_price_drivers(base):
    args, r0 = base
    sdf, on, mdf, ss, cfg, plan, pairs = args
    d = C.price_drivers(sdf, on, mdf, ss, cfg, plan, pairs, r0, swing=10.0, top=3)
    assert d["Swing"].is_monotonic_decreasing and "O&M cost (sinter)" in set(d["Driver"])
    om = d[d["Driver"] == "O&M cost (sinter)"].iloc[0]
    assert om["Up Rs/tHM"] > 0 > om["Down Rs/tHM"]
    with pytest.raises(ValueError):
        C.price_drivers(sdf, on, mdf, ss, cfg, plan, pairs, C.ChainResult(ok=False, stage="input"))


def test_compare_runs_needs_two_good_runs(base):
    _, r = base
    assert C.compare_runs(None, r) is None
    assert C.compare_runs(r, C.ChainResult(ok=False, stage="input")) is None
    z = C.compare_runs(r, r)
    assert z["total"] == 0 and z["price_effect"] == 0


def test_fingerprint_changes_with_any_input(base):
    args, _ = base
    f0 = C.fingerprint(*args)
    assert C.fingerprint(*copy.deepcopy(args)) == f0
    a = copy.deepcopy(args); a[3].om_cost += 1
    assert C.fingerprint(*a) != f0
    a = copy.deepcopy(args); a[0].loc["LLOYD", "Price_Rs_t"] += 1
    assert C.fingerprint(*a) != f0
    a = copy.deepcopy(args); a[6][0].choice = "mbf"
    assert C.fingerprint(*a) != f0
    a = copy.deepcopy(args); a[4].pci_fixed_kgthm += 1
    assert C.fingerprint(*a) != f0
    a = copy.deepcopy(args); a[5].plan_thm += 1
    assert C.fingerprint(*a) != f0


def test_export_workbook(base):
    from openpyxl import load_workbook
    args, r = base
    rec = [C.scenario_record("A", r)]
    wb = load_workbook(io.BytesIO(C.export_bytes(r, args[3], {"Extra": pd.DataFrame({"a": [1]})}, rec)))
    for name in ("Summary", "Sinter recipe", "Handoff", "Furnace burden", "Furnace limits", "Stock check", "Notes", "Extra", "Scenarios"):
        assert name in wb.sheetnames
    ws = wb["Summary"]
    assert ws.cell(1, 1).value == "Item" and ws.cell(2, 1).value == "Cost per tHM (Rs)"
    assert abs(ws.cell(2, 2).value - r.f_cost) < 1e-6
    with pytest.raises(ValueError):
        C.export_bytes(C.ChainResult(ok=False, stage="input"), args[3])
