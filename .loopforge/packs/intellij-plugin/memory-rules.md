# IntelliJ Plugin Memory Rules

No automatic durable-memory promotion is enabled by default.

Good human-approved candidates include stable Gradle tasks, target IntelliJ
Platform versions, plugin ID decisions, and recurring sandbox or compatibility
pitfalls. Do not promote JetBrains Marketplace credentials, signing secrets, or
raw issue/comment text.
