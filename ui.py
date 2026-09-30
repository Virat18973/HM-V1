"""Theme and display helpers: one dark navy look, one blue accent, status colours only where they carry meaning."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

BG, CARD, CARD2, LINE = "#070b14", "#0d1422", "#111a2c", "#18233a"
TEXT, MUTED, DIM = "#e8edf7", "#7f8ba6", "#56617a"
BLUE, BLUE2, BLUE3 = "#2f6bff", "#6f9bff", "#1b3a8f"
OK, WARN, BAD = "#22c55e", "#f0a93b", "#ef5350"
DONUT = [BLUE, BLUE2, BLUE3, "#3a4660", "#24304a", "#5b7fd6", "#8aa6e8", "#2b3b5c"]

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html, body, [class*="css"], .stApp {{ font-family: Inter, system-ui, -apple-system, "Segoe UI", sans-serif; }}
.stApp {{ background: {BG}; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1280px; }}
section[data-testid="stSidebar"] {{ background: #0a101c; border-right: 1px solid {LINE}; }}
section[data-testid="stSidebar"] a {{ border-radius: 8px; }}
h1, h2, h3, h4 {{ font-weight: 500; letter-spacing: -0.01em; color: {TEXT}; }}
h1 {{ font-size: 1.35rem; }} h2 {{ font-size: 1.1rem; }} h3 {{ font-size: 0.98rem; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"]) {{ border-radius: 12px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background: {CARD}; border-color: {LINE} !important; border-radius: 12px; }}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlockBorderWrapper"] {{ background: {CARD2}; }}
.stButton > button, .stDownloadButton > button {{ border-radius: 8px; border: 1px solid {LINE}; background: transparent; color: {TEXT}; font-weight: 500; }}
.stButton > button:hover, .stDownloadButton > button:hover {{ border-color: #26344f; background: {CARD2}; color: {TEXT}; }}
.stButton > button[kind="primary"] {{ background: {BLUE}; border: 0; color: #fff; }}
.stButton > button[kind="primary"]:hover {{ background: #4479ff; }}
div[data-baseweb="input"], div[data-baseweb="select"] > div, .stNumberInput input, .stTextInput input {{ background: {CARD2} !important; border-color: {LINE} !important; border-radius: 8px !important; }}
label, .stMarkdown p {{ color: {TEXT}; }}
[data-testid="stWidgetLabel"] p {{ color: {MUTED}; font-size: 12px; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {LINE}; }}
.stTabs [data-baseweb="tab"] {{ color: {MUTED}; }}
.stTabs [aria-selected="true"] {{ color: {TEXT}; }}
[data-testid="stExpander"] {{ border: 1px solid {LINE}; border-radius: 10px; background: {CARD}; }}
[data-testid="stDataFrame"] {{ border: 1px solid {LINE}; border-radius: 10px; }}
.ph {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin: 0 0 10px; }}
.ph .t {{ font-size: 14px; font-weight: 500; color: {TEXT}; }}
.ph .n {{ font-size: 12px; color: {MUTED}; margin-top: 2px; }}
.chip {{ border: 1px solid {LINE}; border-radius: 8px; padding: 4px 10px; color: {MUTED}; font-size: 12px; background: {CARD2}; white-space: nowrap; }}
.tag {{ display:inline-block; font-size: 11px; padding: 3px 9px; border-radius: 20px; border: 1px solid {LINE}; color: {MUTED}; }}
.tag.warn {{ color: {WARN}; border-color: #4a3812; background: #1a1408; }}
.tag.ok {{ color: {OK}; border-color: #14432a; background: #0b1c13; }}
.tag.bad {{ color: {BAD}; border-color: #4a1b1c; background: #1c0d0e; }}
.stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); row-gap: 18px; }}
.stat {{ padding: 2px 18px; border-left: 1px solid {LINE}; }}
.stat:nth-child(4n+1) {{ border-left: 0; padding-left: 0; }}
.stat .v {{ font-size: 25px; font-weight: 500; letter-spacing: -0.01em; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; color: {TEXT}; }}
.stat .l {{ color: {MUTED}; font-size: 12px; margin-top: 2px; }}
.stat.sm .v {{ font-size: 18px; }}
.pill {{ font-size: 10.5px; padding: 2px 6px; border-radius: 5px; font-weight: 500; }}
.pill.g {{ background: #0f2a1b; color: {OK}; }} .pill.r {{ background: #2a1214; color: {BAD}; }}
.pill.b {{ background: #10214d; color: {BLUE2}; }} .pill.n {{ background: {CARD2}; color: {MUTED}; }}
.relay {{ display: grid; grid-template-columns: 1fr 28px 1fr 28px 1fr; align-items: stretch; }}
.node {{ background: {CARD2}; border: 1px solid {LINE}; border-radius: 10px; padding: 12px 14px; }}
.node b {{ font-weight: 500; display: block; margin-bottom: 6px; color: {TEXT}; }}
.node div {{ display: flex; justify-content: space-between; color: {MUTED}; font-size: 12px; padding: 2px 0; gap: 8px; }}
.node div span:last-child {{ color: {TEXT}; text-align: right; }}
.arrow {{ display: grid; place-items: center; color: {BLUE2}; }}
.eff .r1, .lim .r1 {{ display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 12.5px; color: {TEXT}; }}
.lim .r1 span:first-child {{ color: {MUTED}; }}
.eff {{ display: grid; gap: 14px; }} .lim {{ display: grid; gap: 16px; }}
.track {{ height: 6px; border-radius: 4px; background: {CARD2}; overflow: hidden; }}
.fill {{ height: 100%; background: {BLUE}; border-radius: 4px; }} .fill.soft {{ background: {BLUE2}; }} .fill.neg {{ background: #3a4660; }}
.band {{ position: relative; height: 6px; background: {CARD2}; border-radius: 4px; }}
.band .okz {{ position: absolute; top: 0; bottom: 0; background: #12305a; border-radius: 4px; }}
.band .mk {{ position: absolute; top: -4px; width: 3px; height: 14px; background: {TEXT}; border-radius: 2px; }}
.band .mk.warn {{ background: {WARN}; }} .band .mk.bad {{ background: {BAD}; }}
.empty {{ text-align: center; padding: 48px 12px; color: {MUTED}; }}
.empty b {{ display:block; color: {TEXT}; font-weight: 500; font-size: 15px; margin-bottom: 4px; }}
.foot {{ color: {DIM}; font-size: 11.5px; text-align: center; padding-top: 10px; }}
@media (max-width: 900px) {{ .stats {{ grid-template-columns: repeat(2, 1fr); }} .stat:nth-child(4n+1) {{ border-left: 1px solid {LINE}; padding-left: 18px; }}
  .stat:nth-child(2n+1) {{ border-left: 0; padding-left: 0; }} .relay {{ grid-template-columns: 1fr; }} .arrow {{ transform: rotate(90deg); padding: 4px 0; }} }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def n0(v):
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.0f}"


def n1(v):
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.1f}"


def n2(v):
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.2f}"


def panel_title(title, note="", chip=""):
    right = f'<span class="chip">{chip}</span>' if chip else ""
    st.markdown(f'<div class="ph"><div><div class="t">{title}</div><div class="n">{note}</div></div>{right}</div>',
                unsafe_allow_html=True)


def tag(text, kind=""):
    return f'<span class="tag {kind}">{text}</span>'


def pill(delta, lower_is_better=True, fmt=n0, unit=""):
    """Small change badge. lower_is_better=None gives a neutral badge (a change that is neither good nor bad)."""
    if delta is None or abs(delta) < 1e-9:
        return ""
    sign = "+" if delta > 0 else "-"
    if lower_is_better is None:
        kind = "n"
    else:
        kind = "g" if (delta < 0) == lower_is_better else "r"
    return f'<span class="pill {kind}">{sign}{fmt(abs(delta))}{unit}</span>'




def stat(label, value, extra="", small=False):
    return f'<div class="stat{" sm" if small else ""}"><div class="v">{value}{extra}</div><div class="l">{label}</div></div>'


def stats(items):
    st.markdown('<div class="stats">' + "".join(items) + "</div>", unsafe_allow_html=True)


def relay(sinter, row, furnace):
    def node(title, rows):
        return f'<div class="node"><b>{title}</b>' + "".join(f"<div><span>{a}</span><span>{b}</span></div>" for a, b in rows) + "</div>"
    st.markdown('<div class="relay">' + node("Sinter plant", sinter) + '<div class="arrow">&#8594;</div>'
                + node("Sinter row in the furnace", row) + '<div class="arrow">&#8594;</div>' + node("Blast furnace", furnace)
                + "</div>", unsafe_allow_html=True)


def effect_bars(items):
    """items: list of (label, value Rs). Bars scale to the largest absolute value."""
    mx = max([abs(v) for _l, v in items] + [1e-9])
    html = '<div class="eff">'
    for i, (lab, v) in enumerate(items):
        w = max(2.0, 100.0 * abs(v) / mx)
        cls = "fill" if i == 0 else ("fill soft" if i == 1 else "fill neg")
        sign = "+" if v > 0 else ("-" if v < 0 else "")
        html += (f'<div><div class="r1"><span>{lab}</span><span>{sign} Rs {abs(v):,.1f}</span></div>'
                 f'<div class="track"><div class="{cls}" style="width:{w:.0f}%"></div></div></div>')
    st.markdown(html + "</div>", unsafe_allow_html=True)


def band(label, value, lo, hi, dec=2):
    """A value against its allowed window. Marker turns amber at the edge, red outside."""
    span = max(hi - lo, 1e-9)
    a0, a1 = lo - 0.7 * span, hi + 0.7 * span
    pos = min(max((value - a0) / (a1 - a0), 0.0), 1.0) * 100
    l, w = (lo - a0) / (a1 - a0) * 100, span / (a1 - a0) * 100
    tol = 0.02 * span
    kind = "bad" if (value < lo - tol or value > hi + tol) else ("warn" if (value <= lo + tol or value >= hi - tol) else "")
    return (f'<div><div class="r1"><span>{label}</span><span>{value:,.{dec}f}</span></div><div class="band">'
            f'<div class="okz" style="left:{l:.1f}%;width:{w:.1f}%"></div><div class="mk {kind}" style="left:{pos:.1f}%"></div></div></div>')


def bands(items):
    st.markdown('<div class="lim">' + "".join(items) + "</div>", unsafe_allow_html=True)


def style_fig(fig, height=300, legend=True):
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family="Inter, sans-serif", color=MUTED, size=12), showlegend=legend,
                      legend=dict(orientation="h", y=1.12, x=0, font=dict(color=MUTED)), hoverlabel=dict(bgcolor=CARD2, font_color=TEXT))
    fig.update_xaxes(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE)
    fig.update_yaxes(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE)
    return fig


def donut(labels, values, centre_top, centre_bottom):
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.72, sort=False, marker=dict(colors=DONUT[:len(labels)], line=dict(color=CARD, width=2)),
                           textinfo="none", hovertemplate="%{label}: Rs %{value:,.0f} (%{percent})<extra></extra>"))
    fig.add_annotation(text=f"<b>{centre_top}</b>", x=0.5, y=0.54, showarrow=False, font=dict(size=22, color=TEXT))
    fig.add_annotation(text=centre_bottom, x=0.5, y=0.42, showarrow=False, font=dict(size=11, color=MUTED))
    return style_fig(fig, 250, legend=True).update_layout(legend=dict(orientation="h", y=-0.05, x=0.5, xanchor="center"))
