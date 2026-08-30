from __future__ import annotations

from typing import Any

from coalplan.application.serialization import to_json_text
from coalplan.ports.llm import StructuredLLMClient


def suggest_supplement_values(*, batch: dict, llm: StructuredLLMClient) -> dict[str, str]:
    items = [
        {"item_id": item["item_id"], "label": item["label"], "related_chapters": item.get("node_titles", []), "source_items": item.get("source_items", [])[:4]}
        for item in batch.get("items", []) if item.get("allow_ai", True)
    ]
    prompt = "\n".join([
        "你是施工组织设计资料补全助手。请仅根据项目已有上下文和待补项标签，给出可供用户审核的建议填写内容。",
        "不能编造项目参数、人员、电话、审批结论或实测数据；无法确定时返回空字符串。建议值不会直接进入正文。",
        "只返回 JSON，键必须是 item_id，值是建议填写内容。",
        "待补项：" + to_json_text(items),
        '{"item_id":"建议内容"}',
    ])
    data: Any = llm.complete_json(prompt, schema_name="SupplementBatchSuggestions")
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value).strip() for key, value in data.items() if str(value).strip()}
