"""Pinned config constants. Per TECH_STACK.md: model id is always pinned explicitly, never a "latest" alias."""

GEMINI_MODEL_ID = "gemini-3.7-flash"

# Caps enforced in Firestore (SYSTEM_DESIGN.md §7), mirrored here for agent-side reference only.
MAX_CLARIFICATION_ROUNDS = 3
MAX_EXECUTION_RETRIES = 3
MAX_TRIVIAL_CONFLICT_ATTEMPTS = 1
