"""All pages of the dashboard. Every page calls the engines through combined.py or directly; nothing here solves a model itself."""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import combined as C
import optimiser as M
import optimizer as S
import ui


# ================================================================ state
def bootstrap():
    ss = st.session_state
    ui.inject_css()
    if "init" in ss:
        return
    ss.sdf, ss.mdf = C.demo_sinter_df(), C.demo_mbf_df()
    ss.s_on = {m: True for m in ss.sdf.index}
    ss.s_name = ss.m_name = "Built-in demo data"
    ss.s_set, ss.m_cfg, ss.plan = C.SinterSettings(), M.Config(), C.Plan()
    ss.s_prod = float(S.DEFAULT_PLANNING_TONNES)
    ss.pairs = C.detect_shared(ss.sdf, ss.mdf)
    ss.chain = ss.last_ok = ss.prev_ok = None
    ss.run_fp = ""
    ss.scan = ss.drivers = None
    ss.scenarios = []
    ss.s_res = ss.m_res = None
    ss.export = None
    ss.init = True


def fp_now():
    ss = st.session_state
    return C.fingerprint(ss.sdf, ss.s_on, ss.mdf, ss.s_set, ss.m_cfg, ss.plan, ss.pairs)


def num(label, obj, attr, key, lo=None, hi=None, step=None, fmt=None, scale=1.0, help=None, box=st):
    cur = float(getattr(obj, attr)) * scale
    if lo is not None:
        cur = max(cur, float(lo))
    if hi is not None:
        cur = min(cur, float(hi))
    v = box.number_input(label, value=cur, min_value=lo, max_value=hi, step=step, format=fmt, key=key, help=help)
    setattr(obj, attr, float(v) / scale)


def chk(label, obj, attr, key, help=None, box=st):
    setattr(obj, attr, bool(box.checkbox(label, value=bool(getattr(obj, attr)), key=key, help=help)))


def is_demo():
    return st.session_state.s_name.startswith("Built-in") or st.session_state.m_name.startswith("Built-in")


def demo_notice():
    if is_demo():
        st.markdown(ui.tag("Demo data: prices and assays are placeholders. Upload your two workbooks on the Upload and shared materials page.", "warn"),
                    unsafe_allow_html=True)


def status_style(v):
    v = str(v)
    if v.startswith(("Covered", "Optimal", "Met", "OK", "Decision")):
        return "color: #22c55e"
    if v.startswith(("Short", "OUT", "Infeasible", "Not decision")):
        return "color: #ef5350"
    if v.startswith(("AT LIMIT", "Relaxed", "Check", "NOTE", "No stock", "Within")):
        return "color: #f0a93b"
    return ""


def show(df, fmt=None, status=(), height=None, hide_index=True):
    d = df.copy()
    sty = d.style
    if fmt:
        sty = sty.format(fmt, na_rep="-")
    for c in status:
        if c in d.columns:
            sty = sty.map(status_style, subset=[c])
    kw = {} if height is None else {"height": height}
    st.dataframe(sty, hide_index=hide_index, width="stretch", **kw)


# ================================================================ runs
def run_combined():
    ss = st.session_state
    with st.spinner("Running the sinter model, then the furnace model..."):
        res = C.run_chain(ss.sdf, ss.s_on, ss.mdf, ss.s_set, ss.m_cfg, ss.plan, ss.pairs)
    ss.chain, ss.run_fp = res, fp_now()
    if res.ok:
        ss.prev_ok, ss.last_ok = ss.last_ok, res
    ss.export = None


# ================================================================ COMBINED
def page_combined():
    ss = st.session_state
    demo_notice()
    h1, h2, h3 = st.columns([5, 2.2, 1.4], vertical_alignment="center")
    h1.markdown("## Hot metal cost")
    h1.caption("The sinter plant feeds the blast furnace. One run solves both, in order.")
    tag_slot = h2.empty()
    run_clicked = h3.button("Run combined", type="primary", width="stretch", key="run_combined")

    with st.container(border=True):
        ui.panel_title("Inputs used in this run", "Editable here or on the Sinter and MBF pages: they share one set of settings.",
                       chip=f"Sinter file: {ss.s_name}  |  MBF file: {ss.m_name}")
        a, b, c, d, e = st.columns(5)
        num("BF returns, % of charged mix", ss.s_set, "bfr_pct", "c_bfr", S.BFR_MIN_PCT, S.BFR_MAX_PCT, 0.5, "%.1f", box=a)
        num("IOL fines, % of charged mix", ss.s_set, "iol_pct", "c_iol", S.IOL_MIN_PCT, S.IOL_MAX_PCT, 0.5, "%.1f", box=b)
        num("O&M cost, Rs per t sinter", ss.s_set, "om_cost", "c_om", 0.0, None, 50.0, "%.0f", box=c)
        num("Plan, tHM", ss.plan, "plan_thm", "c_plan", 1.0, None, 500.0, "%.0f", box=d)
        num("Horizon, days", ss.s_set, "horizon_days", "c_hor", 1.0, 365.0, 1.0, "%.0f", box=e)

    if run_clicked:
        run_combined()
    chain = ss.chain
    stale = chain is not None and ss.run_fp != fp_now()
    if chain is None:
        tag_slot.markdown(ui.tag("Not run yet"), unsafe_allow_html=True)
    elif stale:
        tag_slot.markdown(ui.tag("Out of date: rerun needed", "warn"), unsafe_allow_html=True)
    elif chain.ok:
        tag_slot.markdown(ui.tag("Up to date", "ok"), unsafe_allow_html=True)
    else:
        tag_slot.markdown(ui.tag("Run failed", "bad"), unsafe_allow_html=True)

    if chain is None:
        st.markdown('<div class="empty"><b>Run the combined model</b>Press Run combined. Nothing needs to be run on the Sinter or MBF pages first.</div>',
                    unsafe_allow_html=True)
        return
    if not chain.ok:
        st.error(chain.message or "The run did not finish.")
        if chain.sinter is not None and chain.stage == "sinter":
            with st.expander("What the sinter model reported"):
                for x in chain.sinter.diagnostics[:10]:
                    st.write("- " + str(x))
        elif chain.f_diag:
            with st.expander("What the furnace model reported"):
                for x in chain.f_diag[:10]:
                    st.write("- " + str(x))
        return

    k, s = chain.kpis, chain.sinter
    cmp_ = C.compare_runs(ss.prev_ok, ss.last_ok) if chain is ss.last_ok else None
    if not chain.decision_grade:
        st.warning(f"{chain.grade_text}: the sinter model returned '{s.status}'. Read the cost per tHM as an estimate.")

    # ---- headline
    with st.container(border=True):
        ui.panel_title("Hot metal cost report", f"One tonne of hot metal, run at {chain.when}",
                       chip=f"Sinter: {s.status}  |  Furnace: {chain.f_status}")
        ui.stats([
            ui.stat("Cost per tHM, Rs", ui.n0(k["cost_thm"]), ui.pill(cmp_["total"] if cmp_ else None, True, ui.n0)),
            ui.stat("Sinter cost, Rs per t", ui.n0(k["sinter_rs_t"]), ui.pill(cmp_["d_sinter_rs_t"] if cmp_ else None, True, ui.n0)),
            ui.stat("Sinter share of burden", f"{k['sinter_share_pct']:.1f}%", ui.pill(cmp_["d_share"] if cmp_ else None, None, ui.n1, " pt")),
            ui.stat("Regular coke, kg per tHM", ui.n1(k["coke_kg"]), ui.pill(cmp_["d_coke"] if cmp_ else None, True, ui.n1, " kg")),
            ui.stat("Sinter used, kg per tHM", ui.n0(k["sinter_kg_thm"]), small=True),
            ui.stat("Sinter cost in one tHM, Rs", ui.n0(k["sinter_rs_thm"]), small=True),
            ui.stat("Slag, kg per tHM", ui.n0(k["slag_kg"]), small=True),
            ui.stat("Cost of the plan, Rs crore", f"{k['plan_cost'] / 1e7:,.2f}", small=True)])
        if not cmp_:
            st.caption("Change badges appear from the second run onwards.")

    # ---- basicity scan
    with st.container(border=True):
        sc = ss.scan
        ui.panel_title("Cost per tHM against sinter basicity",
                       "Runs the sinter plant and the furnace at each basicity target, so you see the sinter quality that is cheapest for the furnace.",
                       chip=("Out of date" if sc and sc["fp"] != fp_now() else "Basicity spec centred on each value"))
        if st.button("Run basicity scan", key="run_scan"):
            bar = st.progress(0.0, text="Scanning sinter basicity...")
            df = C.basicity_scan(ss.sdf, ss.s_on, ss.mdf, ss.s_set, ss.m_cfg, ss.plan, ss.pairs, progress=lambda f: bar.progress(f))
            bar.empty()
            ss.scan = sc = {"df": df, "fp": fp_now()}
        if sc:
            df = sc["df"]
            ok = df[df["Cost Rs/tHM"].notna()] if "Cost Rs/tHM" in df else df.iloc[0:0]
            if ok.empty:
                st.info("No basicity target gave a furnace-feasible result.")
            else:
                best = df.attrs.get("best")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=ok["Basicity target"], y=ok["Cost Rs/tHM"], mode="lines+markers", name="Cost per tHM (Rs)",
                                         line=dict(color=ui.BLUE, width=2.4), fill="tozeroy", fillcolor="rgba(47,107,255,0.10)"))
                fig.add_trace(go.Scatter(x=ok["Basicity target"], y=ok["Sinter Rs/t"], mode="lines", name="Sinter cost (Rs per t)", yaxis="y2",
                                         line=dict(color=ui.DIM, width=1.6, dash="dot")))
                if best is not None:
                    row = ok[ok["Basicity target"] == best].iloc[0]
                    fig.add_trace(go.Scatter(x=[best], y=[row["Cost Rs/tHM"]], mode="markers", name="Lowest cost",
                                             marker=dict(size=12, color=ui.CARD, line=dict(color=ui.BLUE2, width=2.5))))
                lo, hi = ok["Cost Rs/tHM"].min(), ok["Cost Rs/tHM"].max()
                pad = max((hi - lo) * 0.6, 15)
                fig.update_layout(yaxis=dict(range=[lo - pad, hi + pad], title="Rs per tHM"),
                                  yaxis2=dict(overlaying="y", side="right", showgrid=False, title="Rs per t sinter"),
                                  xaxis=dict(title="Sinter basicity target (B2)"))
                st.plotly_chart(ui.style_fig(fig, 300), width="stretch")
                if best is not None:
                    row = ok[ok["Basicity target"] == best].iloc[0]
                    st.caption(f"Lowest decision-grade cost: basicity {best:.2f}, Rs {row['Cost Rs/tHM']:,.0f} per tHM, sinter share {row['Sinter share %']:.1f}%.")
                    if best in (float(df["Basicity target"].min()), float(df["Basicity target"].max())):
                        st.caption("The lowest point is at the edge of the scanned range, which the approved basicity tolerance sets "
                                   "(Sinter model, Quality targets and approved tolerances). The scan cannot say whether going further would be cheaper or less safe.")
                else:
                    st.caption("No target gave a decision-grade sinter result, so no minimum is marked.")
            with st.expander("Scan table"):
                show(df, {"Basicity target": "{:.2f}", "Sinter basicity": "{:.2f}", "Sinter Fe %": "{:.2f}", "Sinter Rs/t": "{:,.0f}",
                          "Cost Rs/tHM": "{:,.0f}", "Sinter share %": "{:.1f}", "Coke kg/tHM": "{:.1f}"}, status=("Sinter status", "Furnace status"))

    # ---- how the number was built
    with st.container(border=True):
        ui.panel_title("How this number was built", "What the sinter plant hands to the furnace on every run",
                       chip=f"Replaces furnace row: {chain.row}")
        h = chain.handoff.set_index("Field")["Sinter model (used)"]
        ui.relay([("Raw material", f"Rs {ui.n0(k['sinter_rm_rs_t'])}/t"), ("O&M", f"Rs {ui.n0(k['sinter_om_rs_t'])}/t"),
                  ("Fe, basicity", f"{k['sinter_Fe']:.2f} %, {k['sinter_B2']:.2f}")],
                 [("Price", f"Rs {ui.n0(h['Price_Rs_t'])}/t"), ("CaO, SiO2", f"{h['CaO']:.2f} %, {h['SiO2']:.2f} %"),
                  ("Al2O3, MgO", f"{h['Al2O3']:.2f} %, {h['MgO']:.2f} %"), ("Stock cap", "none (made on demand)")],
                 [("Sinter", f"{ui.n0(k['sinter_kg_thm'])} kg/tHM"), ("Regular coke", f"{ui.n1(k['coke_kg'])} kg/tHM"),
                  ("Cost per tHM", f"Rs {ui.n0(k['cost_thm'])}")])
        with st.expander("Handoff table: furnace file before, sinter model used"):
            show(chain.handoff, {"Furnace file (before)": "{:,.3f}", "Sinter model (used)": "{:,.3f}"})

    # ---- breakdown, change, limits
    c1, c2, c3 = st.columns([1.05, 1, 1.05])
    with c1, st.container(border=True):
        ui.panel_title("Cost breakdown", "Where each rupee of one tHM goes")
        bd = chain.breakdown
        by_g = bd.groupby("Group", sort=False)["Rs/tHM"].sum().sort_values(ascending=False)
        st.plotly_chart(ui.donut(list(by_g.index), list(by_g.values), ui.n0(k["cost_thm"]), "Rs per tHM"), width="stretch")
    with c2, st.container(border=True):
        ui.panel_title("Change since last run", "Where the difference came from")
        if cmp_:
            ui.effect_bars([("Sinter price effect", cmp_["price_effect"]), ("Furnace response", cmp_["furnace_response"]), ("Net change per tHM", cmp_["total"])])
            st.caption("Price effect = change in sinter price x the sinter the earlier run used. Furnace response = everything else: "
                       "a different sinter share, coke and flux because sinter quality moved.")
        else:
            st.caption("Change an input and press Run combined again. This panel then splits the difference in cost per tHM.")
    with c3, st.container(border=True):
        ui.panel_title("Quality limits", "The marker shows where each value landed")
        f = chain.f_cfg
        t = s_targets()
        ui.bands([ui.band("Sinter Fe, %", s.achieved["Fe"], S.FE_LOWER, S.FE_UPPER),
                  ui.band("Sinter basicity", s.achieved["Basicity"], t["Basicity_min"], t["Basicity_max"]),
                  ui.band("Sinter MgO, %", s.achieved["MgO"], t["MgO_min"], t["MgO_max"]),
                  ui.band("Furnace slag B2", k["B2"], f.basicity_min, f.basicity_max, 3),
                  ui.band("Slag MgO, %", k["MgO_pct"], f.mgo_min_pct, f.mgo_max_pct),
                  ui.band("Slag Al2O3, %", k["Al2O3_pct"], f.al2o3_min_pct, f.al2o3_max_pct),
                  ui.band("Sinter share, %", k["sinter_share_pct"], f.sinter_min * 100, f.sinter_max * 100, 1)])

    # ---- drivers and stock
    d1, d2 = st.columns(2)
    with d1, st.container(border=True):
        dr = ss.drivers
        ui.panel_title("Price drivers", "Change in Rs per tHM for a 10% swing in each big sinter input, plus O&M and furnace coke and ore",
                       chip=("Out of date" if dr and dr["fp"] != fp_now() else "10% swing"))
        if st.button("Run price drivers", key="run_drv"):
            bar = st.progress(0.0, text="Testing each price driver...")
            df = C.price_drivers(ss.sdf, ss.s_on, ss.mdf, ss.s_set, ss.m_cfg, ss.plan, ss.pairs, chain, 10.0, progress=lambda f: bar.progress(f))
            bar.empty()
            ss.drivers = dr = {"df": df, "fp": fp_now()}
        if dr:
            df = dr["df"].iloc[::-1]
            fig = go.Figure()
            fig.add_trace(go.Bar(y=df["Driver"], x=df["Up Rs/tHM"], orientation="h", name="Price +10%", marker_color=ui.BLUE))
            fig.add_trace(go.Bar(y=df["Driver"], x=df["Down Rs/tHM"], orientation="h", name="Price -10%", marker_color=ui.BLUE3))
            fig.update_layout(barmode="relative", xaxis_title="Change in Rs per tHM")
            st.plotly_chart(ui.style_fig(fig, 60 + 34 * len(df)), width="stretch")
    with d2, st.container(border=True):
        stk = chain.stock
        short = stk[stk["Status"].str.startswith("Short")]
        ui.panel_title("Stock check", "Both plants' draw over the plan against stock. Shared materials share one stock figure.",
                       chip=f"{len(short)} short" if len(short) else "All covered")
        fm = {"Sinter plant t": "{:,.0f}", "Furnace t": "{:,.0f}", "Need t": "{:,.0f}", "Stock t": "{:,.0f}", "Cover %": "{:,.0f}", "Days of cover": "{:,.0f}"}
        top = pd.concat([stk[stk["Side"] == "Shared"], short[short["Side"] != "Shared"]]).drop_duplicates()
        if len(top):
            show(top.drop(columns=["Side"]), fm, status=("Status",))
        else:
            st.caption("No shared materials are in use and nothing is short.")
        with st.expander("All materials"):
            show(stk, fm, status=("Status",))
        basis = "as received (wet)" if ss.s_set.stock_basis == "as_received" else "dry"
        st.caption(f"Tonnes are {basis}. Shared materials are set on the Upload and shared materials page.")
        for n in chain.notes:
            st.caption("Note: " + n)

    # ---- recipes
    r1, r2 = st.columns(2)
    with r1, st.container(border=True):
        ui.panel_title("Sinter recipe", "Dry kg per tonne of sinter. BF returns are poured in at zero cost and are not in the burden.",
                       chip=f"Return sinter {s.mix['Return_Sinter_Pct_of_Mix']:.1f}% of mix" if s.mix else "")
        rec = s.recipe.copy()
        rec = rec[(rec["Dry kg / t sinter"] > 1e-6) | (rec.index == "TOTAL")]
        show(rec.reset_index(names="Material"), {"Dry kg / t sinter": "{:,.1f}", "% of Burden": "{:.1f}", "Dry Cost (Rs/t)": "{:,.0f}"})
    with r2, st.container(border=True):
        ui.panel_title("Furnace burden", "Dry kg per tHM, cheapest first by cost", chip=f"Cost Rs {ui.n0(k['cost_thm'])}")
        show(chain.breakdown, {"kg/tHM": "{:,.1f}", "Price Rs/t": "{:,.0f}", "Rs/tHM": "{:,.0f}", "Share %": "{:.1f}"})

    # ---- scenarios and export
    with st.container(border=True):
        ui.panel_title("Saved scenarios", "Keep this run and compare up to three side by side")
        s1, s2, s3 = st.columns([3, 1.2, 1.6], vertical_alignment="bottom")
        name = s1.text_input("Scenario name", value=f"Run {len(ss.scenarios) + 1}", key="sc_name")
        if s2.button("Save this run", key="sc_save", width="stretch"):
            ss.scenarios.append(C.scenario_record(name, chain))
        if s3.button("Export optimised results", key="sc_export", width="stretch"):
            extras = {}
            if ss.scan:
                extras["Basicity scan"] = ss.scan["df"]
            if ss.drivers:
                extras["Price drivers"] = ss.drivers["df"]
            ss.export = C.export_bytes(chain, ss.s_set, extras, ss.scenarios)
        if ss.export:
            st.download_button("Download workbook", ss.export, file_name="hot_metal_cost_results.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="sc_dl")
        if ss.scenarios:
            df = pd.DataFrame(ss.scenarios)
            show(df, {"Cost Rs/tHM": "{:,.0f}", "Sinter Rs/t": "{:,.0f}", "Sinter kg/tHM": "{:,.0f}", "Sinter share %": "{:.1f}",
                      "Coke kg/tHM": "{:.1f}", "Sinter Fe %": "{:.2f}", "Sinter basicity": "{:.2f}"}, status=("Grade",))
            pick = st.multiselect("Compare (up to three)", df["Name"].tolist(), max_selections=3, key="sc_pick")
            if len(pick) >= 2:
                sub = df[df["Name"].isin(pick)].set_index("Name")[["Cost Rs/tHM", "Sinter Rs/t", "Sinter kg/tHM", "Sinter share %", "Coke kg/tHM"]].T
                first = sub.columns[0]
                for c in list(sub.columns[1:]):
                    sub[f"{c} vs {first}"] = sub[c] - sub[first]
                show(sub.reset_index(names="Result"))
        else:
            st.caption("No scenarios saved yet.")
    st.markdown(f'<div class="foot">Basis: one tonne of hot metal. Sinter model {S.VERSION} feeds MBF model {M.ENGINE_VERSION}.</div>', unsafe_allow_html=True)


def s_targets():
    return st.session_state.chain.sinter and st.session_state.s_set.targets


# ================================================================ SINTER
def kv_editor(title, d, key):
    df = pd.DataFrame({"Setting": list(d.keys()), "Value": [float(v) for v in d.values()]})
    out = st.data_editor(df, hide_index=True, disabled=["Setting"], key=key, width="stretch", height=min(38 * len(df) + 40, 420))
    return {k: float(v) for k, v in zip(out["Setting"], out["Value"])}


def page_sinter():
    ss = st.session_state
    demo_notice()
    h1, h2 = st.columns([6, 1.4], vertical_alignment="center")
    h1.markdown("## Sinter model")
    h1.caption(f"Least-cost sinter burden with quality goals, engine {S.VERSION}. Runs on its own here; the Combined page uses the same engine.")
    st_ = ss.s_set
    with st.container(border=True):
        ui.panel_title("Settings", "Shared with the Combined page", chip=ss.s_name)
        a, b, c, d = st.columns(4)
        num("IOL fines, % of charged mix", st_, "iol_pct", "s_iol", S.IOL_MIN_PCT, S.IOL_MAX_PCT, 0.5, "%.1f", box=a)
        num("BF returns, % of charged mix", st_, "bfr_pct", "s_bfr", S.BFR_MIN_PCT, S.BFR_MAX_PCT, 0.5, "%.1f", box=b)
        num("O&M cost, Rs per t sinter", st_, "om_cost", "s_om", 0.0, None, 50.0, "%.0f", box=c)
        num("Horizon, days", st_, "horizon_days", "s_hor", 1.0, 365.0, 1.0, "%.0f", box=d)
        e, f, g, h = st.columns(4)
        ss.s_prod = float(e.number_input("Sinter to make over the horizon, t", value=float(ss.s_prod), min_value=1.0, step=500.0, key="s_prod_in"))
        st_.stock_basis = f.selectbox("Stock is entered as", ["as_received", "dry"], index=["as_received", "dry"].index(st_.stock_basis),
                                      format_func=lambda x: "As received (wet)" if x == "as_received" else "Dry", key="s_basis")
        num("Inventory weight (0 = pure cost)", st_, "inventory_weight", "s_invw", 0.0, 1.0, 0.1, "%.1f", box=g,
            help="1.0 follows the stock ratio between ores; 0 lets cost decide.")
        num("Flux cap, % of burden", st_, "max_flux_pct", "s_flux", 1.0, 40.0, 1.0, "%.0f", box=h)
        i, j = st.columns(2)
        chk("Also apply Tech Min/Max to iron ores and coke", st_, "apply_tech_ores", "s_tech", box=i)
        chk("Let the model choose IOL and BF returns inside their ranges", st_, "float_returns", "s_float", box=j)
        with st.expander("Quality targets and approved tolerances"):
            t1, t2 = st.columns(2)
            with t1:
                st.caption("Spec (the model aims for this)")
                st_.targets = kv_editor("Targets", st_.targets, "s_targets")
            with t2:
                st.caption("Approved tolerance (a hard outer wall)")
                st_.tolerances = kv_editor("Tolerances", st_.tolerances, "s_tols")
                st.caption("Tolerances other than SiO2 max are placeholders until the plant confirms them.")
    probs = st_.problems()
    for p in probs:
        st.error(p)
    if h2.button("Run sinter model", type="primary", width="stretch", key="run_sinter", disabled=bool(probs)):
        with st.spinner("Solving the sinter burden..."):
            ss.s_res = C.solve_sinter(C.sinter_active(ss.sdf, ss.s_on), st_, ss.s_prod)
    r = ss.s_res
    if r is None:
        st.markdown('<div class="empty"><b>Run the sinter model</b>Press Run sinter model to see the recipe, quality and cost.</div>', unsafe_allow_html=True)
        return
    kind = {"Optimal": "ok", "Relaxed": "warn"}.get(r.status, "bad")
    st.markdown(ui.tag(f"{r.status}: {r.grade}", kind), unsafe_allow_html=True)
    if not r.blend:
        st.error("No recipe. " + " ".join(str(x) for x in r.diagnostics[:3]))
        return
    a = r.achieved
    with st.container(border=True):
        ui.panel_title("Sinter cost and chemistry", "Per tonne of net sinter, dry basis", chip=f"For {r.prod_t:,.0f} t")
        ui.stats([ui.stat("Total cost, Rs per t", ui.n0(r.total_cost)), ui.stat("Raw material, Rs per t", ui.n0(r.rm_cost)),
                  ui.stat("O&M, Rs per t", ui.n0(r.om_cost)), ui.stat("Fe, %", f"{a['Fe']:.2f}"),
                  ui.stat("Basicity CaO/SiO2", f"{a['Basicity']:.2f}", small=True), ui.stat("SiO2, %", f"{a['SiO2']:.2f}", small=True),
                  ui.stat("Al2O3, %", f"{a['Al2O3']:.2f}", small=True), ui.stat("MgO, %", f"{a['MgO']:.2f}", small=True)])
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        ui.panel_title("Quality goals", "Spec, what was achieved, and the approved tolerance")
        gt = r.report.get("goal_table")
        if gt is not None:
            show(pd.DataFrame(gt), {"Achieved": "{:.3f}", "Outside spec by": "{:.3f}"}, status=("Status",))
        else:
            show(r.quality, status=("Status",))
    with c2, st.container(border=True):
        ui.panel_title("Charged mix and return sinter")
        m = r.mix
        ui.stats([ui.stat("Fresh burden, kg/t", ui.n0(m["Fresh_Burden_kg_t"]), small=True), ui.stat("BFR poured, kg/t", ui.n0(m["BFR_Poured_kg_t"]), small=True),
                  ui.stat("Charged mix, kg/t", ui.n0(m["Charged_Mix_kg_t"]), small=True), ui.stat("Return sinter, % of mix", f"{m['Return_Sinter_Pct_of_Mix']:.1f}", small=True)])
        st.caption(f"BF returns {m['BFR_Pct_of_Mix']:.1f}% of mix (chemistry only, zero cost). IOL fines {m['IOL_Pct_of_Mix']:.1f}% of mix (in the burden).")
    with st.container(border=True):
        ui.panel_title("Recipe", "Dry kg per tonne of sinter")
        rec = r.recipe[(r.recipe["Dry kg / t sinter"] > 1e-6) | (r.recipe.index == "TOTAL")]
        show(rec.reset_index(names="Material"), {"Dry kg / t sinter": "{:,.1f}", "% of Burden": "{:.1f}", "Dry Cost (Rs/t)": "{:,.0f}"})
    with st.expander("Messages from the model"):
        for x in list(r.report.get("messages") or []) + r.diagnostics:
            st.write("- " + (x if isinstance(x, str) else str(x)))


def page_sinter_materials():
    ss = st.session_state
    st.markdown("## Sinter materials")
    st.caption("One row per material. Switch materials off, or edit assays, price and stock. Changes apply to every page.")
    df = ss.sdf.reset_index(names="Material")
    df.insert(1, "On", [bool(ss.s_on.get(m, True)) for m in ss.sdf.index])
    cfg = {"On": st.column_config.CheckboxColumn("On"), "Material": st.column_config.TextColumn("Material", disabled=True)}
    out = st.data_editor(df, hide_index=True, width="stretch", column_config=cfg, key="s_mat_ed", height=min(38 * len(df) + 42, 760))
    c1, c2, _ = st.columns([1.2, 1.2, 4])
    if c1.button("Apply changes", type="primary", key="s_mat_apply"):
        new = out.set_index("Material")
        on = {m: bool(v) for m, v in new["On"].items()}
        new = new.drop(columns=["On"])
        errs = []
        for c in ["Fe", "SiO2", "Al2O3", "CaO", "MgO", "LOI", "Moisture_Pct", "Available_Tonnes", "Price_Rs_t"]:
            if (pd.to_numeric(new[c], errors="coerce").isna() | (pd.to_numeric(new[c], errors="coerce") < 0)).any():
                errs.append(f"{c}: every value must be a number of zero or more.")
        if (new["Moisture_Pct"] >= 100).any():
            errs.append("Moisture must be below 100 %.")
        if errs:
            for e in errs:
                st.error(e)
        else:
            ss.sdf, ss.s_on = new, on
            st.success("Sinter materials updated.")
    if c2.button("Reset to demo data", key="s_mat_reset"):
        ss.sdf = C.demo_sinter_df()
        ss.s_on = {m: True for m in ss.sdf.index}
        ss.s_name = "Built-in demo data"
        st.rerun()


# ================================================================ MBF
def page_mbf():
    ss = st.session_state
    demo_notice()
    h1, h2 = st.columns([6, 1.4], vertical_alignment="center")
    h1.markdown("## MBF model")
    h1.caption(f"Least-cost burden for one tonne of hot metal, engine {M.ENGINE_VERSION}. Runs here on the furnace table as it stands, "
               "with the typed sinter row. The Combined page replaces that row with the sinter model's output.")
    cfg = ss.m_cfg
    with st.container(border=True):
        ui.panel_title("Settings", "Shared with the Combined page", chip=ss.m_name)
        a, b, c, d = st.columns(4)
        num("PCI, kg per tHM", cfg, "pci_fixed_kgthm", "m_pci", 0.0, 300.0, 5.0, "%.0f", box=a)
        num("Nut coke, kg per tHM", cfg, "nut_coke_kgthm", "m_nut", 0.0, 200.0, 5.0, "%.0f", box=b)
        num("Sinter share guard rail, low %", cfg, "sinter_min", "m_smin", 0.0, 100.0, 1.0, "%.0f", scale=100.0, box=c)
        num("Sinter share guard rail, high %", cfg, "sinter_max", "m_smax", 0.0, 100.0, 1.0, "%.0f", scale=100.0, box=d)
        e, f, g, h = st.columns(4)
        num("Slag B2, low", cfg, "basicity_min", "m_b2lo", 0.5, 2.0, 0.01, "%.2f", box=e)
        num("Slag B2, high", cfg, "basicity_max", "m_b2hi", 0.5, 2.0, 0.01, "%.2f", box=f)
        num("Slag MgO, low %", cfg, "mgo_min_pct", "m_mglo", 0.0, 30.0, 0.5, "%.1f", box=g)
        num("Slag MgO, high %", cfg, "mgo_max_pct", "m_mghi", 0.0, 30.0, 0.5, "%.1f", box=h)
        i, j, k_, l = st.columns(4)
        num("Slag Al2O3, low %", cfg, "al2o3_min_pct", "m_allo", 0.0, 40.0, 0.5, "%.1f", box=i)
        num("Slag Al2O3, high %", cfg, "al2o3_max_pct", "m_alhi", 0.0, 40.0, 0.5, "%.1f", box=j)
        num("Plan for stock limits, tHM (0 = off)", cfg, "stock_plan_hm_tonnes", "m_plan", 0.0, None, 500.0, "%.0f", box=k_,
            help="When above zero, each material is limited by its RM stock over this plan.")
        chk("Pin the sinter share", cfg, "sinter_manual_on", "m_pin", box=l)
        if cfg.sinter_manual_on:
            num("Pinned sinter share, %", cfg, "sinter_manual_pct", "m_pinpct", 0.0, 100.0, 1.0, "%.1f")
        st.caption("More settings (fuel-rate rules, heat balance, constants) are in the engine's Config and keep their plant defaults here.")
    probs = cfg.problems()
    for p in probs:
        st.error(p)
    if h2.button("Run MBF model", type="primary", width="stretch", key="run_mbf", disabled=bool(probs)):
        with st.spinner("Solving the furnace burden..."):
            with C.LOCK:
                res = M.solve(ss.mdf, cfg)
            lim = None
            if res[0] == "Optimal":
                with C.LOCK, M.session(cfg):
                    lim = M.compliance_table(res[3], ss.mdf)
                    bd = C._breakdown(res[1], ss.mdf)
            ss.m_res = {"res": res, "limits": lim, "bd": bd if res[0] == "Optimal" else None, "cfg": copy.deepcopy(cfg)}
    r = ss.m_res
    if r is None:
        st.markdown('<div class="empty"><b>Run the MBF model</b>Press Run MBF model to see the burden, slag and fuel rate.</div>', unsafe_allow_html=True)
        return
    status, blend, cost, ach, diag = r["res"]
    st.markdown(ui.tag(status, "ok" if status == "Optimal" else "bad"), unsafe_allow_html=True)
    if status != "Optimal":
        for x in diag[:6]:
            st.error(str(x))
        return
    with st.container(border=True):
        ui.panel_title("Hot metal cost report", "One tonne of hot metal, dry and net")
        ui.stats([ui.stat("Cost per tHM, Rs", ui.n0(cost)), ui.stat("Sinter share of burden", f"{ach['Sinter_share_pct']:.1f}%"),
                  ui.stat("Regular coke, kg per tHM", ui.n1(ach["Coke_kg"])), ui.stat("Slag, kg per tHM", ui.n0(ach["slag_kg"])),
                  ui.stat("Slag B2", f"{ach['B2']:.3f}", small=True), ui.stat("Slag MgO, %", f"{ach['MgO_pct']:.2f}", small=True),
                  ui.stat("Slag Al2O3, %", f"{ach['Al2O3_pct']:.2f}", small=True), ui.stat("Hot metal S, %", f"{ach['S_HM_pct']:.3f}", small=True)])
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        ui.panel_title("Burden", "Dry kg per tHM")
        show(r["bd"], {"kg/tHM": "{:,.1f}", "Price Rs/t": "{:,.0f}", "Rs/tHM": "{:,.0f}", "Share %": "{:.1f}"})
    with c2, st.container(border=True):
        ui.panel_title("Limits", "Each requirement against its target")
        show(r["limits"][["Requirement", "Target", "Achieved", "Status"]], status=("Status",))
    with st.expander("Messages from the model"):
        for x in diag:
            st.write("- " + str(x))


def page_mbf_materials():
    ss = st.session_state
    st.markdown("## MBF materials")
    st.caption("The furnace table. On the Combined page the Sinter row you choose is replaced by the sinter model's output on every run.")
    df = ss.mdf.reset_index(names="Material")
    cfg = {"Material": st.column_config.TextColumn("Material", disabled=True),
           "Group": st.column_config.SelectboxColumn("Group", options=M.GROUPS), "Available": st.column_config.CheckboxColumn("On")}
    out = st.data_editor(df, hide_index=True, width="stretch", column_config=cfg, key="m_mat_ed", height=min(38 * len(df) + 42, 700))
    c1, c2, _ = st.columns([1.2, 1.2, 4])
    if c1.button("Apply changes", type="primary", key="m_mat_apply"):
        new = out.set_index("Material")
        for c in M.NUM_COLS + M.OPT_COLS:
            new[c] = pd.to_numeric(new[c], errors="coerce")
        new["Available"] = new["Available"].astype(bool)
        errs = M.validate_df(new)
        if errs:
            for e in errs:
                st.error(e)
        else:
            ss.mdf = new
            st.success("Furnace materials updated.")
    if c2.button("Reset to demo data", key="m_mat_reset"):
        ss.mdf = C.demo_mbf_df()
        ss.m_name = "Built-in demo data"
        st.rerun()


# ================================================================ DATA
def load_pair(s_file, m_file):
    ss = st.session_state
    msgs = []
    try:
        if s_file is not None:
            ss.sdf = C.load_sinter_master(s_file.getvalue(), s_file.name)
            ss.s_on = {m: True for m in ss.sdf.index}
            ss.s_name = s_file.name
            msgs.append(f"Sinter file read: {len(ss.sdf)} materials.")
        if m_file is not None:
            ss.mdf, notes = C.load_mbf_master(m_file.getvalue())
            ss.m_name = m_file.name
            msgs.append(f"MBF file read: {len(ss.mdf)} materials.")
            msgs += notes
        ss.pairs = C.detect_shared(ss.sdf, ss.mdf)
        ss.plan.sinter_row = ""
        ss.chain = ss.last_ok = ss.prev_ok = ss.scan = ss.drivers = ss.s_res = ss.m_res = None
        return True, msgs
    except Exception as e:
        return False, [f"{type(e).__name__}: {e}"]


def page_data():
    ss = st.session_state
    st.markdown("## Upload and shared materials")
    st.caption("Keep your two workbooks as they are. The app reads each with its own loader, then reconciles the materials they share.")
    demo_notice()
    with st.container(border=True):
        ui.panel_title("Workbooks", "Sinter master workbook and MBF input workbook", chip=f"{ss.s_name}  |  {ss.m_name}")
        a, b = st.columns(2)
        s_file = a.file_uploader("Sinter workbook (MASTER_Chemistry)", type=["xlsx"], key="up_s")
        m_file = b.file_uploader("MBF workbook (Input_chemistry)", type=["xlsx"], key="up_m")
        c1, c2, c3, c4 = st.columns([1.3, 1.2, 1.2, 1.2])
        if c1.button("Use these files", type="primary", key="use_files", disabled=(s_file is None and m_file is None)):
            ok, msgs = load_pair(s_file, m_file)
            (st.success if ok else st.error)(" ".join(msgs[:1]))
            for m in msgs[1:]:
                st.caption(m)
        c2.download_button("Sinter template", C.sinter_template_bytes(), "Sinter_Master_Template.xlsx", key="dl_s",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        c3.download_button("MBF template", C.mbf_template_bytes(), "MBF_Input_Template.xlsx", key="dl_m",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if c4.button("Reset to demo data", key="reset_demo"):
            ss.sdf, ss.mdf = C.demo_sinter_df(), C.demo_mbf_df()
            ss.s_on = {m: True for m in ss.sdf.index}
            ss.s_name = ss.m_name = "Built-in demo data"
            ss.pairs = C.detect_shared(ss.sdf, ss.mdf)
            ss.plan.sinter_row = ""
            ss.chain = ss.last_ok = ss.prev_ok = ss.scan = ss.drivers = ss.s_res = ss.m_res = None
            st.rerun()

    with st.container(border=True):
        ui.panel_title("Shared materials", "A material that is in both files is entered twice and can disagree. Pick which values both models use.",
                       chip=f"{len(ss.pairs)} shared")
        if not ss.pairs:
            st.caption("No materials with the same name were found. Add a pair below if two differently named rows are the same physical material.")
        for i, p in enumerate(list(ss.pairs)):
            if p.sinter not in ss.sdf.index or p.mbf not in ss.mdf.index:
                continue
            cmpdf = C.compare_pair(ss.sdf, ss.mdf, p)
            diff = int(cmpdf["Differs"].sum())
            with st.expander(f"{p.sinter}  /  {p.mbf}   ({diff} fields differ)", expanded=diff > 0):
                show(cmpdf, {"Sinter file": "{:,.3f}", "MBF file": "{:,.3f}"})
                p.choice = st.radio("Values both models use", ["sinter", "mbf", "custom"], horizontal=True, key=f"pc_{i}",
                                    index=["sinter", "mbf", "custom"].index(p.choice),
                                    format_func=lambda x: {"sinter": "Sinter file", "mbf": "MBF file", "custom": "Enter new values"}[x])
                if p.choice == "custom":
                    cols = st.columns(4)
                    vals = C.pair_values(ss.sdf, ss.mdf, C.SharedPair(p.sinter, p.mbf, "sinter"))
                    for j, f in enumerate(C.SHARED_FIELDS + ["Stock_t"]):
                        cur = float(p.custom.get(f, vals[f] if not np.isnan(vals[f]) else 0.0))
                        p.custom[f] = float(cols[j % 4].number_input(f, value=cur, key=f"pcv_{i}_{f}"))
                if st.button("Remove this pair", key=f"prem_{i}"):
                    ss.pairs.pop(i)
                    st.rerun()
        x1, x2, x3 = st.columns([2, 2, 1], vertical_alignment="bottom")
        s_pick = x1.selectbox("Sinter file material", list(ss.sdf.index), key="pair_s")
        m_pick = x2.selectbox("MBF file material", list(ss.mdf.index), key="pair_m")
        if x3.button("Add pair", key="pair_add"):
            if any(q.sinter == s_pick or q.mbf == m_pick for q in ss.pairs):
                st.error("One of those materials is already in a pair.")
            else:
                ss.pairs.append(C.SharedPair(s_pick, m_pick))
                st.rerun()

    with st.container(border=True):
        ui.panel_title("How the sinter reaches the furnace", "Applies to the Combined page only")
        rows = [m for m in ss.mdf.index if str(ss.mdf.loc[m, "Group"]).strip() == "Sinter"]
        if not rows:
            st.error("The furnace table has no material in Group 'Sinter'.")
        else:
            cur = ss.plan.sinter_row if ss.plan.sinter_row in rows else rows[0]
            ss.plan.sinter_row = st.selectbox("Furnace row replaced by the calculated sinter", rows, index=rows.index(cur), key="lk_row",
                                              help="Its price, Fe, CaO, MgO, SiO2 and Al2O3 come from the sinter model; Mn, S and moisture stay as in the file.")
            l1, l2 = st.columns(2)
            use_m = l1.checkbox("Set the sinter moisture at the furnace", value=ss.plan.sinter_moisture is not None, key="lk_mo_on")
            if use_m:
                ss.plan.sinter_moisture = float(l1.number_input("Sinter moisture, %", value=float(ss.plan.sinter_moisture or ss.mdf.loc[ss.plan.sinter_row, "Moisture_Pct"]),
                                                                min_value=0.0, max_value=30.0, step=0.5, key="lk_mo"))
            else:
                ss.plan.sinter_moisture = None
                l1.caption(f"Moisture stays at {ss.mdf.loc[ss.plan.sinter_row, 'Moisture_Pct']:.1f}% from the file.")
            chk("Limit the furnace burden by RM stock over the plan", ss.plan, "respect_furnace_stock", "lk_stock", box=l2,
                help="Off matches the MBF model's default. The stock check on the Combined page always shows need against stock.")
    st.markdown(f'<div class="foot">Sinter engine {S.VERSION}. MBF engine {M.ENGINE_VERSION}. Neither engine file is edited by this app.</div>', unsafe_allow_html=True)
