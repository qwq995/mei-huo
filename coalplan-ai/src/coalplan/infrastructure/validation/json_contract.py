from __future__ import annotations

from coalplan.domain.documents import SourceTocItem
from coalplan.domain.outline import SourceMappingResult, TemplateOutlinePlan
from coalplan.domain.profile import ProjectProfile
from coalplan.domain.templates import TemplateTree, iter_template_nodes
from coalplan.domain.validation import ValidationIssue, ValidationResult


class ProjectProfileValidator:
    def validate(self, profile: ProjectProfile, toc_items: list[SourceTocItem]) -> ValidationResult:
        valid_ids = {item.section_id for item in toc_items}
        issues: list[ValidationIssue] = []
        for section_id in profile.source_section_ids:
            if section_id not in valid_ids:
                issues.append(ValidationIssue(code="invalid_source_section_id", message=f"Unknown source_section_id: {section_id}"))
        if not profile.project_name:
            issues.append(ValidationIssue(code="missing_project_name", message="Project profile should include project_name when available."))
        return ValidationResult(passed=not issues, issues=issues)


class TemplateOutlinePlanValidator:
    def validate(self, outline: TemplateOutlinePlan, template_tree: TemplateTree, toc_items: list[SourceTocItem]) -> ValidationResult:
        valid_node_ids = {node.id for node in iter_template_nodes(template_tree.nodes)}
        valid_source_ids = {item.section_id for item in toc_items}
        issues: list[ValidationIssue] = []
        for node in outline.nodes:
            if node.node_id not in valid_node_ids:
                issues.append(ValidationIssue(code="invalid_template_node_id", message=f"Unknown template node_id: {node.node_id}"))
            for section_id in node.source_hints:
                if section_id not in valid_source_ids:
                    issues.append(ValidationIssue(code="invalid_source_hint", message=f"Unknown source_hints section_id: {section_id}"))
            if node.enabled and not (node.main_sources and node.auto_fill and node.manual_fill):
                issues.append(ValidationIssue(code="missing_outline_modules", message=f"Outline node lacks required modules: {node.title}"))
        return ValidationResult(passed=not issues, issues=issues)


class SourceMappingValidator:
    def validate(self, mapping: SourceMappingResult, toc_items: list[SourceTocItem]) -> ValidationResult:
        valid_ids = {item.section_id for item in toc_items}
        issues: list[ValidationIssue] = []
        for match in mapping.matches:
            if match.section_id not in valid_ids:
                issues.append(ValidationIssue(code="invalid_mapping_section_id", message=f"Unknown mapping section_id: {match.section_id}"))
            if not 0 <= match.confidence <= 1:
                issues.append(ValidationIssue(code="invalid_mapping_confidence", message=f"Confidence out of range: {match.confidence}"))
        return ValidationResult(passed=not issues, issues=issues)
