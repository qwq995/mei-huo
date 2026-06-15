from __future__ import annotations

import json
from typing import Any


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def to_json_text(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
