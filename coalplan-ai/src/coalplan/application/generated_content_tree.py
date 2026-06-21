from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha1

from coalplan.domain.generated_content import GeneratedContentNode, GeneratedContentSourceLink, GeneratedContentTree
from coalplan.domain.outline import SourceEvidenceSpan, SourceMappingResult


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def build_generated_content_tree(
    *,
    node_id: str,
    title: str,
    markdown: str,
    version_id: str | None = None,
    source_mapping: SourceMappingResult | dict | None = None,
    fallback_tree: GeneratedContentTree | dict | None = None,
) -> GeneratedContentTree:
    mapping = _coerce_mapping(source_mapping)
    fallback = _coerce_tree(fallback_tree)
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    events = _heading_events(lines)
    if not events:
        root = GeneratedContentNode(
            id=_content_node_id(node_id, [title], 1),
            title=title,
            level=1,
            title_path=[title],
            start_line=1,
            end_line=max(1, len(lines)),
            markdown=markdown,
            body=markdown.strip(),
            source_links=_source_links(markdown, mapping),
        )
        tree = GeneratedContentTree(version_id=version_id, node_id=node_id, title=title, markdown_line_count=len(lines), nodes=[root])
        _carry_fallback_links(tree.nodes, fallback)
        return tree

    built: list[_MutableNode] = []
    stack: list[_MutableNode] = []
    for index, event in enumerate(events):
        end_line = (events[index + 1].line_no - 1) if index + 1 < len(events) else len(lines)
        body_start = event.line_no
        body_end = end_line
        block_lines = lines[event.line_no - 1:end_line]
        body_lines = lines[body_start:body_end]
        while stack and stack[-1].level >= event.level:
            stack.pop()
        title_path = [*(stack[-1].title_path if stack else []), event.title]
        node = _MutableNode(
            id=_content_node_id(node_id, title_path, event.line_no),
            title=event.title,
            level=event.level,
            title_path=title_path,
            start_line=event.line_no,
            end_line=end_line,
            markdown="\n".join(block_lines).strip(),
            body="\n".join(body_lines).strip(),
            source_links=_source_links("\n".join(block_lines), mapping),
        )
        if stack:
            stack[-1].children.append(node)
        else:
            built.append(node)
        stack.append(node)
    tree = GeneratedContentTree(
        version_id=version_id,
        node_id=node_id,
        title=title,
        markdown_line_count=len(lines),
        nodes=[item.to_model() for item in built],
    )
    _carry_fallback_links(tree.nodes, fallback)
    return tree


def replace_content_node_markdown(markdown: str, *, node_id: str, content_node_id: str, replacement_markdown: str) -> str:
    tree = build_generated_content_tree(node_id=node_id, title=node_id, markdown=markdown)
    target = _find_node(tree.nodes, content_node_id)
    if target is None:
        raise KeyError(f"Unknown content_node_id: {content_node_id}")
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    replacement = _normalize_replacement(target, replacement_markdown).split("\n")
    start = max(0, target.start_line - 1)
    end = max(start, target.end_line)
    new_lines = [*lines[:start], *replacement, *lines[end:]]
    return "\n".join(new_lines).rstrip() + "\n"


def _normalize_replacement(target: GeneratedContentNode, replacement_markdown: str) -> str:
    replacement = replacement_markdown.strip()
    if not replacement:
        replacement = target.markdown.strip()
    first = replacement.splitlines()[0] if replacement.splitlines() else ""
    if HEADING_RE.match(first):
        return replacement
    heading = "#" * min(max(target.level, 1), 6)
    return f"{heading} {target.title}\n{replacement}".strip()


@dataclass(frozen=True)
class _HeadingEvent:
    line_no: int
    level: int
    title: str


@dataclass
class _MutableNode:
    id: str
    title: str
    level: int
    title_path: list[str]
    start_line: int
    end_line: int
    markdown: str
    body: str
    source_links: list[GeneratedContentSourceLink]
    children: list["_MutableNode"] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.children is None:
            self.children = []

    def to_model(self) -> GeneratedContentNode:
        return GeneratedContentNode(
            id=self.id,
            title=self.title,
            level=self.level,
            title_path=self.title_path,
            start_line=self.start_line,
            end_line=self.end_line,
            markdown=self.markdown,
            body=self.body,
            source_links=self.source_links,
            children=[child.to_model() for child in self.children],
        )


def _heading_events(lines: list[str]) -> list[_HeadingEvent]:
    events: list[_HeadingEvent] = []
    for index, line in enumerate(lines, start=1):
        match = HEADING_RE.match(line.strip())
        if match:
            events.append(_HeadingEvent(line_no=index, level=len(match.group(1)), title=match.group(2).strip()))
    return events


def _content_node_id(node_id: str, title_path: list[str], start_line: int) -> str:
    text = "::".join([node_id, *title_path, str(start_line)])
    return f"gcn_{sha1(text.encode('utf-8')).hexdigest()[:12]}"


def _coerce_mapping(source_mapping: SourceMappingResult | dict | None) -> SourceMappingResult | None:
    if source_mapping is None:
        return None
    if isinstance(source_mapping, SourceMappingResult):
        return source_mapping
    return SourceMappingResult.model_validate(source_mapping)


def _coerce_tree(fallback_tree: GeneratedContentTree | dict | None) -> GeneratedContentTree | None:
    if fallback_tree is None:
        return None
    if isinstance(fallback_tree, GeneratedContentTree):
        return fallback_tree
    return GeneratedContentTree.model_validate(fallback_tree)


def _carry_fallback_links(nodes: list[GeneratedContentNode], fallback_tree: GeneratedContentTree | None) -> None:
    if fallback_tree is None:
        return
    fallback_by_path = {tuple(node.title_path): node.source_links for node in _walk_nodes(fallback_tree.nodes) if node.source_links}
    for node in _walk_nodes(nodes):
        if node.source_links:
            continue
        links = fallback_by_path.get(tuple(node.title_path))
        if links:
            node.source_links = links


def _source_links(markdown: str, mapping: SourceMappingResult | None) -> list[GeneratedContentSourceLink]:
    if mapping is None:
        return []
    explicit = _explicit_links(markdown, mapping)
    if explicit:
        return explicit[:5]
    scored: list[GeneratedContentSourceLink] = []
    for span in mapping.evidence:
        score, terms = _evidence_score(markdown, span)
        if score <= 0:
            continue
        scored.append(
            GeneratedContentSourceLink(
                evidence_id=span.evidence_id,
                section_id=span.section_id,
                title_path=span.title_path,
                confidence=round(min(1.0, 0.35 + score / 14), 3),
                reason="generated_subsection_keyword_overlap",
                matched_terms=terms[:8],
            )
        )
    scored.sort(key=lambda item: item.confidence, reverse=True)
    return scored[:5]


def _explicit_links(markdown: str, mapping: SourceMappingResult) -> list[GeneratedContentSourceLink]:
    links: list[GeneratedContentSourceLink] = []
    evidence_by_id = {span.evidence_id: span for span in mapping.evidence}
    section_by_id = {match.section_id: match for match in mapping.matches}
    for evidence_id in dict.fromkeys(re.findall(r"ev_[0-9a-f]{12}", markdown)):
        span = evidence_by_id.get(evidence_id)
        if not span:
            continue
        links.append(
            GeneratedContentSourceLink(
                evidence_id=span.evidence_id,
                section_id=span.section_id,
                title_path=span.title_path,
                confidence=1.0,
                reason="explicit_evidence_id",
                matched_terms=[],
            )
        )
    for section_id in dict.fromkeys(re.findall(r"sec_[0-9a-f]{12}", markdown)):
        if any(link.section_id == section_id for link in links):
            continue
        match = section_by_id.get(section_id)
        if not match:
            continue
        links.append(
            GeneratedContentSourceLink(
                evidence_id=None,
                section_id=section_id,
                title_path=match.title_path,
                confidence=0.8,
                reason="explicit_section_id",
                matched_terms=[],
            )
        )
    return links


def _evidence_score(markdown: str, span: SourceEvidenceSpan) -> tuple[float, list[str]]:
    text = _compact(markdown)
    terms = [*span.matched_terms, *(_terms(span.summary)), *(_terms(" ".join(span.title_path)))]
    seen: list[str] = []
    score = 0.0
    for term in terms:
        if not term or term in seen:
            continue
        seen.append(term)
        count = text.count(term)
        if count:
            score += min(count, 4) * (1.0 + min(len(term), 8) / 12)
    return score, seen


def _terms(text: str) -> list[str]:
    stop = {"主要来源", "生成正文", "人工补充", "特殊备注", "施工", "工程", "章节"}
    return [
        item
        for item in re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z][A-Za-z0-9_-]{1,30}|\d+(?:\.\d+)?[A-Za-z%]*", text or "")
        if item not in stop
    ]


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _find_node(nodes: list[GeneratedContentNode], node_id: str) -> GeneratedContentNode | None:
    for node in nodes:
        if node.id == node_id:
            return node
        found = _find_node(node.children, node_id)
        if found:
            return found
    return None


def _walk_nodes(nodes: list[GeneratedContentNode]):
    for node in nodes:
        yield node
        yield from _walk_nodes(node.children)
