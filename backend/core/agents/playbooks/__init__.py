"""Playbooks — per-agent reusable business procedures (markdown + frontmatter).

A playbook stores HOW this business does something ("how we chase overdue
invoices here"), distinct from memory (facts) and context files (knowledge).
Files live at data/agents/{slug}/playbooks/{playbook-slug}.md; archived
playbooks move to playbooks/archive/. A compact index is injected into the
system prompt; full content is loaded on demand via the read_playbook tool.
"""
