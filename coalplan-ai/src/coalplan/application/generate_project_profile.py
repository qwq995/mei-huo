from __future__ import annotations

import re

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import MarkdownSection, SourceTocItem
from coalplan.domain.profile import ProjectProfile
from coalplan.infrastructure.validation.json_contract import ProjectProfileValidator
from coalplan.ports.llm import StructuredLLMClient
from coalplan.ports.repository import ArtifactRepository


PROFILE_KEYWORDS = [
    "项目名称",
    "工程概况",
    "项目概况",
    "项目基本信息",
    "工程范围",
    "施工范围",
    "工作内容",
    "施工内容",
    "工程量",
    "工期",
    "质量",
    "安全",
    "环境",
    "水文",
    "地质",
    "施工条件",
]

PROFILE_TITLE_PRIORITY = [
    "项目名称",
    "项目基本信息",
    "工程概况",
    "项目概况",
    "具体施工内容",
    "施工内容",
    "工程范围",
    "施工范围",
    "地理位置",
    "交通条件",
    "质量要求",
]

PROFILE_LOW_VALUE_TITLE_TERMS = {
    "编制依据",
    "作业技术依据",
    "法律法规",
    "规范",
    "标准",
    "类似项目",
    "业绩",
    "投标人",
}


def generate_project_profile(
    *,
    project_id: str,
    toc_items: list[SourceTocItem],
    sections: list[MarkdownSection],
    llm: StructuredLLMClient,
    artifacts: ArtifactRepository,
) -> ProjectProfile:
    source_sections = _select_profile_sections(sections, limit=18)
    try:
        data = llm.complete_json(
            build_project_profile_prompt(toc_items=toc_items, sections=source_sections),
            schema_name="ProjectProfile",
        )
        profile = ProjectProfile(**data)
    except Exception:
        profile = _fallback_profile(source_sections)
    result = ProjectProfileValidator().validate(profile, toc_items)
    if not result.passed:
        repaired = _repair_profile_source_ids(profile, toc_items, result)
        repaired_result = ProjectProfileValidator().validate(repaired, toc_items)
        if repaired_result.passed:
            profile = repaired
        else:
            fallback = _fallback_profile(source_sections)
            fallback.missing_items.extend(f"AI 项目概况输出校验失败：{issue.message}" for issue in repaired_result.issues)
            profile = fallback
    profile = _repair_profile_semantics(profile, source_sections)
    profile.artifact_json_path = artifacts.write_text(project_id, "profile/project_profile.json", to_json_text(dump_model(profile)))
    profile.artifact_markdown_path = artifacts.write_text(project_id, "profile/project_profile.md", render_project_profile_markdown(profile))
    return profile


def build_project_profile_prompt(*, toc_items: list[SourceTocItem], sections: list[MarkdownSection]) -> str:
    return "\n".join(
        [
            "你是施工方案项目信息抽取 agent。你只能依据给定投标文档内容生成项目概况，不得引入外部知识，不得猜测缺失信息。",
            "",
            "输入一：投标文档目录",
            to_json_text(_compact_toc(toc_items)),
            "",
            "输入二：高相关原文片段",
            _render_sections(sections),
            "",
            "任务：",
            "从真实文档中抽取项目画像，供后续施工组织设计生成使用。",
            "",
            "输出要求：",
            "只输出 JSON，不要 Markdown，不要解释。",
            "必须符合以下 schema：",
            '{"project_name":"string|null","project_type":"string|null","location":"string|null","construction_scope":["string"],"key_quantities":["string"],"main_methods":["string"],"schedule":["string"],"quality_safety_environment_targets":["string"],"risk_points":["string"],"missing_items":["string"],"source_section_ids":["string"]}',
            "",
            "规则：",
            "- 所有字段必须来自输入原文。",
            "- 缺失则填 null 或空数组，并写入 missing_items。",
            "- key_quantities 必须保留单位。",
            "- source_section_ids 只能使用输入中存在的 section_id。",
        ]
    )


def render_project_profile_markdown(profile: ProjectProfile) -> str:
    lines = ["# 项目概况", ""]
    for label, value in [
        ("项目名称", profile.project_name),
        ("项目类型", profile.project_type),
        ("项目位置", profile.location),
    ]:
        lines.extend([f"## {label}", value or "【需人工补充】", ""])
    for label, items in [
        ("施工范围", profile.construction_scope),
        ("关键工程量", profile.key_quantities),
        ("主要工法", profile.main_methods),
        ("工期信息", profile.schedule),
        ("质量安全环保目标", profile.quality_safety_environment_targets),
        ("风险要点", profile.risk_points),
        ("缺失信息", profile.missing_items),
        ("来源章节", profile.source_section_ids),
    ]:
        lines.append(f"## {label}")
        lines.extend([f"- {item}" for item in items] or ["- 【无】"])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _select_profile_sections(sections: list[MarkdownSection], *, limit: int) -> list[MarkdownSection]:
    scored: list[tuple[int, int, MarkdownSection]] = []
    for section in sections:
        title_text = " > ".join(section.title_path)
        haystack = f"{title_text}\n{section.content}"
        score = sum(1 for keyword in PROFILE_KEYWORDS if keyword in haystack)
        priority = sum((len(PROFILE_TITLE_PRIORITY) - index) * 4 for index, keyword in enumerate(PROFILE_TITLE_PRIORITY) if keyword in title_text)
        if any(term in title_text for term in PROFILE_LOW_VALUE_TITLE_TERMS):
            priority -= 25
        if score and section.content.strip():
            scored.append((priority + score, -(section.start_line or 0), section))
    scored.sort(key=lambda item: (item[0], item[1], len(item[2].content)), reverse=True)
    if scored:
        return [section for _, _line, section in scored[:limit]]
    return [section for section in sections if section.content.strip()][:limit]


def _render_sections(sections: list[MarkdownSection]) -> str:
    blocks = []
    for section in sections:
        blocks.append(
            "\n".join(
                [
                    f"section_id: {section.id}",
                    f"title_path: {' > '.join(section.title_path)}",
                    "content:",
                    section.content[:1800],
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def _compact_toc(toc_items: list[SourceTocItem]) -> list[dict]:
    return [
        {
            "section_id": item.section_id,
            "title_path": item.title_path,
            "level": item.level,
            "char_count": item.char_count,
        }
        for item in toc_items
    ]


def _fallback_profile(sections: list[MarkdownSection]) -> ProjectProfile:
    source_profile = _profile_from_source_sections(sections)
    source_ids = [section.id for section in sections[:8]]
    source_profile.source_section_ids = source_ids
    source_profile.missing_items.append("AI 项目概况抽取失败，已使用源文档启发式画像；请人工核验项目名称、类型、地点、范围、工期和质量安全环保目标。")
    return source_profile


def _repair_profile_source_ids(
    profile: ProjectProfile,
    toc_items: list[SourceTocItem],
    result,
) -> ProjectProfile:
    if not any(issue.code == "invalid_source_section_id" for issue in result.issues):
        return profile
    valid_ids = {item.section_id for item in toc_items}
    cleaned_ids = [section_id for section_id in profile.source_section_ids if section_id in valid_ids]
    dropped_ids = [section_id for section_id in profile.source_section_ids if section_id not in valid_ids]
    if not dropped_ids:
        return profile
    data = dump_model(profile)
    data["source_section_ids"] = cleaned_ids
    missing_items = list(data.get("missing_items") or [])
    missing_items.append(
        "AI project profile referenced invalid source_section_ids; invalid ids were removed: "
        + ", ".join(dropped_ids)
    )
    data["missing_items"] = missing_items
    return ProjectProfile(**data)


def _repair_profile_semantics(profile: ProjectProfile, sections: list[MarkdownSection]) -> ProjectProfile:
    source_profile = _profile_from_source_sections(sections)
    data = dump_model(profile)
    missing_items = list(data.get("missing_items") or [])

    if _is_suspicious_project_name(profile.project_name):
        if source_profile.project_name:
            data["project_name"] = source_profile.project_name
            missing_items.append("ProjectProfile project_name looked like a section heading and was repaired from source text.")
    for field in [
        "project_type",
        "location",
        "construction_scope",
        "key_quantities",
        "main_methods",
        "schedule",
        "quality_safety_environment_targets",
        "risk_points",
    ]:
        value = data.get(field)
        if value and not _is_generic_profile_field_value(value):
            continue
        replacement = getattr(source_profile, field)
        if replacement:
            data[field] = replacement
            missing_items.append(f"ProjectProfile field `{field}` was repaired from source text.")

    existing_source_ids = [section_id for section_id in data.get("source_section_ids") or [] if section_id]
    for section_id in source_profile.source_section_ids:
        if section_id not in existing_source_ids:
            existing_source_ids.append(section_id)
    data["source_section_ids"] = existing_source_ids[:12]
    data["missing_items"] = _dedupe(missing_items)
    return ProjectProfile(**data)


def _profile_from_source_sections(sections: list[MarkdownSection]) -> ProjectProfile:
    text = "\n".join(_section_text(section) for section in sections)
    source_ids = [section.id for section in sections[:8]]
    project_name = _extract_project_name(sections, text)
    return ProjectProfile(
        project_name=project_name,
        project_type=_extract_project_type(text),
        location=_extract_location(text),
        construction_scope=_extract_scope(sections),
        key_quantities=_extract_quantities(text),
        main_methods=_extract_methods(text),
        schedule=_extract_schedule(text),
        quality_safety_environment_targets=_extract_quality_targets(sections),
        risk_points=_extract_risks(text),
        missing_items=[],
        source_section_ids=source_ids,
    )


def _section_text(section: MarkdownSection) -> str:
    return "\n".join([" > ".join(section.title_path), section.content])


def _extract_project_name(sections: list[MarkdownSection], text: str) -> str | None:
    for section in sections:
        title = " > ".join(section.title_path)
        if "项目名称" not in title and "工程名称" not in title and "项目基本信息" not in title:
            continue
        candidate = _extract_quoted_project_name(section.content) or _extract_named_value(section.content)
        if candidate:
            return candidate
    quoted = _extract_quoted_project_name(text)
    if quoted:
        return quoted
    match = re.search(r"([\u4e00-\u9fffA-Za-z0-9（）()、·\-]{8,80}(?:项目|工程)(?:[\u4e00-\u9fffA-Za-z0-9（）()、·\-]{0,40})(?:施工|治理|建设)?)", text)
    return _clean_profile_value(match.group(1)) if match else None


def _extract_quoted_project_name(text: str) -> str | None:
    patterns = [
        r"本项目为[“\"]([^”\"\n]{6,120})[”\"]",
        r"项目名称[：:]\s*[“\"]?([^”\"\n。；;]{6,120})",
        r"工程名称[：:]\s*[“\"]?([^”\"\n。；;]{6,120})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean_profile_value(match.group(1))
    return None


def _extract_named_value(text: str) -> str | None:
    for line in text.splitlines():
        if "项目名称" in line or "工程名称" in line:
            parts = re.split(r"[：:]", line, maxsplit=1)
            if len(parts) == 2:
                return _clean_profile_value(parts[1])
    return None


def _extract_project_type(text: str) -> str | None:
    if "煤火" in text or "火区" in text:
        return "煤火区安全与生态治理"
    if "光伏" in text:
        return "光伏工程"
    if "风电" in text:
        return "风电工程"
    if "水利" in text or "水电" in text:
        return "水利水电工程"
    if "市政" in text:
        return "市政工程"
    return None


def _extract_location(text: str) -> str | None:
    match = re.search(r"(?:项目)?位于([^。\n；;]{4,120})", text)
    if match:
        return _clean_profile_value(match.group(1))
    match = re.search(r"行政区划属([^。\n；;]{4,80})", text)
    return _clean_profile_value(match.group(1)) if match else None


def _extract_scope(sections: list[MarkdownSection]) -> list[str]:
    output: list[str] = []
    for section in sections:
        title = " > ".join(section.title_path)
        if not any(term in title for term in ["施工内容", "工作内容", "工程范围", "施工范围", "工程概况", "项目名称"]):
            continue
        output.extend(_important_sentences(section.content, ["治理", "施工", "范围", "主要工作", "内容", "面积"], limit=3))
    return _dedupe(output)[:6]


def _extract_quantities(text: str) -> list[str]:
    patterns = [
        r"[^。\n；;]{0,30}(?:面积|长度|数量|工程量|工期|孔深|孔径|厚度|压力|流量)[^。\n；;]{0,80}(?:公顷|m2|㎡|m³|m3|MPa|天|日|米|m)[^。\n；;]{0,30}",
        r"[^。\n；;]{0,20}\d+(?:\.\d+)?\s*(?:公顷|m2|㎡|m³|m3|MPa|天|日|米|m)[^。\n；;]{0,50}",
    ]
    items: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            items.append(_clean_profile_value(match.group(0)))
    return _dedupe([item for item in items if len(item) >= 4])[:10]


def _extract_methods(text: str) -> list[str]:
    methods = []
    for keyword in ["注水降温", "注水", "钻孔", "灌注浆", "灌浆", "覆盖封堵", "覆盖", "监测评价", "生态恢复", "采坑回填", "黄土覆盖"]:
        if keyword in text and keyword not in methods:
            methods.append(keyword)
    return methods[:10]


def _extract_schedule(text: str) -> list[str]:
    return _dedupe(_important_sentences(text, ["工期", "进度", "计划", "开工", "完工"], limit=4))


def _extract_quality_targets(sections: list[MarkdownSection]) -> list[str]:
    output: list[str] = []
    for section in sections:
        if any(term in " > ".join(section.title_path) for term in ["质量", "安全", "环保", "环境"]):
            output.extend(_important_sentences(section.content, ["符合", "满足", "标准", "质量", "安全", "环保"], limit=3))
    return _dedupe(output)[:6]


def _extract_risks(text: str) -> list[str]:
    risks = []
    for keyword in ["高温火区", "裂隙", "塌陷", "采空区", "复燃", "水文地质", "生态环境", "安全风险"]:
        if keyword in text:
            risks.append(keyword)
    return risks[:8]


def _important_sentences(text: str, keywords: list[str], *, limit: int) -> list[str]:
    sentences = [item.strip() for item in re.split(r"[。\n；;]", text) if item.strip()]
    output = []
    for sentence in sentences:
        if any(keyword in sentence for keyword in keywords):
            output.append(_clean_profile_value(sentence))
        if len(output) >= limit:
            break
    return output


def _is_suspicious_project_name(value: str | None) -> bool:
    if not value:
        return True
    cleaned = value.strip()
    if cleaned in PROFILE_LOW_VALUE_TITLE_TERMS:
        return True
    if any(term == cleaned for term in ["工程概况", "项目概况", "项目名称", "具体施工内容", "质量要求"]):
        return True
    if cleaned in {"示例项目", "测试项目", "demo", "Demo"}:
        return True
    if "示例" in cleaned or "测试" in cleaned:
        return True
    return len(cleaned) < 6 and not any(term in cleaned for term in ["项目", "工程"])


def _is_generic_profile_field_value(value) -> bool:
    if value is None:
        return True
    values = value if isinstance(value, list) else [value]
    if not values:
        return True
    joined = " ".join(str(item) for item in values if str(item).strip())
    generic_markers = ["示例", "测试", "生成测试", "依据投标文件生成施工组织设计正文", "local demo"]
    return bool(joined) and any(marker in joined for marker in generic_markers)


def _clean_profile_value(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ：:，,；;。、“”\"")
    return value[:180]


def _dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in output:
            output.append(cleaned)
    return output
