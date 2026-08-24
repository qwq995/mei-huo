from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from coalplan.domain.documents import stable_id
from coalplan.domain.standard_constraints import (
    ComplianceFinding,
    ComplianceReviewRun,
    ConstraintAtom,
    ConstraintMatch,
    ConstraintReviewStatus,
    ConstraintSeverity,
    FindingStatus,
    StandardDocument,
    StandardDocumentStatus,
    StandardMatch,
)


MAX_ATOMS_PER_CHAPTER = 18
DOCUMENT_MATCH_BATCH_SIZE = 20
CONSTRAINT_MATCH_BATCH_SIZE = 30


@dataclass(frozen=True)
class ReviewChapter:
    node_id: str
    title: str
    version_id: str
    markdown: str


def match_standard_documents(
    *,
    documents: list[StandardDocument],
    project_text: str,
    llm,
    existing_matches: list[StandardMatch] | None = None,
    candidate_documents: list[StandardDocument] | None = None,
    warnings: list[str] | None = None,
) -> list[StandardMatch]:
    existing = {item.document_id: item for item in (existing_matches or [])}
    matches: list[StandardMatch] = []
    source_documents = candidate_documents if candidate_documents is not None else documents
    candidates = [item for item in source_documents if item.status not in {StandardDocumentStatus.failed, StandardDocumentStatus.excluded}]
    for offset in range(0, len(candidates), DOCUMENT_MATCH_BATCH_SIZE):
        batch = candidates[offset : offset + DOCUMENT_MATCH_BATCH_SIZE]
        items = _match_document_batch_resilient(project_text, batch, llm, warnings)
        by_id = {item.id: item for item in batch}
        returned: set[str] = set()
        for item in items:
            document_id = str(item.get("document_id") or "")
            if document_id not in by_id:
                continue
            returned.add(document_id)
            previous = existing.get(document_id)
            decision = previous.decision if previous else ("selected" if bool(item.get("applicable", False)) else "suggested")
            matches.append(StandardMatch(
                document_id=document_id,
                score=_score(item.get("score")),
                match_reason=str(item.get("match_reason") or "AI 未提供匹配理由").strip(),
                decision=decision,
            ))
        for document in batch:
            if document.id in returned:
                continue
            if document.id in existing:
                matches.append(existing[document.id])
            else:
                matches.append(StandardMatch(
                    document_id=document.id,
                    score=0.0,
                    match_reason="AI 未返回该规范的适用性判断，需人工确认。",
                    decision="suggested",
                ))
    matched_ids = {item.document_id for item in matches}
    for item in existing.values():
        if item.document_id not in matched_ids:
            matches.append(item)
    return sorted(matches, key=lambda item: (item.decision == "selected", item.score), reverse=True)


def match_constraints(
    *, atoms: list[ConstraintAtom], chapter: ReviewChapter, llm,
    candidate_atoms: list[ConstraintAtom] | None = None,
    warnings: list[str] | None = None,
) -> list[tuple[ConstraintAtom, float, str]]:
    ranked: list[tuple[ConstraintAtom, float, str]] = []
    source_atoms = candidate_atoms if candidate_atoms is not None else atoms
    published = [atom for atom in source_atoms if atom.status == ConstraintReviewStatus.published]
    for offset in range(0, len(published), CONSTRAINT_MATCH_BATCH_SIZE):
        batch = published[offset : offset + CONSTRAINT_MATCH_BATCH_SIZE]
        items = _match_constraint_batch_resilient(chapter, batch, llm, warnings)
        by_id = {item.id: item for item in batch}
        for item in items:
            atom = by_id.get(str(item.get("atom_id") or ""))
            if atom is None or not bool(item.get("applicable", True)):
                continue
            ranked.append((atom, _score(item.get("score")), str(item.get("match_reason") or "AI 判定条款与章节相关").strip()))
    return sorted(ranked, key=lambda item: item[1], reverse=True)[:MAX_ATOMS_PER_CHAPTER]


def run_compliance_review(*, project_id: str, pipeline, repository, progress=None) -> dict[str, Any]:
    project = pipeline.projects.get(project_id)
    chapters = selected_review_chapters(project_id, pipeline.workspace_store)
    if not chapters:
        raise ValueError("当前没有已选用的章节版本，请先生成或手动保存章节。")
    run = ComplianceReviewRun(id=f"review_{uuid4().hex[:16]}", project_id=project_id, chapter_count=len(chapters))
    repository.create_review_run(run)
    project_text = _project_context(project, chapters)
    warnings: list[str] = []
    all_documents = repository.list_documents()
    selected_existing = {
        item.document_id for item in repository.list_project_matches(project_id) if item.decision == "selected"
    }
    candidate_documents = repository.search_document_candidates(
        project_text,
        include_document_ids=selected_existing,
    ) if hasattr(repository, "search_document_candidates") else None
    if candidate_documents is None:
        candidate_documents = all_documents
    matches = match_standard_documents(
        documents=all_documents,
        project_text=project_text,
        llm=pipeline._structured_llm(),
        existing_matches=repository.list_project_matches(project_id),
        candidate_documents=candidate_documents,
        warnings=warnings,
    )
    repository.replace_project_matches(project_id, matches)
    selected_doc_ids = {item.document_id for item in matches if item.decision == "selected"}
    atoms = [atom for atom in repository.list_atoms(status=ConstraintReviewStatus.published) if atom.document_id in selected_doc_ids]
    findings: list[ComplianceFinding] = []
    candidate_count = 0
    total = len(chapters)
    for index, chapter in enumerate(chapters, start=1):
        if progress:
            progress("constraint_matching", index - 1, total, f"正在匹配第 {index}/{total} 个章节：{chapter.title}")
        candidate_atoms = repository.search_constraint_candidates(
            f"{chapter.title}\n{chapter.markdown[:12000]}", selected_doc_ids,
        ) if hasattr(repository, "search_constraint_candidates") else None
        if candidate_atoms is None:
            candidate_atoms = atoms
        candidates = match_constraints(
            atoms=atoms,
            candidate_atoms=candidate_atoms,
            chapter=chapter,
            llm=pipeline._structured_llm(),
            warnings=warnings,
        )
        candidate_count += len(candidates)
        repository.save_constraint_matches(
            [ConstraintMatch(
                run_id=run.id,
                atom_id=atom.id,
                document_id=atom.document_id,
                node_id=chapter.node_id,
                score=score,
                match_reason=reason,
            ) for atom, score, reason in candidates],
            project_id=project_id,
            chapter_version_id=chapter.version_id,
        )
        if not candidates:
            continue
        deterministic, ai_candidates = _deterministic_findings(project_id, run.id, chapter, candidates)
        findings.extend(deterministic)
        if not ai_candidates:
            continue
        try:
            payload = pipeline._structured_llm().complete_json(
                _review_prompt(chapter, ai_candidates),
                schema_name="standard_compliance_review",
            )
        except Exception as exc:
            warnings.append(f"章节《{chapter.title}》违规判断失败，已保留其他章节结果：{exc}")
            continue
        findings.extend(_materialize_findings(project_id, run.id, chapter, ai_candidates, payload))
    if progress:
        progress("compliance_review", total, total, "规范符合性审查完成")
    open_count = sum(item.status == FindingStatus.open for item in findings)
    summary = {
        "chapter_versions": {chapter.node_id: chapter.version_id for chapter in chapters},
        "standard_matches": [item.model_dump(mode="json") for item in matches],
        "selected_document_ids": sorted(selected_doc_ids),
    }
    completed = repository.complete_review_run(
        run.id,
        status="completed" if not warnings else "partial",
        chapter_count=len(chapters),
        matched_document_count=len(selected_doc_ids),
        candidate_constraint_count=candidate_count,
        findings=findings,
        warnings=warnings,
        summary=summary,
    )
    return {
        "run": completed.model_dump(mode="json"),
        "project_id": project_id,
        "standard_matches": [item.model_dump(mode="json") for item in matches],
        "matched_document_count": len(selected_doc_ids),
        "published_constraint_count": len(atoms),
        "candidate_constraint_count": candidate_count,
        "finding_count": len(findings),
        "open_count": open_count,
        "ai_fixable_count": sum(item.ai_fixable for item in findings),
        "warnings": warnings,
        "findings": [item.model_dump(mode="json") for item in findings],
        "message": "未发现明确违规项" if not findings else f"发现 {len(findings)} 项需要确认，其中 {sum(item.ai_fixable for item in findings)} 项可由 AI 协助修复",
    }


def _match_document_batch_resilient(
    project_text: str,
    documents: list[StandardDocument],
    llm,
    warnings: list[str] | None,
) -> list[dict[str, Any]]:
    try:
        payload = llm.complete_json(_document_match_prompt(project_text, documents), schema_name="standard_document_matching")
        return list(payload.get("matches", []))
    except Exception as exc:
        if len(documents) > 1:
            middle = len(documents) // 2
            return [
                *_match_document_batch_resilient(project_text, documents[:middle], llm, warnings),
                *_match_document_batch_resilient(project_text, documents[middle:], llm, warnings),
            ]
        if warnings is not None:
            warnings.append(f"规范《{documents[0].name}》AI 适用性判断失败，已转为人工确认：{exc}")
        return []


def _match_constraint_batch_resilient(
    chapter: ReviewChapter,
    atoms: list[ConstraintAtom],
    llm,
    warnings: list[str] | None,
) -> list[dict[str, Any]]:
    try:
        payload = llm.complete_json(_constraint_match_prompt(chapter, atoms), schema_name="standard_constraint_matching")
        return list(payload.get("matches", []))
    except Exception as exc:
        if len(atoms) > 1:
            middle = len(atoms) // 2
            return [
                *_match_constraint_batch_resilient(chapter, atoms[:middle], llm, warnings),
                *_match_constraint_batch_resilient(chapter, atoms[middle:], llm, warnings),
            ]
        if warnings is not None:
            atom = atoms[0]
            warnings.append(f"条款 {atom.standard_code} {atom.clause_no or atom.id} AI 匹配失败，已跳过并保留人工复核入口：{exc}")
        return []


def selected_review_chapters(project_id: str, workspace_store) -> list[ReviewChapter]:
    chapters: list[ReviewChapter] = []
    for node in workspace_store.list_outline_nodes(project_id):
        selected_id = node.get("selected_version_id")
        if not selected_id:
            continue
        try:
            version = workspace_store.get_version(project_id, node["node_id"], selected_id)
        except KeyError:
            continue
        if (version.get("markdown") or "").strip():
            chapters.append(ReviewChapter(node["node_id"], node["title"], selected_id, version["markdown"]))
    return chapters


def ai_repair_finding(*, project_id: str, finding_id: str, pipeline, repository) -> dict[str, Any]:
    finding = repository.get_finding(project_id, finding_id)
    if not finding.ai_fixable:
        raise ValueError("该问题涉及项目事实、审批或检测依据，不能由 AI 自动补写。")
    version = pipeline.workspace_store.get_version(project_id, finding.node_id, finding.chapter_version_id or "")
    prompt = f"""你负责修订施工组织设计中的单个规范违规项。仅修订正文以满足给定条款，不得新增工程量、参数、审批结果、检测结论或其他项目事实。

章节标题：{finding.chapter_title}
规范：{finding.standard_code} {finding.standard_name} 第 {finding.clause_no or '相关'} 条
规范原文：{finding.constraint_text}
违规说明：{finding.explanation}
修复建议：{finding.suggested_fix}

请返回完整修订后 Markdown，保留原有标题层级和已有事实。若缺少事实依据，应保留【需人工补充：...】占位。

原章节：
{version['markdown']}"""
    revised = _strip_markdown_fence(pipeline.llm.complete(prompt).strip())
    if not revised:
        raise ValueError("AI 未返回可保存的修订内容。")
    created = pipeline.workspace_store.create_chapter_version(
        project_id,
        finding.node_id,
        title=version["title"],
        markdown=revised,
        source_type="compliance_ai_repair",
        source_section_ids=version.get("source_section_ids", []),
        supplement_ids=version.get("supplement_ids", []),
        created_by="ai",
        select=True,
    )
    resolved = repository.resolve_finding(
        project_id,
        finding_id,
        status=FindingStatus.pending_recheck,
        note="AI 已创建并选用新的合规修订版本，待重新审查确认。",
        resolved_version_id=created["id"],
    )
    return {"finding": resolved.model_dump(mode="json"), "version": created}


def recheck_finding(*, project_id: str, finding_id: str, pipeline, repository) -> dict[str, Any]:
    finding = repository.get_finding(project_id, finding_id)
    result = run_compliance_review(project_id=project_id, pipeline=pipeline, repository=repository)
    still_violated = any(
        item["atom_id"] == finding.atom_id and item["node_id"] == finding.node_id
        for item in result["findings"]
    )
    updated = repository.resolve_finding(
        project_id,
        finding_id,
        status=FindingStatus.open if still_violated else FindingStatus.ai_resolved,
        note="复审仍发现该条款问题。" if still_violated else "复审未再发现该条款问题。",
    )
    return {"finding": updated.model_dump(mode="json"), "review": result}


def _project_context(project, chapters: list[ReviewChapter]) -> str:
    parts = [project.name, project.template_id]
    profile = getattr(project, "profile", None)
    if profile:
        parts.append(str(profile.model_dump(mode="json") if hasattr(profile, "model_dump") else profile))
    parts.extend(f"{chapter.title}\n{chapter.markdown[:1200]}" for chapter in chapters)
    return "\n".join(parts)


def _review_prompt(chapter: ReviewChapter, candidates: list[tuple[ConstraintAtom, float, str]]) -> str:
    constraints = "\n\n".join(
        f"[atom_id={atom.id}; standard={atom.standard_code} {atom.standard_name}; clause={atom.clause_no or '-'}; type={atom.constraint_type}; ai_fixable={str(atom.ai_fixable).lower()}]\n原文：{atom.source_text}\n审查要求：{atom.normalized_requirement}\n适用条件：{'；'.join(atom.applicability) or '-'}"
        for atom, _, _ in candidates
    )
    return f"""你是施工组织设计成稿的规范符合性审查员。只判断下列候选条款是否被当前章节明确违反。

判断规则：
1. 只输出明确违反或明确缺失必要措施的条款；已满足、无法判断、明显不适用的条款不要输出。
2. 不得因正文未复述规范全文就判违规。涉及审批、检测、现场参数等外部事实，若正文没有声称已完成，仅标记为需人工确认，不得虚构结论。
3. evidence_quote 必须逐字引用当前章节中的相关句子；没有可引用句子时留空。
4. ai_fixable 不得超过约束原子自身给出的可修复边界。
5. 返回 JSON：{{"violations":[{{"atom_id":"","verdict":"violated|needs_confirmation","explanation":"","evidence_quote":"","suggested_fix":"","ai_fixable":false}}]}}

章节：{chapter.title}
版本：{chapter.version_id}
正文：
{chapter.markdown}

候选条款：
{constraints}"""


def _document_match_prompt(project_text: str, documents: list[StandardDocument]) -> str:
    candidates = "\n".join(
        f"- document_id={item.id}; code={item.standard_code}; name={item.name}; category={item.category}; disciplines={'、'.join(item.disciplines) or '-'}; project_types={'、'.join(item.project_types) or '-'}"
        for item in documents
    )
    return f"""你负责批量判断工程规范是否适用于当前施工组织设计项目。逐份判断专业范围、工程对象、施工活动和规范用途；不要使用固定关键词计数，不要因为同属水利水电就全部选中。

返回每份候选文档，JSON：{{"matches":[{{"document_id":"","applicable":true,"score":0.0,"match_reason":"具体说明项目活动与规范范围的对应关系"}}]}}。score 为 0~1；信息不足时 applicable=false 并说明需人工确认。

项目上下文：
{project_text[:24000]}

候选规范：
{candidates}"""


def _constraint_match_prompt(chapter: ReviewChapter, atoms: list[ConstraintAtom]) -> str:
    candidates = "\n\n".join(
        f"[atom_id={item.id}; standard={item.standard_code}; clause={item.clause_no}; type={item.constraint_type}]\n要求：{item.normalized_requirement}\n适用条件：{'；'.join(item.applicability) or '-'}\n章节范围：{'；'.join(item.chapter_scopes) or '-'}"
        for item in atoms
    )
    return f"""你负责从已确认适用的规范中，批量召回与当前章节直接相关的具体约束。基于语义、施工对象、工序和适用条件判断，不要做关键词计数。只返回值得进入违规审查的约束；不适用或仅弱相关的条款不要返回。

返回 JSON：{{"matches":[{{"atom_id":"","applicable":true,"score":0.0,"match_reason":""}}]}}，最多返回 {MAX_ATOMS_PER_CHAPTER} 条。

章节标题：{chapter.title}
章节正文：
{chapter.markdown[:28000]}

候选约束：
{candidates}"""


def _materialize_findings(
    project_id: str,
    run_id: str,
    chapter: ReviewChapter,
    candidates: list[tuple[ConstraintAtom, float, str]],
    payload: dict,
) -> list[ComplianceFinding]:
    by_id = {atom.id: atom for atom, _, _ in candidates}
    output: list[ComplianceFinding] = []
    for item in payload.get("violations", []):
        atom = by_id.get(str(item.get("atom_id") or ""))
        verdict = str(item.get("verdict") or "")
        if atom is None or verdict not in {"violated", "needs_confirmation"}:
            continue
        evidence_quote = str(item.get("evidence_quote") or "").strip()
        quote_valid = not evidence_quote or evidence_quote in chapter.markdown
        if not quote_valid:
            verdict = "needs_confirmation"
        ai_fixable = atom.ai_fixable and bool(item.get("ai_fixable", False)) and verdict == "violated"
        output.append(
            ComplianceFinding(
                id=stable_id("finding", f"{run_id}:{chapter.version_id}:{atom.id}"),
                run_id=run_id,
                project_id=project_id,
                node_id=chapter.node_id,
                chapter_title=chapter.title,
                chapter_version_id=chapter.version_id,
                atom_id=atom.id,
                document_id=atom.document_id,
                standard_code=atom.standard_code,
                standard_name=atom.standard_name,
                clause_no=atom.clause_no,
                constraint_text=atom.source_text,
                severity=atom.severity,
                verdict=verdict,
                explanation=(str(item.get("explanation") or "章节内容与该条款存在冲突").strip()
                             + ("；模型引用未在章节正文中验证，需人工确认。" if not quote_valid else "")),
                evidence_quote=evidence_quote if quote_valid else "",
                ai_fixable=ai_fixable,
                suggested_fix=str(item.get("suggested_fix") or atom.repair_instruction).strip(),
            )
        )
    return output


def _deterministic_findings(
    project_id: str,
    run_id: str,
    chapter: ReviewChapter,
    candidates: list[tuple[ConstraintAtom, float, str]],
) -> tuple[list[ComplianceFinding], list[tuple[ConstraintAtom, float, str]]]:
    findings: list[ComplianceFinding] = []
    remaining: list[tuple[ConstraintAtom, float, str]] = []
    for candidate in candidates:
        atom = candidate[0]
        violation = _numeric_threshold_violation(atom, chapter.markdown) if atom.review_method == "numeric_compare" else None
        if violation is None:
            remaining.append(candidate)
            continue
        findings.append(ComplianceFinding(
            id=stable_id("finding", f"{run_id}:{chapter.version_id}:{atom.id}"),
            run_id=run_id,
            project_id=project_id,
            node_id=chapter.node_id,
            chapter_title=chapter.title,
            chapter_version_id=chapter.version_id,
            atom_id=atom.id,
            document_id=atom.document_id,
            standard_code=atom.standard_code,
            standard_name=atom.standard_name,
            clause_no=atom.clause_no,
            constraint_text=atom.source_text,
            severity=atom.severity,
            verdict="violated",
            explanation=violation,
            evidence_quote="",
            ai_fixable=False,
            suggested_fix="请核对当前项目依据后调整数值或保留人工补充说明。",
        ))
    return findings, remaining


def _numeric_threshold_violation(atom: ConstraintAtom, chapter_markdown: str) -> str | None:
    source = re.sub(r"\s+", "", atom.normalized_requirement)
    upper = re.search(r"(?:不宜|不得|不应|不|不超过|不大于)(?:大于|超过)?(\d+(?:\.\d+)?)([a-zA-Z%㎡²]{1,6})", source)
    lower = re.search(r"(?:不宜|不得|不应|不|不少于|不小于)(?:小于|低于)?(\d+(?:\.\d+)?)([a-zA-Z%㎡²]{1,6})", source)
    match = upper or lower
    if match is None:
        return None
    limit = float(match.group(1))
    unit = match.group(2)
    values = [float(value) for value in re.findall(rf"(\d+(?:\.\d+)?)\s*{re.escape(unit)}", chapter_markdown, re.I)]
    if not values:
        return None
    if upper and max(values) > limit:
        return f"程序校验发现章节包含 {max(values):g}{unit}，超过条款上限 {limit:g}{unit}。"
    if lower and min(values) < limit:
        return f"程序校验发现章节包含 {min(values):g}{unit}，低于条款下限 {limit:g}{unit}。"
    return None


def _score(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _strip_markdown_fence(text: str) -> str:
    match = re.match(r"^```(?:markdown|md)?\s*\n(?P<body>.*)\n```\s*$", text, re.S | re.I)
    return match.group("body").strip() if match else text
