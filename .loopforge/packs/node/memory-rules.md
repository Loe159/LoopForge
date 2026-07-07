# Node Memory Rules

No automatic durable-memory promotion is enabled by default.

Good human-approved candidates include the package manager, canonical test or
build script, supported Node version, and known lockfile expectations. Do not
promote registry credentials, tokens, npm auth lines, or raw issue/comment text.
