"""Showcase Demo Homes: the curated Parker family dataset behind the PCC
Family Demo and Ultimate Demo templates.

Modules:

* parker   — the fictional dataset (pure data, dates relative to a reference day)
* registry — the plan-gated module registry and seed orchestrator
* family / ultimate — the module seeders
* purge    — removal of showcase content before a reset
* images   — original illustrations or approved photography
* guards   — which fixtures are showcases, and what that restricts

Kept import-free so lightweight callers (mykhaya.showcase.guards) never load
the seeders.
"""
