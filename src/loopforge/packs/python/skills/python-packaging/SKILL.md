---
name: python-packaging
description: Handle Python package metadata and dependencies conservatively using existing packaging conventions.
---

# Python packaging

Treat package metadata, requirements, and lockfiles as review-sensitive. Do not
add a dependency when the standard library or an existing dependency suffices.
