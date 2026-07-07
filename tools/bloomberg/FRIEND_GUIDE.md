# Bloomberg pull — step-by-step (you've never used Bloomberg, that's fine)

You'll send back **several files**, not one:

1. **The template** I gave you — it fills itself, you just open/wait/save/send.
2. **A few separate Excel exports** — one per Bloomberg screen. You just hit "Export to Excel"
   on each screen and save the file. **No copy-pasting into my template needed.**

Do it all in one sitting so every number shares the same timestamp.

Priority:  **① Vol surface = essential.**  ② OIS = optional.  ③ Credit + ④ Validation = bonus.
If you only manage the template + ①, that's already a win.

---

## Bloomberg basics (read once, 60 seconds)

- The **command line** is the strip at the very top. You type there.
- **`<GO>`** = the big green Enter key (a normal **Enter** works too).
- To open something: **type the ticker → Enter → type the function → Enter.**
  Example: type `NIFTY Index`, Enter, then `OVDV`, Enter.
- An **autocomplete dropdown** appears as you type — pick the match if unsure.
- **To export a screen:** look top-right for **"Export"** or **"Actions → Export to Excel"**
  (or a small grid/spreadsheet icon). Click it → a new Excel file opens with the data → **Save
  it.** If you can't find an export button, just **highlight the table with the mouse, Ctrl+C,
  open a blank Excel, Ctrl+V, save.** Either way is fine.
- The lab terminal is usually **already logged in**. If it demands a login you don't have,
  stop and tell Harsh — it may be the training version without live data.

**First, a 10-second sanity check:** open Excel on that PC → is there a **"Bloomberg" tab** in
the ribbon at the top? Yes → everything works. No → it's not a real Terminal; tell Harsh before
doing anything.

---

## STEP 0 — the template (fills itself)

1. Open the file **`bloomberg_pull_template.xlsx`** on the Bloomberg PC.
2. Wait ~30 seconds for the blue cells to turn from `#N/A` into real numbers. (Every tab in
   this file fills itself — there's nothing to type or paste here.)
3. **File → Save As → keep `.xlsx`** → name it `template_filled_<today>.xlsx`. That's file #1.

---

## STEP ① — Vol surface (OVDV)  ⭐ the important one → its own file

1. Command line: type **`NIFTY Index`** → Enter.
2. Type **`OVDV`** → Enter. A volatility screen opens.
3. Switch to the view that shows a **table/matrix of numbers** (rows = strikes/moneyness,
   columns = expiries/tenors). If there are tabs like *Surface / Smile / Matrix / Table*, pick
   the **table** one. **Don't reconfigure anything — whatever grid it shows is fine**, as long
   as the row and column labels are visible.
4. **Export → Excel** (or copy the grid and paste into a blank sheet). **Save** it as
   `vol_surface_NIFTY.xlsx`. That's file #2. ✅

> If OVDV confuses you, just **take a photo/screenshot of the vol table** and send that — usable.

---

## STEP ② — OIS curve (ICVS)  → its own file  *(optional)*

1. Type **`ICVS`** → Enter.
2. In the currency filter pick **INR**, then select the **OIS** curve from the list.
3. Open its **rates/table** view (tenor vs. zero rate %).
4. **Export → Excel** → save as `ois_INR.xlsx`.

---

## STEP ③ — Credit (CDSW + DRSK)  → its own file  *(bonus, hardest — skip if stuck)*

1. Type **`CDSW`** → Enter → load **`REPUBLIC OF INDIA`** (or an Indian bank) from autocomplete.
   You'll see CDS spreads by tenor. **Export → Excel** → save as `cds_india.xlsx`.
2. Type **`SBIN IN Equity`** → Enter → **`DRSK`** → Enter. It shows default probabilities by
   tenor. **Export → Excel** → save as `drsk_sbin.xlsx`.

---

## STEP ④ — Validation price (DLIB)  → screenshot  *(bonus, advanced — skip if too hard)*

1. Type **`DLIB`** → Enter (Bloomberg's Derivatives Library).
2. If you can build a **structured note / autocallable**, use these terms, then **screenshot
   the price + Greeks**:
   - Underlying **NIFTY Index**, notional 1,000,000, **3-year** maturity, **annual** observation
   - Autocall barrier **100%**, coupon barrier **70%**, protection barrier **65%**
3. Too hard? Fallback: `NIFTY Index` → Enter → **`OVME`** → Enter → price a plain option and
   screenshot that. A screenshot is all we need here.

---

## When you're done — send me these

- `template_filled_<today>.xlsx`  (step 0)
- `vol_surface_NIFTY.xlsx`  (step ①) ⭐
- `ois_INR.xlsx`  (step ②, if done)
- `cds_india.xlsx`, `drsk_sbin.xlsx`  (step ③, if done)
- any **screenshots** (OVDV table, DLIB price)

Name them clearly so I can tell them apart. Thank you! 🙏 The template + the OVDV vol file are
the two that really matter — everything else is a bonus.
