from __future__ import annotations

import json
import re
from typing import Any


class FakeLLMClient:
    """Deterministic LLM stub for tests and local demos."""

    def complete(self, prompt: str) -> str:
        if "CONTENT_SUBSECTION_REVISION_PROMPT" in prompt:
            return _fake_content_subsection_revision(prompt)
        if "CHAPTER_WRITING_UNIT_PROMPT" in prompt:
            return _fake_chapter_writing_unit(prompt)
        title = _extract(prompt, "当前小章节标题") or _extract(prompt, "章节标题") or "未命名章节"
        sources = _extract_block(prompt, "已匹配来源章节摘要") or _extract_block(prompt, "来源片段")
        manual = _extract_block(prompt, "人工补充项")
        special = _extract_block(prompt, "特殊备注")
        required_facts = _extract_required_facts(prompt)
        feedback_required_facts = _extract_feedback_required_facts(prompt)
        pattern_moves = _extract_pattern_requirements(prompt)
        evidence_quotes = _extract_evidence_quotes(prompt)
        source_lines = [line.strip() for line in sources.splitlines() if line.strip().startswith("-")]
        if not source_lines:
            source_lines = ["- 未在投标文档中识别到强匹配章节。"]
        manual_items = [line.strip("- ").strip() for line in manual.splitlines() if line.strip().startswith("-")]
        if not manual_items:
            manual_items = ["现场核验资料、合同数据或审批信息"]
        special_items = [line.strip("- ").strip() for line in special.splitlines() if line.strip().startswith("-")]
        body = [
            f"# {title}",
            "",
            "## 主要来源摘要",
            *source_lines[:5],
            "",
            "## 生成正文",
            f"本节围绕“{title}”编写。当前为本地测试桩输出，仅用于验证接口、校验和落盘链路。",
            "真实生成请使用 deepseek/minimax 等真实 LLM provider 启动后端。",
            "本节测试正文吸收以下已映射来源摘要：",
            *source_lines[:5],
            *(_render_pattern_moves_body(pattern_moves) if pattern_moves else []),
            *(_render_required_fact_body(required_facts) if required_facts else []),
            *(_render_feedback_required_fact_body(feedback_required_facts) if feedback_required_facts else []),
            *(_render_evidence_quotes_body(evidence_quotes) if evidence_quotes else []),
            "",
            "## 人工补充需补充",
        ]
        body.append("- 本地测试桩不判断现场、合同、审批和实测资料缺失情况；真实生成时由模型依据来源证据保留必要占位。")
        if special_items:
            body.extend(["", "## 特殊备注"])
            body.extend(f"- {item}" for item in special_items[:6])
        return "\n".join(body).strip() + "\n"

    def complete_json(self, prompt: str, *, schema_name: str) -> dict[str, Any]:
        if schema_name == "ProjectProfile":
            return _fake_project_profile(prompt)
        if schema_name == "TemplateOutlinePlan":
            return _fake_outline(prompt)
        if schema_name == "SourceMappingResult":
            return _fake_mapping(prompt)
        if schema_name == "standard_constraint_atomization":
            return _fake_standard_constraints(prompt)
        if schema_name == "standard_document_classification":
            return _fake_standard_document_classification(prompt)
        if schema_name == "standard_document_matching":
            return _fake_standard_document_matching(prompt)
        if schema_name == "standard_constraint_matching":
            return _fake_standard_constraint_matching(prompt)
        if schema_name == "standard_compliance_review":
            return _fake_standard_compliance_review(prompt)
        return {}


def _fake_standard_constraints(prompt: str) -> dict[str, Any]:
    pattern = re.compile(
        r"\[block_id=(?P<id>[^;]+); clause=(?P<clause>[^;]+);[^\]]*\]\n(?P<text>.*?)(?=\n\n\[block_id=|\Z)",
        re.S,
    )
    atoms = []
    for match in pattern.finditer(prompt):
        text = match.group("text").strip()
        if not re.search(r"必须|应当|应|不得|严禁|不应|允许偏差|合格率", text):
            continue
        constraint_type = "禁止性要求" if re.search(r"不得|严禁|不应", text) else "一般技术要求"
        ai_fixable = constraint_type != "禁止性要求" and not re.search(r"审批|资质|检测|试验|实测", text)
        keywords = [term for term in ("爆破", "开挖", "混凝土", "灌浆", "模板", "安全", "验收") if term in text]
        atoms.append({
            "block_id": match.group("id"),
            "clause_no": "" if match.group("clause") == "-" else match.group("clause"),
            "source_text": text,
            "normalized_requirement": text,
            "constraint_type": constraint_type,
            "review_method": "semantic_review",
            "severity": "blocking" if constraint_type == "禁止性要求" else "warning",
            "disciplines": keywords[:2],
            "project_types": ["水利水电"],
            "chapter_scopes": keywords,
            "keywords": keywords,
            "applicability": [],
            "exceptions": [],
            "evidence_required": [],
            "ai_fixable": ai_fixable,
            "repair_instruction": "删除冲突表述并补充符合条款的控制措施。",
            "confidence": 0.9,
            "status": "published",
        })
    return {"atoms": atoms[:16]}


def _fake_standard_document_classification(prompt: str) -> dict[str, Any]:
    pattern = re.compile(r"\[source_id=(?P<id>[^;]+); file_name=(?P<name>[^\]]+)\]\n(?P<text>.*?)(?=\n\n\[source_id=|\Z)", re.S)
    documents = []
    for match in pattern.finditer(prompt):
        text = f"{match.group('name')}\n{match.group('text')[:1800]}"
        if "施工组织" in text:
            category = "施工组织"
        elif "安全" in text:
            category = "安全"
        elif "验收" in text or "质量检验" in text:
            category = "质量验收"
        elif "施工" in text:
            category = "施工技术"
        else:
            category = "其他"
        disciplines = [term for term in ("地下工程", "爆破", "混凝土", "灌浆", "土石方", "施工导流") if any(char_pair in text for char_pair in _bigrams(term))]
        documents.append({
            "source_id": match.group("id"), "category": category, "disciplines": disciplines[:4],
            "project_types": ["水利水电"] if any(term in text for term in ("水利", "水电", "水工")) else [],
            "summary": match.group("name"), "confidence": 0.9,
        })
    return {"documents": documents}


def _fake_standard_document_matching(prompt: str) -> dict[str, Any]:
    project_match = re.search(r"项目上下文：\n(?P<text>.*?)(?=\n\n候选规范：)", prompt, re.S)
    project = project_match.group("text") if project_match else ""
    matches = []
    for line in prompt.split("候选规范：", 1)[-1].splitlines():
        match = re.match(r"- document_id=(?P<id>[^;]+);(?P<meta>.*)", line)
        if not match:
            continue
        overlap = _semantic_overlap(project, match.group("meta"))
        matches.append({
            "document_id": match.group("id"), "applicable": overlap >= 0.08,
            "score": round(min(0.98, 0.35 + overlap), 3) if overlap >= 0.08 else round(overlap, 3),
            "match_reason": "项目内容与规范范围存在语义重合" if overlap >= 0.08 else "当前项目信息不足以确认适用",
        })
    return {"matches": matches}


def _fake_standard_constraint_matching(prompt: str) -> dict[str, Any]:
    chapter_match = re.search(r"章节标题：(?P<title>.*?)\n章节正文：\n(?P<body>.*?)(?=\n\n候选约束：)", prompt, re.S)
    chapter = f"{chapter_match.group('title')}\n{chapter_match.group('body')}" if chapter_match else ""
    pattern = re.compile(r"\[atom_id=(?P<id>[^;]+);[^\]]+\]\n要求：(?P<requirement>.*?)(?=\n适用条件：)", re.S)
    matches = []
    for item in pattern.finditer(prompt):
        overlap = _semantic_overlap(chapter, item.group("requirement"))
        if overlap >= 0.08:
            matches.append({"atom_id": item.group("id"), "applicable": True, "score": min(0.98, 0.45 + overlap), "match_reason": "章节施工内容与条款要求语义相关"})
    return {"matches": matches[:18]}


def _fake_standard_compliance_review(prompt: str) -> dict[str, Any]:
    chapter_match = re.search(r"正文：\n(?P<body>.*?)(?=\n\n候选条款：)", prompt, re.S)
    chapter = chapter_match.group("body") if chapter_match else ""
    atom_pattern = re.compile(
        r"\[atom_id=(?P<id>[^;]+);[^\]]*ai_fixable=(?P<fix>true|false)\]\n原文：(?P<text>.*?)(?=\n审查要求：)",
        re.S,
    )
    violations = []
    for match in atom_pattern.finditer(prompt):
        source = match.group("text").strip()
        prohibited = re.search(r"(?:严禁|不得|不应)(?:采用|使用|进行)?([^，。；\n]{2,18})", source)
        if not prohibited:
            continue
        token = prohibited.group(1).strip()
        if token not in chapter and not any(part in chapter for part in re.findall(r"[\u4e00-\u9fff]{2,}", token)):
            continue
        violations.append({
            "atom_id": match.group("id"),
            "verdict": "violated",
            "explanation": f"章节表述涉及规范禁止的“{token}”。",
            "evidence_quote": token,
            "suggested_fix": "删除冲突做法，并改写为符合规范的施工控制措施。",
            "ai_fixable": match.group("fix") == "true",
        })
    return {"violations": violations}


def _bigrams(text: str) -> set[str]:
    compact = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())
    return {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}


def _semantic_overlap(left: str, right: str) -> float:
    left_terms = _bigrams(left)
    right_terms = _bigrams(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / max(1, min(len(left_terms), len(right_terms)))


def _extract(prompt: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}[:：]\s*(.+)", prompt)
    return match.group(1).strip() if match else ""


def _extract_block(prompt: str, label: str) -> str:
    match = re.search(rf"## {re.escape(label)}\n(.*?)(?=\n## |\Z)", prompt, re.S)
    return match.group(1).strip() if match else ""


def _extract_required_facts(prompt: str) -> list[str]:
    block = _extract_block(prompt, "required_source_facts（必须优先写入生成正文的原文事实）")
    if not block or block.strip() == "无。":
        return []
    facts: list[str] = []
    for line in block.splitlines():
        text = line.strip("- ").strip()
        if not text:
            continue
        fact_match = re.search(r"fact:\s*(.*?)(?:；要求:|$)", text)
        token_match = re.search(r"tokens:\s*(.*?)(?:；fact:|$)", text)
        fact_text = fact_match.group(1).strip() if fact_match else text
        token_text = token_match.group(1).strip() if token_match else ""
        facts.append(f"{fact_text}（关键值：{token_text}）" if token_text and token_text != "-" else fact_text)
    return facts


def _extract_feedback_required_facts(prompt: str) -> list[str]:
    block = _extract_block(prompt, "quality_feedback_required_facts（质量审计要求本次必须承接的事实）")
    if not block or block.strip() == "无。":
        return []
    return [line.strip("- ").strip() for line in block.splitlines() if line.strip().startswith("-")]


def _extract_evidence_quotes(prompt: str) -> list[str]:
    block = _extract_block(prompt, "原文文段映射表（模板要求 -> 输入文档证据）")
    if not block:
        block = prompt
    spans = re.findall(
        r"### evidence_id:\s*(ev_[0-9a-f]{12}).*?```text\s*(.*?)\s*```",
        block,
        flags=re.S,
    )
    if not spans:
        spans = re.findall(r"^-\s*(ev_[0-9a-f]{12})：(.*)$", block, flags=re.M)
    return [
        f"{evidence_id}：{re.sub(r'\s+', ' ', quote).strip()}"
        for evidence_id, quote in spans
        if quote.strip()
    ]


def _extract_pattern_requirements(prompt: str) -> list[str]:
    requirements: list[str] = []
    active_label = ""
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped in {"generation_moves:", "detail_design_rules:"}:
            active_label = stripped
            continue
        if active_label and re.match(
            r"^(human_only_items|revision_checks|corpus_basis|organization_policy|source_mapping_requirements|detail_design_rules):$",
            stripped,
        ):
            active_label = "detail_design_rules:" if stripped == "detail_design_rules:" else ""
            continue
        if active_label and stripped.startswith("- "):
            value = stripped[2:].strip()
            if value and value not in requirements:
                requirements.append(value)
        if len(requirements) >= 12:
            break
    preserved = re.findall(
        r"本节已按本地施组写作模式组织以下要点：\s*((?:\n-\s+.*)+)",
        prompt,
    )
    for block in preserved:
        for line in block.splitlines():
            value = line.strip("- ").strip()
            if value and value not in requirements:
                requirements.append(value)
            if len(requirements) >= 12:
                return requirements
    return requirements


def _fake_content_subsection_revision(prompt: str) -> str:
    first_line = _extract(prompt, "第一行必须是")
    if not first_line:
        first_line = "### 修订小节"
    section_ids = _known_section_ids(prompt)[:3]
    source_text = "、".join(section_ids) if section_ids else "【需人工补充：可靠来源章节】"
    required_facts = _extract_content_revision_required_facts(prompt)
    lines = [
        first_line,
        f"本小节已按小节级修订动作重新组织，依据 {source_text} 对原小节进行补充。",
    ]
    if required_facts:
        lines.append("本小节已承接 content_revision_required_facts 中要求补写的来源事实：")
        lines.extend(f"- {fact}" for fact in required_facts[:8])
    lines.append("后续真实模型应结合来源章节全文展开施工对象、工艺流程、资源条件、质量安全控制和记录要求；本地 fake 输出仅用于验证小节级版本更新链路。")
    return "\n".join(lines).strip() + "\n"


def _fake_chapter_writing_unit(prompt: str) -> str:
    title = _extract(prompt, "写作单元") or "写作单元"
    evidence_quotes = _extract_evidence_quotes(prompt)
    required_facts = _extract_required_facts(prompt)
    feedback_required_facts = _extract_feedback_required_facts(prompt)
    pattern_moves = _extract_pattern_requirements(prompt)
    lines = [
        f"### {title}",
        "",
        f"本单元围绕“{title}”组织施工对象、工艺步骤和控制要求。本地 fake 输出用于验证细粒度调用与整章装配链路。",
    ]
    if evidence_quotes:
        lines.extend(["", "本单元承接以下当前项目投标证据：", *[f"- {item}" for item in evidence_quotes[:4]]])
    if required_facts:
        lines.extend(["", "本单元优先吸收以下来源事实：", *[f"- {item}" for item in required_facts[:4]]])
    if feedback_required_facts:
        lines.extend(["", "本单元按质量反馈承接以下来源事实：", *[f"- {item}" for item in feedback_required_facts[:4]]])
    if pattern_moves:
        lines.extend(["", "本单元按本地施组写作模式组织以下要点：", *[f"- {item}" for item in pattern_moves[:8]]])
    lines.extend(["", "实际生成时应继续依据投标证据填充参数，并利用参考原子和写作技巧完善工序、检查与记录闭环。"])
    return "\n".join(lines).strip() + "\n"


def _extract_content_revision_required_facts(prompt: str) -> list[str]:
    block = _extract_block(prompt, "content_revision_required_facts")
    if not block or block.strip().lower() == "none":
        return []
    facts: list[str] = []
    for line in block.splitlines():
        text = line.strip("- ").strip()
        if not text:
            continue
        match = re.search(r"fact:\s*(.*)$", text)
        facts.append(match.group(1).strip() if match else text)
    return facts


def _render_required_fact_body(required_facts: list[str]) -> list[str]:
    return ["", "本节已吸收原文证据中的关键事实：", *[f"- {item}" for item in required_facts[:8]]]


def _render_feedback_required_fact_body(required_facts: list[str]) -> list[str]:
    return ["", "本节已按质量反馈补写以下来源事实：", *[f"- {item}" for item in required_facts[:8]]]


def _render_evidence_quotes_body(quotes: list[str]) -> list[str]:
    return ["", "本节测试正文承接以下原文证据：", *[f"- {item}" for item in quotes]]


def _render_pattern_moves_body(pattern_moves: list[str]) -> list[str]:
    return ["", "本节已按本地施组写作模式组织以下要点：", *[f"- {item}" for item in pattern_moves[:8]]]


def _fake_project_profile(prompt: str) -> dict[str, Any]:
    section_ids = _known_section_ids(prompt)[:8]
    return {
        "project_name": "示例项目",
        "project_type": "施工组织设计生成测试项目",
        "location": None,
        "construction_scope": ["依据投标文件生成施工组织设计正文"],
        "key_quantities": [],
        "main_methods": [],
        "schedule": [],
        "quality_safety_environment_targets": [],
        "risk_points": [],
        "missing_items": [],
        "source_section_ids": section_ids,
    }


def _fake_outline(prompt: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for item in _json_array_after_marker(prompt, "目标模板树："):
        node_id = item.get("id") or item.get("node_id")
        if not node_id:
            continue
        if not any([item.get("source_rules"), item.get("auto_fill"), item.get("manual_fill"), item.get("special_notes")]):
            continue
        nodes.append(
            {
                "node_id": node_id,
                "title": item.get("title", ""),
                "level": item.get("level", 1),
                "enabled": True,
                "source_hints": _known_section_ids(prompt)[:4],
                "main_sources": item.get("source_rules", []),
                "auto_fill": item.get("auto_fill", []),
                "manual_fill": item.get("manual_fill", []),
                "special_notes": item.get("special_notes", []),
            }
        )
    return {"template_id": "fake", "nodes": nodes}


def _fake_mapping(prompt: str) -> dict[str, Any]:
    node_id = _extract_json_field(prompt, "id") or _extract_json_field(prompt, "node_id")
    ids = _known_section_ids(prompt)[:4]
    return {
        "node_id": node_id,
        "matches": [
            {
                "section_id": section_id,
                "title_path": [],
                "usage": "fact",
                "reason": "关键词与当前小章节主要来源要求匹配。",
                "confidence": 0.75,
            }
            for section_id in ids
        ],
        "missing_evidence": [] if ids else ["未识别到可靠来源章节。"],
    }


def _known_section_ids(text: str) -> list[str]:
    ordered: list[str] = []
    for section_id in re.findall(r"sec_[0-9a-f]{12}", text):
        if section_id not in ordered:
            ordered.append(section_id)
    return ordered


def _json_array_after_marker(prompt: str, marker: str) -> list[dict[str, Any]]:
    try:
        start = prompt.index(marker) + len(marker)
    except ValueError:
        return []
    text = prompt[start:].strip()
    array_start = text.find("[")
    if array_start < 0:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(text[array_start:])
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _extract_json_field(text: str, field: str) -> str:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else ""
