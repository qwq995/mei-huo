from __future__ import annotations

import re

from coalplan.domain.reference_library import (
    AtomLeakageIssue,
    AtomRetrievalQuery,
    AtomRetrievalResult,
    ReferenceAtom,
    ReferenceReviewStatus,
)
from coalplan.ports.llm import StructuredLLMClient


TECHNICAL_FAMILIES: dict[str, tuple[str, ...]] = {
    "blasting": ("爆破", "钻爆", "钻孔", "装药", "起爆", "炮孔", "雷管", "炸药", "火工"),
    "excavation": ("开挖", "洞挖", "明挖", "出渣", "超欠挖"),
    "support": ("支护", "锚杆", "钢架", "小导管", "喷射混凝土", "锚喷"),
    "lining_concrete": ("衬砌", "浇筑", "振捣", "入仓", "模板", "钢筋", "养护", "泌水"),
    "grouting": ("灌浆", "注浆", "制浆", "帷幕", "固结", "回填灌浆"),
    "water_diversion": ("导流", "围堰", "截流", "度汛", "排水"),
    "earth_rock_fill": ("填筑", "碾压", "堆石", "土石方", "坝体"),
    "metal_structure": ("金属结构", "闸门", "启闭机", "埋件", "焊接"),
}


def prefilter_reference_atoms(
    atoms: list[ReferenceAtom],
    query: AtomRetrievalQuery,
    *,
    limit: int = 24,
) -> list[ReferenceAtom]:
    query_text = " ".join(
        [query.project_type, query.chapter_title, *query.parent_titles, query.evidence_summary, *query.writing_topics]
    )
    query_terms = _terms(query_text)
    query_families = _technical_families(
        " ".join([query.chapter_title, *query.parent_titles, *query.writing_topics])
    )
    excluded = set(query.excluded_project_names) | {query.project_name}
    scored: list[tuple[float, ReferenceAtom]] = []
    for atom in atoms:
        if atom.status != ReferenceReviewStatus.published or atom.project_name in excluded:
            continue
        if not _semantic_compatible(query_families, atom):
            continue
        atom_text = " ".join(
            [
                atom.project_type,
                *atom.title_path,
                atom.engineering_object,
                atom.specialty,
                atom.work_item,
                atom.process,
                atom.process_stage,
                atom.chapter_type,
                *atom.content_functions,
                *atom.applicability,
                atom.content[:1200],
            ]
        )
        overlap = len(query_terms & _terms(atom_text))
        project_bonus = 3.0 if _project_family(query.project_type) == _project_family(atom.project_type) else 0.0
        scored.append((overlap + project_bonus + atom.quality_score, atom))
    return [atom for _, atom in sorted(scored, key=lambda item: (-item[0], item[1].id))[:limit]]


def retrieve_reference_atoms(
    *,
    atoms: list[ReferenceAtom],
    query: AtomRetrievalQuery,
    llm: StructuredLLMClient,
) -> list[AtomRetrievalResult]:
    candidates = prefilter_reference_atoms(atoms, query)
    if not candidates:
        return []
    payload = llm.complete_json(_rerank_prompt(query, candidates), schema_name="reference_atom_rerank")
    by_id = {atom.id: atom for atom in candidates}
    results: list[AtomRetrievalResult] = []
    seen: set[str] = set()
    for item in payload.get("selected", []):
        atom_id = str(item.get("atom_id", ""))
        if atom_id in seen or atom_id not in by_id:
            continue
        seen.add(atom_id)
        results.append(
            AtomRetrievalResult(
                atom_id=atom_id,
                score=_score(item.get("score")),
                match_reason=str(item.get("match_reason", "")).strip(),
                prompt_use=str(item.get("prompt_use", "")).strip(),
                atom=by_id[atom_id],
            )
        )
        if results[-1].score < 0.62 or not _semantic_compatible(
            _technical_families(" ".join([query.chapter_title, *query.parent_titles, *query.writing_topics])),
            results[-1].atom,
        ):
            results.pop()
            continue
        if len(results) >= max(1, min(query.top_k, 6)):
            break
    return results


def render_reference_atoms_for_prompt(results: list[AtomRetrievalResult]) -> str:
    if not results:
        return "无匹配参考原子。"
    blocks = [
        (
            f"### atom_id: {result.atom_id}\n"
            f"- 来源项目：{result.atom.project_name}（仅为异项目参考）\n"
            f"- 来源标题：{' > '.join(result.atom.title_path)}\n"
            f"- 匹配理由：{result.match_reason}\n"
            f"- 允许借鉴：{result.prompt_use}\n"
            f"- 事实变量（禁止直接迁移）："
            f"{'；'.join(variable.value for variable in result.atom.fact_variables) or '无显式变量'}\n"
            f"- 适用条件：{'；'.join(result.atom.applicability) or '未标注'}\n"
            "```text\n"
            f"{result.atom.content}\n"
            "```"
        )
        for result in results
    ]
    return "\n\n".join(blocks)


def audit_reference_atom_leakage(
    *,
    generated_markdown: str,
    results: list[AtomRetrievalResult],
    trusted_project_text: str,
) -> list[AtomLeakageIssue]:
    issues: list[AtomLeakageIssue] = []
    for result in results:
        values = {variable.value for variable in result.atom.fact_variables if variable.value.strip()}
        values.update(_specific_tokens(result.atom.content))
        for value in sorted(values, key=len, reverse=True):
            if value in generated_markdown and value not in trusted_project_text:
                issues.append(
                    AtomLeakageIssue(
                        atom_id=result.atom_id,
                        value=value,
                        reason="该值仅出现在异项目参考原子中，未在当前项目证据或用户补充中找到",
                    )
                )
    return issues


def build_reference_leakage_repair_prompt(
    *,
    generated_markdown: str,
    issues: list[AtomLeakageIssue],
    trusted_project_text: str,
) -> str:
    issue_lines = "\n".join(
        f"- atom_id={issue.atom_id}；unsupported_value={issue.value}；{issue.reason}" for issue in issues
    )
    return f"""你是施工组织设计事实边界修复助手。下列章节误用了异项目参考原子的参数。

待修复问题：
{issue_lines}

当前项目可信证据：
```text
{trusted_project_text}
```

待修复 Markdown：
```markdown
{generated_markdown}
```

修复规则：
1. 删除或改写所有 unsupported_value；只有可信证据中明确出现的数值、地名、工程量、设备数量、日期和规范版本才可保留。
2. 若该技术控制点仍有必要但可信证据无参数，改为定性控制要求或 `【需人工补充：具体参数】`。
3. 保留原章节结构、当前项目已有事实和有用的工艺闭环，不新增任何事实。
4. 只输出修复后的 Markdown，不要解释。"""


def _rerank_prompt(query: AtomRetrievalQuery, candidates: list[ReferenceAtom]) -> str:
    rows = "\n\n".join(
        (
            f"[atom_id={atom.id}]\n项目类型={atom.project_type}\n标题={' > '.join(atom.title_path)}\n"
            f"标签={atom.engineering_object}/{atom.specialty}/{atom.work_item}/{atom.process}/{atom.process_stage}/"
            f"{atom.chapter_type}\n适用条件={'；'.join(atom.applicability)}\n禁用条件={'；'.join(atom.prohibited_scenarios)}\n"
            f"摘要={atom.content[:700]}"
        )
        for atom in candidates
    )
    return f"""你负责为当前施工组织设计章节匹配异项目优秀参考原子。
当前项目：{query.project_name}
项目类型：{query.project_type}
章节路径：{' > '.join([*query.parent_titles, query.chapter_title])}
当前项目证据摘要：{query.evidence_summary}
写作主题：{'；'.join(query.writing_topics)}

约束：
1. 原子只补充工艺展开、控制维度、检查闭环和专业表达，不是当前项目事实。
2. 适用条件冲突、工程对象不相关、仅项目名称相似的原子不得选择。
3. 不得仅因“控制闭环可以类比”跨工序选择原子，例如爆破章节不得选混凝土泌水、喷射混凝土原子。
4. 最多选择 {max(1, min(query.top_k, 6))} 条；没有足够高相关原子时宁可少选或不选，避免为凑数量引入旁支内容。
5. score 为 0~1；prompt_use 明确说明可借鉴的组织方式，不能建议迁移数值、地名或工程量。

返回 JSON：{{"selected":[{{"atom_id":"","score":0.0,"match_reason":"","prompt_use":""}}]}}

候选原子：
{rows}"""


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z]{2,}|\d+(?:\.\d+)?", text.lower()))


def _specific_tokens(text: str) -> set[str]:
    return set(
        re.findall(
            r"(?:[A-Za-z]{1,6}-)?\d+(?:\.\d+)?(?:m³|m2|m3|mm|cm|m|km|MPa|kPa|d|h|台|套|人|%|℃)"
            r"|(?:DL|GB|SL|NB|JGJ|JTG|DB)[/T\s-]*\d+(?:\.\d+)*(?:-\d{4})?",
            text,
            flags=re.I,
        )
    )


def _project_family(value: str) -> str:
    for family in ("抽水蓄能", "水电", "光伏", "风电", "水环境", "市政", "煤火"):
        if family in value:
            return family
    return value


def _technical_families(text: str) -> set[str]:
    return {
        family
        for family, terms in TECHNICAL_FAMILIES.items()
        if any(term in (text or "") for term in terms)
    }


def _semantic_compatible(query_families: set[str], atom: ReferenceAtom) -> bool:
    if not query_families:
        return True
    atom_core = " ".join(
        [
            *atom.title_path,
            atom.engineering_object,
            atom.specialty,
            atom.work_item,
            atom.process,
            atom.process_stage,
            atom.chapter_type,
            *atom.applicability,
        ]
    )
    atom_families = _technical_families(atom_core)
    return not atom_families or bool(query_families & atom_families)


def _score(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
