"""Broker account sync — daily archival of Dhan-reported account state + ledger.

Stores the broker's view (Dhan as source of truth): immutable daily snapshots in MongoDB
(`broker_snapshots`) plus a current-state mirror in PostgreSQL, with auto-EOD + manual
triggers and a one-time historical backfill of the transactional logs.
"""
