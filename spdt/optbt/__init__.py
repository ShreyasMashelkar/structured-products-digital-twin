"""optbt — EOD options backtesting engine for NSE index options (plan: qcalpha-engagement).

Sits on SPDT's data, vol and pricing layers. Design constraints, stated once:
EOD bhavcopy data, fortnightly-scale rebalancing, every mark provenance-tagged, every
result a band across cost scenarios, no look-ahead by construction.
"""
