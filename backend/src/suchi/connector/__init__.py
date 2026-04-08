"""Zotero Connector compatibility layer.

Makes Suchi speak the Zotero Connector protocol so the existing
Zotero browser extension (Chrome/Firefox) works with Suchi unmodified.

The Zotero Connector calls localhost:23119 with specific endpoints.
We translate those calls into Suchi's internal API.
"""
