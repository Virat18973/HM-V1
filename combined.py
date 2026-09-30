"""
combined.py - the link layer between the two existing models.

    optimizer.py  = sinter burden model (v42.0)      -> solve_blend_with_compensation()
    optimiser.py  = MBF hot-metal burden model (v11.7) -> solve()

Neither engine file is edited. This module only (1) reads and reconciles the two material tables,
(2) runs the sinter model, (3) writes its cost and chemistry into the sinter row of the furnace table,
(4) runs the furnace model on that copy, and (5) reports the chain: cost per tHM, stock check, scans.
There is no Streamlit code here, so it can be imported in a notebook or a test.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime

import numpy as np
import pandas as pd
from openpyxl.styles import Font

import optimizer as S      # sinter engine
import optimiser as M      # MBF engine

# Both engines keep some state at module level. One lock around every chain run keeps two users apart.
LOCK = threading.RLock()

HANDOFF_FIELDS = ["Fe", "CaO", "MgO", "SiO2", "Al2O3"]
SHARED_FIELDS = ["Fe", "SiO2", "Al2O3", "CaO", "MgO", "Moisture_Pct", "Price_Rs_t"]
GOOD_FURNACE = ("Optimal",)


# ================================================================ settings
@dataclass
class SinterSettings:
    """Everything the sinter model needs besides its material table. Defaults are the v42.0 engine defaults."""
    iol_pct: float = S.IOL_FINES_NOMINAL_PCT * 100.0        # % of the charged mix
    bfr_pct: float = S.BF_RETURNS_NOMINAL_PCT * 100.0       # % of the charged mix
    om_cost: float = float(S.DEFAULT_OM_COST_RS_T)          # Rs per tonne of sinter, added to raw-material cost
    horizon_days: float = float(S.DEFAULT_HORIZON_DAYS)
    stock_basis: str = S.DEFAULT_STOCK_BASIS                # "as_received" | "dry"
    inventory_weight: float = float(S.DEFAULT_INVENTORY_WEIGHT)
    max_flux_pct: float = S.MAX_FLUX_PORTION * 100.0
    apply_tech_ores: bool = False
    float_returns: bool = False
    targets: dict = field(default_factory=lambda: dict(S.TARGETS))
    tolerances: dict = field(default_factory=lambda: dict(S.DEFAULT_TOLERANCES))

    def problems(self):
        p = []
        if not (S.IOL_MIN_PCT <= self.iol_pct <= S.IOL_MAX_PCT):
            p.append(f"IOL fines must be {S.IOL_MIN_PCT:g} to {S.IOL_MAX_PCT:g} % of the charged mix.")
        if not (S.BFR_MIN_PCT <= self.bfr_pct <= S.BFR_MAX_PCT):
            p.append(f"BF returns must be {S.BFR_MIN_PCT:g} to {S.BFR_MAX_PCT:g} % of the charged mix.")
        if self.om_cost < 0:
            p.append("O&M cost cannot be negative.")
        if self.horizon_days <= 0:
            p.append("Horizon must be above zero days.")
        return p

    def kwargs(self):
        tech = ("Flux", "Recycle") + (("Iron_ore", "Fuel") if self.apply_tech_ores else ())
        return dict(
            iol_nominal=self.iol_pct / 100.0, bf_nominal=self.bfr_pct / 100.0,
            fuel_ash_settings=copy.deepcopy(S.DEFAULT_FUEL_ASH_SETTINGS),
            inventory_weight=float(self.inventory_weight), apply_tech_limits_to=tech,
            stock_basis=self.stock_basis, max_flux_portion=self.max_flux_pct / 100.0,
            tolerances={k: float(v) for k, v in self.tolerances.items()},
            float_returns=bool(self.float_returns), horizon_days=float(self.horizon_days))


@dataclass
class Plan:
    """The plan and the link between the two models."""
    plan_thm: float = 9000.0            # hot metal to make over the horizon
    sinter_row: str = ""                # row of the furnace table replaced by the calculated sinter ("" = first Sinter row)
    sinter_moisture: float | None = None  # None = keep the moisture already in that row
    respect_furnace_stock: bool = False  # True = furnace burden limited by RM stock over the plan


@dataclass
class SharedPair:
    """One physical material that appears in both files."""
    sinter: str
    mbf: str
    choice: str = "sinter"              # which file's values win: "sinter" | "mbf" | "custom"
    custom: dict = field(default_factory=dict)


# ================================================================ data in / out
def demo_sinter_df():
    return S._ensure_material_role(S.get_default_chemistry().copy())


def demo_mbf_df():
    return M.demo_df()


def load_sinter_master(content: bytes, name: str = "master.xlsx"):
    return S.load_master_chemistry_excel({name: bytes(content)})


def load_mbf_master(content: bytes):
    return M.load_master(content)          # (table, notes)


def mbf_template_bytes():
    return M.template_bytes()


def sinter_template_bytes():
    """Template for the sinter master workbook, filled with the built-in demo values."""
    d = demo_sinter_df().reset_index()
    out = pd.DataFrame({
        "Material": d["Material"], "Group": d["Group"], "Material_Role": d["Material_Role"],
        "Fe_%": d["Fe"], "SiO2_%": d["SiO2"], "Al2O3_%": d["Al2O3"], "CaO_%": d["CaO"], "MgO_%": d["MgO"],
        "LOI_%": d["LOI"], "Moisture_%": d["Moisture_Pct"], "Tech_Min_kg_t": d["Tech_Min"], "Tech_Max_kg_t": d["Tech_Max"],
        "Available_Stock_t": d["Available_Tonnes"], "Price_Rs_t": d["Price_Rs_t"], "CV_kcal_kg": d["CV_kcal_kg"],
        "FC_Pct": d["FC_Pct"], "Fines_%": d["Fines_Pct"]})
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as xw:
        out.to_excel(xw, sheet_name="Materials", index=False)
        ws = xw.sheets["Materials"]
        for i, c in enumerate(out.columns, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, len(c) + 2)
    return bio.getvalue()


def sinter_active(sdf, on):
    """The sinter table with switched-off materials given zero stock (the same way the sinter dashboard does)."""
    d = sdf.copy()
    for m in d.index:
        if not on.get(m, True):
            d.loc[m, "Available_Tonnes"] = 0.0
    return d


# ================================================================ shared materials
def detect_shared(sdf, mdf):
    """Suggest pairs by matching names (case and punctuation ignored). The user confirms them."""
    mm = {M.norm(m): m for m in mdf.index}
    return [SharedPair(s, mm[M.norm(s)]) for s in sdf.index if M.norm(s) in mm]


def _stock_of(sdf, mdf, pair, side):
    v = sdf.loc[pair.sinter, "Available_Tonnes"] if side == "sinter" else mdf.loc[pair.mbf, "RM_Stock"]
    return float(v) if pd.notna(v) else np.nan


def pair_values(sdf, mdf, pair):
    """The values both models will use for this material."""
    if pair.choice == "mbf":
        src = {f: float(mdf.loc[pair.mbf, f]) for f in SHARED_FIELDS}
        stock = _stock_of(sdf, mdf, pair, "mbf")
        if np.isnan(stock):
            stock = _stock_of(sdf, mdf, pair, "sinter")
    elif pair.choice == "custom":
        src = {f: float(pair.custom.get(f, sdf.loc[pair.sinter, f])) for f in SHARED_FIELDS}
        stock = float(pair.custom.get("Stock_t", _stock_of(sdf, mdf, pair, "sinter")))
    else:
        src = {f: float(sdf.loc[pair.sinter, f]) for f in SHARED_FIELDS}
        stock = _stock_of(sdf, mdf, pair, "sinter")
        if np.isnan(stock):
            stock = _stock_of(sdf, mdf, pair, "mbf")
    src["Stock_t"] = stock
    return src


def compare_pair(sdf, mdf, pair):
    rows = []
    for f in SHARED_FIELDS:
        a, b = float(sdf.loc[pair.sinter, f]), float(mdf.loc[pair.mbf, f])
        rows.append({"Field": f, "Sinter file": a, "MBF file": b, "Differs": abs(a - b) > 1e-9})
    a, b = _stock_of(sdf, mdf, pair, "sinter"), _stock_of(sdf, mdf, pair, "mbf")
    rows.append({"Field": "Stock_t", "Sinter file": a, "MBF file": b,
                 "Differs": not (np.isnan(a) and np.isnan(b)) and not (abs(a - b) <= 1e-9)})
    return pd.DataFrame(rows)


def apply_shared(sdf, mdf, pairs):
    """Copies of both tables with every shared material set to one value. Returns (sdf, mdf, notes)."""
    s2, m2, notes = sdf.copy(), mdf.copy(), []
    for c in s2.columns:                         # prices may load as whole numbers; scans and price changes need floats
        if c not in ("Group", "Material_Role"):
            s2[c] = pd.to_numeric(s2[c], errors="coerce").astype(float)
    for c in M.NUM_COLS + M.OPT_COLS:
        if c in m2.columns:
            m2[c] = pd.to_numeric(m2[c], errors="coerce").astype(float)
    for p in pairs:
        if p.sinter not in s2.index or p.mbf not in m2.index:
            notes.append(f"Shared pair {p.sinter} / {p.mbf} skipped: one of the names is not in its file.")
            continue
        v = pair_values(s2, m2, p)
        for f in SHARED_FIELDS:
            s2.loc[p.sinter, f] = v[f]
            m2.loc[p.mbf, f] = v[f]
        if not np.isnan(v["Stock_t"]):
            s2.loc[p.sinter, "Available_Tonnes"] = v["Stock_t"]
            m2.loc[p.mbf, "RM_Stock"] = v["Stock_t"]
    return s2, m2, notes


def sinter_row_name(mdf, plan):
    rows = [m for m in mdf.index if str(mdf.loc[m, "Group"]).strip() == "Sinter"]
    if plan.sinter_row and plan.sinter_row in mdf.index:
        return plan.sinter_row
    if not rows:
        raise ValueError("The furnace table has no material in Group 'Sinter' to replace.")
    return rows[0]


# ================================================================ sinter step
@dataclass
class SinterResult:
    status: str
    blend: dict | None
    achieved: dict | None
    diagnostics: list
    report: dict
    df: pd.DataFrame
    prod_t: float
    rm_cost: float | None = None
    om_cost: float = 0.0
    total_cost: float | None = None      # Rs per tonne of sinter: raw material + O&M
    recipe: pd.DataFrame | None = None
    mix: dict | None = None
    quality: pd.DataFrame | None = None

    @property
    def grade(self):
        return {"Optimal": "Decision grade", "Relaxed": "Within approved tolerance"}.get(self.status, "Not decision grade")


def solve_sinter(sdf_active, st: SinterSettings, prod_t: float) -> SinterResult:
    prod_t = max(float(prod_t), 1.0)
    with LOCK:
        status, blend, _cost, ach, diag, _fb = S.solve_blend_with_compensation(
            sdf_active, prod_t, dict(st.targets), baseline_blend=None, **st.kwargs())
        report = dict(S.get_last_run_report())
    r = SinterResult(status, blend, ach, list(diag), report, sdf_active.copy(), prod_t, om_cost=float(st.om_cost))
    if blend and ach:
        bfr = S._bfr_name(sdf_active)
        fresh = {m: v for m, v in blend.items() if m != bfr}
        table, rm, total = S.compute_dry_cost_table(fresh, sdf_active, st.om_cost)
        r.recipe, r.rm_cost, r.total_cost = table, float(rm), float(total)
        used = report.get("returns_used") or {}
        b = S.resolve_return_sinter(sdf_active, prod_t, used.get("iol", st.iol_pct / 100.0),
                                    used.get("bfr", st.bfr_pct / 100.0), st.stock_basis)["b"]
        r.mix = S.charged_mix_summary(blend, sdf_active, b)
        r.quality = S.quality_table(ach, dict(st.targets))
    return r


# ================================================================ furnace step
def build_furnace_df(mdf, row, sres: SinterResult, sinter_moisture=None):
    """Copy of the furnace table with the sinter row replaced by the sinter model's output."""
    d = mdf.copy()
    a = sres.achieved
    for k in HANDOFF_FIELDS:
        d.loc[row, k] = float(a[k])
    d.loc[row, "Price_Rs_t"] = float(sres.total_cost)      # Rs per DRY tonne, raw material + O&M
    d.loc[row, "RM_Stock"] = np.nan                        # made on demand: no stock cap
    d.loc[row, "Available"] = True
    if sinter_moisture is not None:
        d.loc[row, "Moisture_Pct"] = float(sinter_moisture)
    return d                                               # Mn, S, FC stay as in the old row (carried over)


def furnace_config(m_cfg, plan):
    c = copy.deepcopy(m_cfg)
    c.stock_plan_hm_tonnes = float(plan.plan_thm) if plan.respect_furnace_stock else 0.0
    return c


# ================================================================ the chain
@dataclass
class ChainResult:
    ok: bool
    stage: str                          # "input" | "sinter" | "furnace" | "done"
    message: str = ""
    sinter: SinterResult | None = None
    row: str = ""
    furnace_df: pd.DataFrame | None = None
    f_status: str = ""
    f_blend: dict | None = None
    f_cost: float | None = None
    f_ach: dict | None = None
    f_diag: list = field(default_factory=list)
    f_cfg: object = None
    handoff: pd.DataFrame | None = None
    kpis: dict = field(default_factory=dict)
    breakdown: pd.DataFrame | None = None
    limits: pd.DataFrame | None = None
    stock: pd.DataFrame | None = None
    notes: list = field(default_factory=list)
    plan: Plan | None = None
    horizon_days: float = 7.0
    when: str = ""
    passes: int = 1

    @property
    def decision_grade(self):
        return bool(self.ok and self.sinter is not None and self.sinter.status == "Optimal" and self.f_status == "Optimal")

    @property
    def grade_text(self):
        if not self.ok:
            return "No result"
        if self.decision_grade:
            return "Decision grade"
        if self.f_status == "Optimal" and self.sinter is not None and self.sinter.status == "Relaxed":
            return "Sinter within approved tolerance"
        return "Not decision grade"


def run_chain(sdf, s_on, mdf, s_set: SinterSettings, m_cfg, plan: Plan, pairs=None, tweak=None) -> ChainResult:
    """Sinter model -> handoff -> furnace model. `tweak(sdf, mdf, s_set)` may edit the working copies
    after shared materials are reconciled (used by the scans)."""
    pairs = pairs or []
    res = ChainResult(ok=False, stage="input", plan=copy.deepcopy(plan), horizon_days=s_set.horizon_days,
                      when=datetime.now().strftime("%H:%M:%S"))
    probs = s_set.problems() + list(m_cfg.problems())
    if plan.plan_thm <= 0:
        probs.append("The plan (tHM) must be above zero.")
    if probs:
        res.message = " ".join(probs)
        return res
    try:
        s2, m2, notes = apply_shared(sdf, mdf, pairs)
        s_set = copy.deepcopy(s_set)
        if tweak:
            tweak(s2, m2, s_set)
        res.notes += notes
        row = sinter_row_name(m2, plan)
        res.row = row
        cfg = furnace_config(m_cfg, plan)
        prod_s = plan.plan_thm * float(cfg.ref_rates["sinter"]) / 1000.0     # first estimate of the sinter tonnes the plan needs
        s_act = sinter_active(s2, s_on)
        for pass_no in range(3):
            # The furnace decides how much sinter the plan needs, and the sinter stock caps depend on that tonnage,
            # so repeat until the two agree (normally one or two passes).
            sres = solve_sinter(s_act, s_set, prod_s)
            res.sinter, res.stage, res.passes = sres, "sinter", pass_no + 1
            if not sres.blend or sres.total_cost is None:
                res.message = ("The sinter model found no recipe (" + sres.status + "). "
                               + " ".join(str(x) for x in sres.diagnostics[:2]))
                return res
            fdf = build_furnace_df(m2, row, sres, plan.sinter_moisture)
            res.furnace_df, res.f_cfg = fdf, cfg
            with LOCK:
                fs, fb, fc, fa, fd = M.solve(fdf, cfg, explain=True)
            res.f_status, res.f_blend, res.f_cost, res.f_ach, res.f_diag = fs, fb, fc, fa, list(fd)
            if fs != "Optimal" or not fb:
                res.stage = "furnace"
                res.message = "The furnace model returned " + fs + ". " + " ".join(str(x) for x in fd[:2])
                return res
            need = float(fa["Sinter_kg"]) * plan.plan_thm / 1000.0
            if abs(need - prod_s) / max(prod_s, 1.0) <= 0.03:
                break
            prod_s = need
        old = m2.loc[row]
        cols = HANDOFF_FIELDS + ["Price_Rs_t", "Moisture_Pct", "Mn", "S", "RM_Stock"]
        res.handoff = pd.DataFrame({
            "Field": cols,
            "Furnace file (before)": [old[f] for f in cols],
            "Sinter model (used)": [fdf.loc[row, f] for f in cols],
            "Source": ["sinter model"] * 6 + ["sinter plan" if plan.sinter_moisture is not None else "kept from file",
                                              "kept from file", "kept from file", "no cap"]})
        with LOCK, M.session(cfg):
            res.breakdown = _breakdown(fb, fdf)
            res.limits = M.compliance_table(fa, fdf)
        res.kpis = _kpis(res, plan)
        res.stock = stock_check(res, s2, s_act, m2, pairs, plan, s_set)
        res.ok, res.stage = True, "done"
        res.notes += _consistency_notes(res, plan, cfg)
        return res
    except Exception as e:                                   # pragma: no cover - surfaced to the user
        res.message = f"{type(e).__name__}: {e}"
        return res


def _breakdown(blend, fdf):
    rows = []
    for m, kg in blend.items():
        if kg > 1e-6:
            rs = kg * M.eff_price(fdf, m) / 1000.0
            rows.append({"Material": m, "Group": fdf.loc[m, "Group"], "kg/tHM": kg,
                         "Price Rs/t": M.eff_price(fdf, m), "Rs/tHM": rs})
    d = pd.DataFrame(rows).sort_values("Rs/tHM", ascending=False).reset_index(drop=True)
    tot = d["Rs/tHM"].sum()
    d["Share %"] = 100.0 * d["Rs/tHM"] / tot if tot else 0.0
    return d


def _kpis(res, plan):
    a, s = res.f_ach, res.sinter
    bd = res.breakdown
    sinter_rs = float(bd.loc[bd["Group"] == "Sinter", "Rs/tHM"].sum())
    used = s.report.get("returns_used") or {}
    return {
        "cost_thm": float(res.f_cost),
        "sinter_rs_t": float(s.total_cost), "sinter_rm_rs_t": float(s.rm_cost), "sinter_om_rs_t": float(s.om_cost),
        "sinter_kg_thm": float(a["Sinter_kg"]), "sinter_rs_thm": sinter_rs,
        "coke_kg": float(a["Coke_kg"]), "sinter_share_pct": float(a["Sinter_share_pct"]),
        "slag_kg": float(a["slag_kg"]), "B2": float(a["B2"]), "MgO_pct": float(a["MgO_pct"]),
        "Al2O3_pct": float(a["Al2O3_pct"]), "S_HM_pct": float(a["S_HM_pct"]), "fuel_kg": float(a["Fuel_supplied"]),
        "sinter_Fe": float(s.achieved["Fe"]), "sinter_B2": float(s.achieved["Basicity"]),
        "plan_cost": float(res.f_cost) * plan.plan_thm,
        "sinter_t_needed": float(a["Sinter_kg"]) * plan.plan_thm / 1000.0,
        "iol_used_pct": used.get("iol", np.nan) * 100 if used else np.nan,
        "bfr_used_pct": used.get("bfr", np.nan) * 100 if used else np.nan,
    }


def _consistency_notes(res, plan, cfg):
    notes = []
    need, assumed = res.kpis["sinter_t_needed"], res.sinter.prod_t
    if assumed > 0 and abs(need - assumed) / assumed > 0.03:
        notes.append(f"The furnace needs {need:,.0f} t of sinter for the plan, but the sinter stock limits were set for "
                     f"{assumed:,.0f} t after {res.passes} passes. Sinter stock caps may be slightly off.")
    elif res.passes > 1:
        notes.append(f"The sinter stock limits were re-set to the {assumed:,.0f} t of sinter the plan needs ({res.passes} passes).")
    if not res.decision_grade:
        notes.append(f"Sinter status is {res.sinter.status}: treat the cost per tHM as an estimate, not a decision number.")
    return notes


# ================================================================ stock check
def stock_check(res, s2, s_act, m2, pairs, plan, s_set):
    """Need against stock over the plan. Shared materials add both plants' draw against one stock figure."""
    basis = s_set.stock_basis
    sinter_t = res.kpis.get("sinter_t_needed", res.f_ach["Sinter_kg"] * plan.plan_thm / 1000.0)

    def wet(kg_dry, moist):
        if basis == "dry":
            return kg_dry
        mo = float(moist) / 100.0
        return kg_dry / (1.0 - mo) if mo < 1 else kg_dry

    s_need = {}
    for m, kg in res.sinter.blend.items():
        if kg > 1e-9:
            s_need[m] = wet(kg, s_act.loc[m, "Moisture_Pct"]) * sinter_t / 1000.0
    bfr = S._bfr_name(s_act)
    if bfr and res.sinter.mix and res.sinter.mix["BFR_Poured_kg_t"] > 1e-9:
        s_need[bfr] = wet(res.sinter.mix["BFR_Poured_kg_t"], s_act.loc[bfr, "Moisture_Pct"]) * sinter_t / 1000.0
    f_need = {}
    for m, kg in res.f_blend.items():
        if kg > 1e-9 and m != res.row:
            f_need[m] = wet(kg, res.furnace_df.loc[m, "Moisture_Pct"]) * plan.plan_thm / 1000.0

    rows, used_s, used_f = [], set(), set()
    for p in pairs:
        if p.sinter in s_need or p.mbf in f_need:
            ns, nf = s_need.get(p.sinter, 0.0), f_need.get(p.mbf, 0.0)
            stock = pair_values(s2, m2, p)["Stock_t"]
            rows.append(_stock_row(p.sinter if p.sinter == p.mbf else f"{p.sinter} / {p.mbf}", "Shared", ns, nf, stock, s_set.horizon_days))
            used_s.add(p.sinter); used_f.add(p.mbf)
    for m, n in s_need.items():
        if m not in used_s:
            stock = float(s_act.loc[m, "Available_Tonnes"]) if pd.notna(s_act.loc[m, "Available_Tonnes"]) else np.nan
            rows.append(_stock_row(m, "Sinter plant", n, 0.0, stock, s_set.horizon_days))
    for m, n in f_need.items():
        if m not in used_f:
            st_ = m2.loc[m, "RM_Stock"]
            rows.append(_stock_row(m, "Furnace", 0.0, n, float(st_) if pd.notna(st_) else np.nan, s_set.horizon_days))
    d = pd.DataFrame(rows)
    order = {"Shared": 0, "Sinter plant": 1, "Furnace": 2}
    d = d.sort_values(["Side", "Need t"], key=lambda c: c.map(order) if c.name == "Side" else -c).reset_index(drop=True)
    return d


def _stock_row(name, side, ns, nf, stock, horizon):
    need = ns + nf
    if np.isnan(stock):
        status, cover, days = "No stock entered", np.nan, np.nan
    else:
        cover = 100.0 * stock / need if need > 1e-9 else np.nan
        days = stock / (need / horizon) if need > 1e-9 else np.nan
        status = "Covered" if need <= stock + 1e-6 else f"Short by {need - stock:,.0f} t"
    return {"Material": name, "Side": side, "Sinter plant t": ns, "Furnace t": nf, "Need t": need,
            "Stock t": stock, "Cover %": cover, "Days of cover": days, "Status": status}


# ================================================================ comparisons and scans
def compare_runs(prev: ChainResult, cur: ChainResult):
    """Split the change in cost per tHM between two runs. Price effect = change in sinter price x the sinter the
    old run used. Furnace response = everything else (a different sinter share, coke, flux, quality)."""
    if not (prev and cur and prev.ok and cur.ok):
        return None
    pk, ck = prev.kpis, cur.kpis
    total = ck["cost_thm"] - pk["cost_thm"]
    price_eff = (ck["sinter_rs_t"] - pk["sinter_rs_t"]) * pk["sinter_kg_thm"] / 1000.0
    return {"total": total, "price_effect": price_eff, "furnace_response": total - price_eff,
            "d_sinter_rs_t": ck["sinter_rs_t"] - pk["sinter_rs_t"], "d_sinter_kg": ck["sinter_kg_thm"] - pk["sinter_kg_thm"],
            "d_coke": ck["coke_kg"] - pk["coke_kg"], "d_share": ck["sinter_share_pct"] - pk["sinter_share_pct"],
            "d_fe": ck["sinter_Fe"] - pk["sinter_Fe"], "d_b2": ck["sinter_B2"] - pk["sinter_B2"]}


def _run_kw(res):
    return None


def basicity_scan(sdf, s_on, mdf, s_set, m_cfg, plan, pairs, centres=None, half_width=0.025, progress=None):
    """Re-run the whole chain with the sinter basicity spec centred on each value. The tolerance stays as set."""
    if centres is None:
        lo, hi = s_set.tolerances["Basicity_min"], s_set.tolerances["Basicity_max"]
        centres = [round(x, 3) for x in np.arange(lo + 0.05, hi - 0.049, 0.05)]
    rows = []
    for i, c in enumerate(centres):
        def tweak(_s, _m, st, c=c):
            st.targets["Basicity_min"] = round(c - half_width, 4)
            st.targets["Basicity_max"] = round(c + half_width, 4)
        r = run_chain(sdf, s_on, mdf, s_set, m_cfg, plan, pairs, tweak=tweak)
        row = {"Basicity target": c, "Sinter status": r.sinter.status if r.sinter else r.stage,
               "Furnace status": r.f_status or "-"}
        if r.ok:
            k = r.kpis
            row.update({"Sinter basicity": k["sinter_B2"], "Sinter Fe %": k["sinter_Fe"], "Sinter Rs/t": k["sinter_rs_t"],
                        "Cost Rs/tHM": k["cost_thm"], "Sinter share %": k["sinter_share_pct"], "Coke kg/tHM": k["coke_kg"],
                        "Decision grade": r.decision_grade})
        rows.append(row)
        if progress:
            progress((i + 1) / len(centres))
    d = pd.DataFrame(rows)
    ok = d[d.get("Cost Rs/tHM").notna()] if "Cost Rs/tHM" in d else d.iloc[0:0]
    ok = ok[ok["Decision grade"] == True] if len(ok) else ok        # noqa: E712
    d.attrs["best"] = None if ok.empty else float(ok.loc[ok["Cost Rs/tHM"].idxmin(), "Basicity target"])
    return d


def price_drivers(sdf, s_on, mdf, s_set, m_cfg, plan, pairs, base: ChainResult, swing=10.0, top=6, progress=None):
    """Change in cost per tHM for +/- swing % on each big sinter input, on O&M, and on the furnace coke and ore."""
    if not (base and base.ok):
        raise ValueError("Run the combined model first.")
    bfr = S._bfr_name(sdf)
    sb = base.sinter.recipe.drop(index="TOTAL", errors="ignore")
    big = sb.sort_values("Dry Cost (Rs/t)", ascending=False).index.tolist()
    big = [m for m in big if m != bfr][:top]
    f_coke = [m for m in base.f_blend if base.f_blend[m] > 1e-6 and str(base.furnace_df.loc[m, "Group"]) == "Fuel_Coke"]
    f_ore = [m for m in base.f_blend if base.f_blend[m] > 1e-6 and str(base.furnace_df.loc[m, "Group"]) == "Iron_ore"]
    drivers = [(f"{m} (sinter)", "s", [m]) for m in big] + [("O&M cost (sinter)", "om", [])]
    if f_coke:
        drivers.append(("Furnace coke price", "f", f_coke))
    if f_ore:
        drivers.append(("Furnace ore price", "f", f_ore))
    rows, n, done = [], len(drivers) * 2, 0
    for label, side, names in drivers:
        out = {"Driver": label}
        for tag, sign in (("Up", +1), ("Down", -1)):
            f = 1.0 + sign * swing / 100.0

            def tweak(s2, m2, st, side=side, names=names, f=f):
                if side == "s":
                    for m in names:
                        s2.loc[m, "Price_Rs_t"] *= f
                elif side == "f":
                    for m in names:
                        m2.loc[m, "Price_Rs_t"] *= f
                else:
                    st.om_cost *= f
            r = run_chain(sdf, s_on, mdf, s_set, m_cfg, plan, pairs, tweak=tweak)
            out[f"{tag} Rs/tHM"] = (r.kpis["cost_thm"] - base.kpis["cost_thm"]) if r.ok else np.nan
            done += 1
            if progress:
                progress(done / n)
        rows.append(out)
    d = pd.DataFrame(rows)
    d["Swing"] = d[["Up Rs/tHM", "Down Rs/tHM"]].abs().max(axis=1)
    return d.sort_values("Swing", ascending=False).reset_index(drop=True)


# ================================================================ scenarios, fingerprint, export
def scenario_record(name, res: ChainResult):
    k = res.kpis
    return {"Name": name, "Saved": res.when, "Cost Rs/tHM": k["cost_thm"], "Sinter Rs/t": k["sinter_rs_t"],
            "Sinter kg/tHM": k["sinter_kg_thm"], "Sinter share %": k["sinter_share_pct"], "Coke kg/tHM": k["coke_kg"],
            "Sinter Fe %": k["sinter_Fe"], "Sinter basicity": k["sinter_B2"], "Grade": res.grade_text}


def fingerprint(sdf, s_on, mdf, s_set, m_cfg, plan, pairs):
    """Changes whenever any input changes, so the dashboard can say 'rerun needed'."""
    def dfj(d):
        return d.to_json(orient="split", date_format="iso", default_handler=str)
    blob = json.dumps({"s": dfj(sdf), "on": sorted((k, bool(v)) for k, v in s_on.items()), "m": dfj(mdf),
                       "ss": asdict(s_set), "cfg": json.loads(json.dumps(m_cfg.__dict__, default=str)),
                       "plan": asdict(plan), "pairs": [asdict(p) for p in pairs]}, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()


def export_bytes(res: ChainResult, s_set: SinterSettings, extras: dict | None = None, scenarios=None):
    """One workbook: summary, both recipes, handoff, limits, stock check, and any scans that were run."""
    if not (res and res.ok):
        raise ValueError("Nothing to export: run the combined model first.")
    k = res.kpis
    summary = pd.DataFrame([
        ("Cost per tHM (Rs)", k["cost_thm"]), ("Grade", res.grade_text), ("Plan (tHM)", res.plan.plan_thm),
        ("Cost of the plan (Rs)", k["plan_cost"]), ("Sinter cost (Rs/t): raw material", k["sinter_rm_rs_t"]),
        ("Sinter cost (Rs/t): O&M", k["sinter_om_rs_t"]), ("Sinter cost (Rs/t): total", k["sinter_rs_t"]),
        ("Sinter used (kg/tHM)", k["sinter_kg_thm"]), ("Sinter cost in one tHM (Rs)", k["sinter_rs_thm"]),
        ("Sinter share of burden (%)", k["sinter_share_pct"]), ("Regular coke (kg/tHM)", k["coke_kg"]),
        ("Slag (kg/tHM)", k["slag_kg"]), ("Slag B2", k["B2"]), ("Slag MgO (%)", k["MgO_pct"]),
        ("Slag Al2O3 (%)", k["Al2O3_pct"]), ("Sinter Fe (%)", k["sinter_Fe"]), ("Sinter basicity", k["sinter_B2"]),
        ("Sinter status", res.sinter.status), ("Furnace status", res.f_status),
        ("IOL fines used (% of mix)", k["iol_used_pct"]), ("BF returns used (% of mix)", k["bfr_used_pct"]),
        ("O&M (Rs/t sinter)", s_set.om_cost), ("Horizon (days)", s_set.horizon_days), ("Run time", res.when),
        ("Furnace row replaced", res.row)], columns=["Item", "Value"])
    sheets = {"Summary": summary, "Sinter recipe": res.sinter.recipe.reset_index(names="Material"),
              "Sinter quality": res.sinter.quality, "Handoff": res.handoff,
              "Furnace burden": res.breakdown, "Furnace limits": res.limits, "Stock check": res.stock}
    if res.sinter.report.get("goal_table") is not None:
        sheets["Sinter goals"] = pd.DataFrame(res.sinter.report["goal_table"])
    for name, d in (extras or {}).items():
        if d is not None and len(d):
            sheets[name] = d
    if scenarios:
        sheets["Scenarios"] = pd.DataFrame(scenarios)
    notes = pd.DataFrame({"Notes": res.notes + res.sinter.diagnostics[:6] + res.f_diag[:8]})
    sheets["Notes"] = notes
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as xw:
        for name, d in sheets.items():
            d = d.copy()
            d.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for i, c in enumerate(d.columns, 1):
                w = max([len(str(c))] + [len(f"{v:,.2f}") if isinstance(v, (int, float, np.floating)) else len(str(v)) for v in d[c].head(60)])
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(max(10, w + 2), 60)
                ws.cell(1, i).font = Font(bold=True)
    return bio.getvalue()
