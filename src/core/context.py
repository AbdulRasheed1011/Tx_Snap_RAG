from __future__ import annotations

import os
import uuid

def get_run_id() -> str:
    # Use env if present (useful in CI/AWS), else generate
    return os.getenv("RUN_ID") or uuid.uuid4().hex[:12]