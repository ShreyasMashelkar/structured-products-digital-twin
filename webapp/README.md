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

## Workflow tabs

`Structuring` (interactive client brief → solve-to-par → catalog + 3-D vol surface) ·
`Blotter` · `Risk` · `P&L Explain` · `Hedging` · `Model Risk` (LSV−LV) · `Stress` · `Backtest`.

The backend does no quant of its own — it calls `spdt.dashboard.desk_data.build_desk_data` and
`spdt.structurer`, so the web app and the library can never disagree.
