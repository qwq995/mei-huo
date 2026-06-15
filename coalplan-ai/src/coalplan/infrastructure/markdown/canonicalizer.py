from __future__ import annotations

import re


class MarkdownCanonicalizer:
    """Normalize bid markdown into a stable input for section splitting."""

    _frontmatter_re = re.compile(r"\A---\n.*?\n---\n", re.S)

    def canonicalize(self, text: str) -> str:
        text = text.replace("\ufeff", "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = self._frontmatter_re.sub("", text)
        text = re.sub(r"[ \t]+$", "", text, flags=re.M)
        lines = [self._normalize_heading_line(line) for line in text.split("\n")]
        lines = self._drop_obvious_toc_noise(lines)
        return self._collapse_blank_lines(lines).strip() + "\n"

    def _normalize_heading_line(self, line: str) -> str:
        stripped = line.strip()
        if not stripped:
            return ""
        if stripped.startswith("#"):
            return re.sub(r"^(#{1,6})\s*", r"\1 ", stripped)
        return stripped

    def _drop_obvious_toc_noise(self, lines: list[str]) -> list[str]:
        cleaned: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                cleaned.append("")
                continue
            if self._looks_like_toc_dot_leader(stripped):
                continue
            if stripped in {"目录", "目 录", "【目录】"}:
                continue
            cleaned.append(line)
        return cleaned

    def _looks_like_toc_dot_leader(self, line: str) -> bool:
        if len(line) > 160:
            return False
        if re.search(r"[-.·…_]{3,}\s*\d+\s*$", line):
            return True
        if re.search(r"\s{2,}\d{1,4}\s*$", line) and re.match(r"^(第.+章|第.+节|\d+(?:\.\d+){1,3}\s+)", line):
            return True
        return False

    def _collapse_blank_lines(self, lines: list[str]) -> str:
        output: list[str] = []
        blank = 0
        for line in lines:
            if line.strip():
                blank = 0
                output.append(line)
            else:
                blank += 1
                if blank <= 1:
                    output.append("")
        return "\n".join(output)
