from __future__ import annotations

from pydantic import BaseModel, Field

from .documents import stable_id


class TemplateNode(BaseModel):
    id: str
    title: str
    level: int
    source_rules: list[str] = Field(default_factory=list)
    auto_fill: list[str] = Field(default_factory=list)
    manual_fill: list[str] = Field(default_factory=list)
    special_notes: list[str] = Field(default_factory=list)
    target_word_count: int | None = None
    origin: str = "template"
    template_anchor_id: str | None = None
    source_hints: list[str] = Field(default_factory=list)
    matched_skill_keys: list[str] = Field(default_factory=list)
    chapter_summary: dict = Field(default_factory=dict)
    children: list["TemplateNode"] = Field(default_factory=list)

    @property
    def has_generation_contract(self) -> bool:
        return bool(self.source_rules or self.auto_fill or self.manual_fill or self.special_notes)


class TemplateTree(BaseModel):
    id: str
    name: str
    nodes: list[TemplateNode] = Field(default_factory=list)


def make_node_id(title_path: list[str]) -> str:
    return stable_id("tplnode", *title_path)


def iter_template_nodes(nodes: list[TemplateNode]) -> list[TemplateNode]:
    flat: list[TemplateNode] = []
    for node in nodes:
        flat.append(node)
        flat.extend(iter_template_nodes(node.children))
    return flat
