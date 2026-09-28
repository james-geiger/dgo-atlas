---
title: How to propose a change
nav_group: Start here
order: 10
toc: true
---

## Propose a new term

Add a file under `governance/` holding the term, a term creation with the term
as `has_output`, and a `drafted` status boundary. Open a pull request; the
build checks it and publishes a preview.

## Change a term

Edit the term in place: it keeps its id. Add a term modification with the
term as `has_output`, and give it status boundaries as it is reviewed.

## Retire a term

Never delete it. Add a term deprecation and, if something replaces it, set
`replaced_by` on the old term. Once the deprecation is approved the term is
shown as deprecated and points at its successor.
