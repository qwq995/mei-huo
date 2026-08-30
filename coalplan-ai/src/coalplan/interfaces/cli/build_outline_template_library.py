from __future__ import annotations

import argparse

from coalplan.application.outline_template_library import build_outline_template_library


def main() -> None:
    parser = argparse.ArgumentParser(description="批量提取施组 Markdown 目录模板")
    parser.add_argument("corpus_dir", help="施组 Markdown 样本目录")
    parser.add_argument("--output-dir", default=None, help="目录模板库输出目录")
    args = parser.parse_args()
    result = build_outline_template_library(args.corpus_dir, args.output_dir)
    print(f"已处理 {result['document_count']} 份，失败 {result['failed_count']} 份")
    print(result["library_dir"])


if __name__ == "__main__":
    main()
