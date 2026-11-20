---
id: CTX-001
kind: decision
title: Raise API rate limit
status: active
author: ChangeTrace Demo
created: '2026-11-20'
touches: [api/settings.yaml#rate_limit.requests_per_minute]
guards:
- {file: api/settings.yaml, key: rate_limit.requests_per_minute, expect: '120', previous: '60'}
supersedes: []
superseded_by: null
tags: [api, rate-limit]
---

## Problem
Partner integrations were throttled at 60 requests per minute and saw 429 errors during normal batch syncs.

## Decided
Raise the default rate limit to 120 requests per minute.

## Tried and ruled out
Per-partner overrides: more configuration to maintain for the same outcome.

## Assumptions
The API tier can absorb twice the request rate.

## Watch out
Lowering the limit back to 60 brings the 429 errors back for batch syncs. Check partner traffic before changing it.
