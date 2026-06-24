---
title: SPDT Structuring Desk
emoji: 📈
colorFrom: gray
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Equity structured-products desk + XVA twin (React + FastAPI)
---

# SPDT — Structured Products Digital Twin (live desk)

A simulation of an equity structured-products desk **plus its counterparty-risk twin** —
`structuring → pricing → hedging → risk → P&L`, then `exposure → CVA/FVA → all-in price →
governance`. This Space serves the **React trading terminal** (`webapp/frontend`) and the
FastAPI engine from a single container.

Workspaces: **Overview · Originate · Book & Risk · Counterparty & XVA · Validate**.

Runs on a reproducible **synthetic** market snapshot by default (no external data needed).

- Source & full design docs: https://github.com/ShreyasMashelkar/structured-products-digital-twin
- The Space build is defined by the repo-root `Dockerfile` (Node builds the Vite app;
  `python:3.11-slim` serves API + built SPA via uvicorn on port 7860).

> This `README.md` (with the Hugging Face Space frontmatter above) lives only on the
> `hf-space` branch; `main` keeps the full project README.
