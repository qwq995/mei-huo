from __future__ import annotations

from coalplan.application.serialization import dump_model, to_json_text
from coalplan.domain.documents import MarkdownSection, SourceTocItem
from coalplan.domain.profile import ProjectProfile
from coalplan.infrastructure.validation.json_contract import ProjectProfileValidator
from coalplan.ports.llm import StructuredLLMClient
from coalplan.ports.repository import ArtifactRepository


PROFILE_KEYWORDS = [
    "工程概况",
    "项目概况",
    "工程范围",
    "工作内容",
    "工程量",
    "工期",
    "质量",
    "安全",
    "环境",
    "水文",
    "地质",
    "施工条件",
]


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
        fallback = _fallback_profile(source_sections)
        fallback.missing_items.extend(f"AI 项目概况输出校验失败：{issue.message}" for issue in result.issues)
        profile = fallback
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
    scored: list[tuple[int, MarkdownSection]] = []
    for section in sections:
        haystack = f"{section.path_text}\n{section.content}"
        score = sum(1 for keyword in PROFILE_KEYWORDS if keyword in haystack)
        if score and section.content.strip():
            scored.append((score, section))
    scored.sort(key=lambda item: (item[0], len(item[1].content)), reverse=True)
    if scored:
        return [section for _, section in scored[:limit]]
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
    first = next((section for section in sections if section.content.strip()), None)
    source_ids = [section.id for section in sections[:8]]
    return ProjectProfile(
        project_name=first.title_path[-1] if first and first.title_path else None,
        project_type=None,
        location=None,
        construction_scope=[],
        key_quantities=[],
        main_methods=[],
        schedule=[],
        quality_safety_environment_targets=[],
        risk_points=[],
        missing_items=["AI 项目概况抽取失败，已使用基础兜底画像；请人工补充项目名称、类型、地点、范围、工期和质量安全环保目标。"],
        source_section_ids=source_ids,
    )
