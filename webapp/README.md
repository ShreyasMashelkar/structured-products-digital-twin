# SPDT Desk — web front end

A real trading-terminal front end for the desk, replacing the Streamlit MVP. **FastAPI** serves
the `spdt` engine; a **Vite + React + TypeScript + Tailwind** app renders it as a dense dark
structuring terminal (the stack tier-1 tools' modern UIs use: owned components, a real data grid,
Recharts, and Plotly for the 3-D vol surface).

```
webapp/
├── server.py            # FastAPI: /api/desk, /api/structure (live solve-to-par)
└── frontend/            # Vite + React + Tailwind app
    └── src/
        ├── App.tsx      # shell: masthead, KPI strip, tabs
        ├── views.tsx    # the 8 workflow views
        ├── components/  # ui primitives + themed charts
        └── lib/         # api client, theme tokens, formatting
```

## Run (two terminals)

```bash
# 1. backend — serves the desk on :8077
uvicorn webapp.server:app --port 8077 --reload

# 2. frontend — dev server on :5173 (proxies /api → :8077)
cd webapp/frontend
npm install      # first time only
npm run dev
```

Then open **http://localhost:5173**.

### API token

When the backend is protected with `SPDT_API_TOKEN`, supply the same token to the trusted desk
frontend at build/dev-server startup so every API request includes `X-API-Token`:

```bash
SPDT_API_TOKEN=local-secret uvicorn webapp.server:app --port 8077
cd webapp/frontend
VITE_SPDT_API_TOKEN=local-secret npm run dev
```

`VITE_*` values are visible to the browser. For an internet-facing deployment, terminate user
authentication in a server-side gateway and do not embed a privileged shared secret in the SPA.

### Data source (env-driven)

The backend runs on a reproducible **synthetic** snapshot by default. To build from **live** Indian market data (option chain + FBIL rates), pick an engine:

```bash
# 1. NSE EOD bhavcopy (public, no account) — the default live engine
SPDT_LIVE=1 uvicorn webapp.server:app --port 8077

# 2. DhanHQ intraday option chain (needs a Dhan account + token)
SPDT_LIVE=1 SPDT_SOURCE=dhan \
  DHAN_CLIENT_ID=xxxxxxxxxx DHAN_ACCESS_TOKEN=eyJ... \
  uvicorn webapp.server:app --port 8077

# 3. Optional local Bloomberg export: MIFOR funding overlay only
SPDT_SOURCE=bloomberg-rates \
SPDT_BLOOMBERG_RATES_XLSX="/Users/shreyas/Downloads/Data for Intern's usage.xlsx" \
  uvicorn webapp.server:app --port 8077
```

- **bhavcopy** — NSE's public EOD F&O file; walks back to the latest *published* file, so it works any time of day (mid-session it serves the previous close — the masthead shows the data date with an **EOD** badge). Today's file publishes after the close (~6 pm IST).
- **dhan** — DhanHQ's v2 Option Chain API: an *authenticated broker feed*, so it gives **intraday** spot + chain (with IV) and isn't IP-blocked like the public NSE endpoints. Set `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN` (never commit them); Dhan returns one expiry per call, so the source fetches the nearest few (≈1 req/3s). Requires a free Dhan account.
- **bloomberg-rates** — reads the one-sheet Terminal export used in this project. The file contains Modified MIFOR, SOFR and USD/INR vol, not NIFTY options and not a MIBOR/OIS curve. SPDT therefore uses it only as a **MIFOR-implied funding overlay**; the masthead explicitly shows that equity and discount-curve inputs are unchanged.

Keep synthetic for reproducible runs and tests.

### Replay mode (public deployments)

Broker API terms and the exchanges' display licences don't allow republishing a live feed on
a public site — so the public demo (Hugging Face Spaces) replays a **recorded** session
instead. Same pipeline, same UI (the masthead badge reads **replay**), day-old data:

```bash
# during market hours, on the live feed — cut the day's tick tape
SPDT_SOURCE=xts python3 -m tools.record_tape

# near/after the close — save the desk payload (and history) the replay will serve
SPDT_SOURCE=xts python3 -m tools.record_tape --desk

# serve the recorded session (the Dockerfile ships data/replay/ and defaults to this)
SPDT_SOURCE=replay uvicorn webapp.server:app --port 8077
```

The tape maps onto the wall clock by IST time-of-day — at 14:05 viewers see the 14:05 tick
of the recorded session — and wraps modulo the tape length overnight so it never freezes.

## Workflow tabs

`Structuring` (interactive client brief → solve-to-par → catalog + 3-D vol surface) ·
`Blotter` · `Risk` · `P&L Explain` · `Hedging` · `Model Risk` (LSV−LV) · `Stress` · `Backtest`.

The backend does no quant of its own — it calls `spdt.dashboard.desk_data.build_desk_data` and
`spdt.structurer`, so the web app and the library can never disagree.
