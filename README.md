# Hospet Cost Studio

One Streamlit app with three parts, one theme:

| Section | What it is |
|---|---|
| **Combined: Hot metal cost** | The new part. Runs the sinter model, writes its cost and chemistry into the sinter row of the furnace table, runs the furnace model, and reports cost per tHM. |
| **Sinter model** | The v42.0 sinter engine on its own: settings, run, cost, quality goals, recipe. Plus a materials editor. |
| **MBF model** | The v11.7 furnace engine on its own, with the typed sinter row: settings, run, burden, limits. Plus a materials editor. |
| **Upload and shared materials** | The two workbooks, templates, the shared-material panel, and the link settings. |

## Files

| File | Purpose |
|---|---|
| `app.py` | Entry point: navigation and page setup |
| `views.py` | Every page |
| `ui.py` | Theme (dark navy, one blue accent) and display helpers |
| `combined.py` | The backend link layer. No Streamlit code, so it can also be imported in a notebook |
| `optimizer.py` | Sinter engine v42.0, copied unmodified |
| `optimiser.py` | MBF engine v11.7 (engine version 14.0), copied unmodified |
| `templates/` | Blank-ready workbooks for both models (demo values) |
| `tests/` | 32 tests: `test_combined.py` (backend) and `test_app.py` (every page) |

The two engine files are byte-for-byte the ones you supplied. Nothing in this package edits them.

Run: `pip install -r requirements.txt`, then `streamlit run app.py`. Tests: `pip install -r requirements-dev.txt`, then `pytest -q` (about 35 s).

## How the combined run works

1. **Reconcile.** Materials named in both files (limestone, dolomite by default) are set to one value in both tables, using the file you choose per material, or values you type. Your files are not changed.
2. **Sinter model** solves for the sinter burden. Cost per tonne = raw material + O&M (default Rs 750/t), dry basis. BF returns are poured in at zero cost.
3. **Handoff.** In a copy of the furnace table, the chosen Sinter row gets the sinter model's price, Fe, CaO, MgO, SiO2 and Al2O3, and no stock cap. Mn, S and moisture stay as in your file.
4. **Furnace model** solves on that copy. Cost per tHM comes straight from its result.
5. **Settle the tonnage.** The furnace decides how much sinter the plan needs, and sinter stock limits depend on that tonnage, so steps 2 to 4 repeat (up to three passes) until they agree within 3%.
6. **Checks.** Stock need against stock for both plants (shared materials add both draws against one stock figure), quality limits, and a grade: *Decision grade* only if the sinter model returned Optimal and the furnace returned Optimal.

If the sinter step fails, the furnace is not run on a made-up sinter row; the page says why.

## Reading the change since the last run

Price effect = change in sinter price x the sinter the earlier run used. Furnace response = everything else (the furnace choosing a different sinter share, coke and flux because sinter quality moved). The two add up to the change in cost per tHM.

## Settings that need your confirmation

- Every sinter quality **tolerance** except SiO2 max is a placeholder in the v42.0 engine.
- O&M Rs 750/t, and the plan default of 9,000 tHM over 7 days, are defaults.
- Furnace stock limits over the plan are **off** by default, matching the MBF model. Turn them on under Upload and shared materials. The stock check on the Combined page always shows need against stock.
- Moisture of the sinter row at the furnace is kept from your file unless you set it.
- Heat-balance values and the other engine constants keep their plant defaults; heat values are literature placeholders until calibrated.

## Not included

This package rebuilds the pages needed for the combined model. The original dashboards have more pages that are **not** in this app: the sinter app's Inventory Usage, Manual Burden Control, Scenario Analysis, Plant Run Validation, Productivity and Wet Specific Consumption; the MBF app's Slag oxides, Trends, Scenario analysis, Heat audit and Reports. Keep those apps deployed for that detail. Both engines here are the same, so results agree.

## Known limits

- The furnace's stock check treats stock in the sinter's stock basis (as received by default); the MBF engine itself applies stock in dry kg.
- The basicity scan varies the sinter basicity spec (a window of +/- 0.025 around each value) inside the approved tolerance. If the cheapest point is at the edge of the range, the page says so.
- Both engines keep some state at module level. One lock serialises every solve, so users on a shared deployment queue rather than mix results.
- Prices and commercial data are sensitive. Host privately, and upload real workbooks in the app instead of committing them.
