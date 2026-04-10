#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple


def parse_diff_hunks(diff_text: str) -> List[Dict[str, str | List[str]]]:
    lines = diff_text.splitlines()
    hunks: List[Dict[str, str | List[str]]] = []

    current_old = ""
    current_new = ""
    current_hunk_header = ""
    current_hunk_lines: List[str] = []

    for line in lines:
        if line.startswith("--- "):
            if current_hunk_header:
                hunks.append(
                    {
                        "old": current_old,
                        "new": current_new,
                        "header": current_hunk_header,
                        "lines": current_hunk_lines,
                    }
                )
                current_hunk_header = ""
                current_hunk_lines = []
            current_old = line
            continue

        if line.startswith("+++ "):
            current_new = line
            continue

        if line.startswith("@@"):
            if current_hunk_header:
                hunks.append(
                    {
                        "old": current_old,
                        "new": current_new,
                        "header": current_hunk_header,
                        "lines": current_hunk_lines,
                    }
                )
            current_hunk_header = line
            current_hunk_lines = []
            continue

        if current_hunk_header:
            current_hunk_lines.append(line)

    if current_hunk_header:
        hunks.append(
            {
                "old": current_old,
                "new": current_new,
                "header": current_hunk_header,
                "lines": current_hunk_lines,
            }
        )

    return hunks


def escape_caption(text: str) -> str:
    return text.replace("_", r"\_")


def remove_inline_comment(code: str) -> Tuple[str, bool]:
    out: List[str] = []
    in_single = False
    in_double = False
    escaped = False
    i = 0
    removed = False

    while i < len(code):
        ch = code[i]
        nxt = code[i + 1] if i + 1 < len(code) else ""

        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue

        if ch == "\\" and (in_single or in_double):
            out.append(ch)
            escaped = True
            i += 1
            continue

        if not in_single and not in_double:
            if ch == "/" and nxt == "/":
                removed = True
                break
            if ch == "/" and nxt == "*":
                removed = True
                end = code.find("*/", i + 2)
                if end == -1:
                    break
                i = end + 2
                continue

        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double

        out.append(ch)
        i += 1

    return "".join(out).rstrip(), removed


def is_comment_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if re.fullmatch(r"[/*\-_=*]{8,}", stripped):
        return True
    if stripped.startswith("/*") and re.search(r"\*{6,}", stripped):
        return True
    if stripped.startswith("*") and len(stripped) >= 20:
        return True
    return (
        stripped.startswith("//")
        or stripped.startswith("/*")
        or stripped.startswith("*")
        or bool(re.fullmatch(r"[*=\-]{6,}", stripped))
    )


def truncate_code(code: str, max_body_width: int) -> str:
    extra_margin = 3
    if max_body_width <= 3:
        return code
    if len(code) <= max_body_width:
        return code
    keep = max_body_width - 3 - extra_margin
    if keep < 0:
        keep = 0
    return code[:keep].rstrip() + "..."


def format_meta_line(line: str, max_width: int) -> str:
    line = line.rstrip().replace("\t", "    ")

    if line.startswith("--- ") or line.startswith("+++ "):
        marker = line[:3]
        rest = line[4:].strip()

        if rest.startswith('"'):
            end_quote = rest.find('"', 1)
            path_part = rest[1:end_quote] if end_quote != -1 else rest[1:]
        else:
            path_part = rest.split()[0] if rest else ""

        path_part = path_part.strip()
        if len(path_part) >= 2 and path_part[0] == '"' and path_part[-1] == '"':
            path_part = path_part[1:-1]

        if not path_part:
            compact = f"{marker}"
        else:
            budget = max_width - len(marker) - 1

            normalized = path_part.replace("\\", "/")
            has_dot_prefix = normalized.startswith("./")
            body = normalized[2:] if has_dot_prefix else normalized
            segments = [seg for seg in body.split("/") if seg]

            def build_candidate(parts: List[str]) -> str:
                if not parts:
                    return "./" if has_dot_prefix else ""
                joined = "/".join(parts)
                return f"./{joined}" if has_dot_prefix else joined

            if budget > 0:
                candidate = build_candidate(segments)
                while len(candidate) > budget and len(segments) > 1:
                    segments.pop(0)
                    candidate = build_candidate(segments)

                if len(candidate) > budget and budget > 0:
                    candidate = candidate[-budget:]

                path_part = candidate

            compact = f"{marker} {path_part}".rstrip()

        return compact if len(compact) <= max_width else truncate_code(compact, max_width)

    if len(line) <= max_width:
        return line
    return truncate_code(line, max_width)


def select_nearby_lines(lines: List[str], context_lines: int) -> List[str]:
    modified_idx = [i for i, line in enumerate(lines) if line and line[0] in "+-"]
    if not modified_idx:
        return []

    ranges: List[Tuple[int, int]] = []
    for idx in modified_idx:
        start = max(0, idx - context_lines)
        end = min(len(lines) - 1, idx + context_lines)
        ranges.append((start, end))

    merged: List[Tuple[int, int]] = []
    for start, end in sorted(ranges):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))

    out: List[str] = []
    for start, end in merged:
        out.extend(lines[start : end + 1])
    return out


def remap_indent_levels(lines: List[str]) -> List[str]:
    indents: List[int] = []

    for line in lines:
        if not line or line[0] not in " +-":
            continue
        body = line[1:].expandtabs(4)
        if not body.strip():
            continue
        leading = len(body) - len(body.lstrip(" "))
        indents.append(leading)

    if not indents:
        return lines

    min_indent = min(indents)
    normalized_levels = sorted({indent - min_indent for indent in indents})
    level_rank = {level: rank for rank, level in enumerate(normalized_levels)}

    normalized: List[str] = []
    for line in lines:
        if not line or line[0] not in " +-":
            normalized.append(line)
            continue

        prefix = line[0]
        body = line[1:].expandtabs(4)
        if not body.strip():
            normalized.append(prefix)
            continue

        leading = len(body) - len(body.lstrip(" "))
        relative_level = leading - min_indent
        mapped_level = level_rank.get(relative_level, 0)
        normalized.append(prefix + ("\t" * mapped_level) + body.lstrip(" "))

    return normalized


def format_diff_line(
    line: str,
    max_width: int,
    long_comment_len: int,
) -> str | None:
    if not line or line[0] not in " +-":
        return None

    prefix = line[0]
    body = line[1:].rstrip()

    if prefix == " " and not body.strip():
        return None

    current_len = len((prefix + body).expandtabs(4))
    if current_len > max_width:
        if prefix in "+-":
            stripped, removed = remove_inline_comment(body)
            if removed:
                body = stripped
        else:
            stripped, _ = remove_inline_comment(body)
            body = stripped
            if len((prefix + body).expandtabs(4)) > max_width:
                body = truncate_code(body, max_width - 1)

    if len((prefix + body).expandtabs(4)) > long_comment_len and is_comment_only(body):
        return None

    if prefix == " " and not body.strip():
        return None

    return prefix + body


def hunk_caption(old_line: str, hunk_header: str) -> str:
    src_path = old_line[4:].strip() if old_line.startswith("--- ") else "diff"
    name = Path(src_path).name
    m = re.match(r"@@\s*-(\d+)(?:,\d+)?\s*\+(\d+)(?:,\d+)?\s*@@", hunk_header)
    if not m:
        return f"{name} --- {hunk_header}"
    return f"{name} --- hunk -{m.group(1)} +{m.group(2)}"


def build_latex_blocks_by_hunk(
    hunks: List[Dict[str, str | List[str]]],
    style: str,
    max_files: int,
    max_width: int,
    context_lines: int,
    long_comment_len: int,
) -> str:
    out: List[str] = []

    for index, hunk in enumerate(hunks, start=1):
        if max_files > 0 and index > max_files:
            break

        old_line = str(hunk["old"])
        new_line = str(hunk["new"])
        header = str(hunk["header"])
        lines = hunk["lines"]
        assert isinstance(lines, list)

        body_lines = [line for line in lines if not line.startswith("\\ No newline at end of file")]
        compact_lines = select_nearby_lines(body_lines, context_lines=context_lines)
        compact_lines = remap_indent_levels(compact_lines)
        if not compact_lines:
            continue

        formatted: List[str] = []
        for line in compact_lines:
            processed = format_diff_line(
                line,
                max_width=max_width,
                long_comment_len=long_comment_len,
            )
            if processed is not None:
                formatted.append(processed)

        if not formatted:
            continue

        if not any(line[0] in "+-" for line in formatted):
            continue

        caption = escape_caption(hunk_caption(old_line, header))
        out.append(f"\\begin{{lstlisting}}[style={style},caption={{{caption}}}]")
        out.append(format_meta_line(old_line, max_width=max_width))
        out.append(format_meta_line(new_line, max_width=max_width))
        out.append(format_meta_line(header, max_width=max_width))
        out.extend(formatted)
        out.append(r"\end{lstlisting}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def build_standalone_latex(listings_body: str, style_name: str, title: str) -> str:
    escaped_title = title.replace("_", r"\_")
    return (
        "\\documentclass[12pt,a4paper]{article}\n"
        "\\usepackage[UTF8]{ctex}\n"
        "\\usepackage[margin=2.5cm]{geometry}\n"
        "\\usepackage{listings}\n"
        "\\usepackage{xcolor}\n\n"
        "\\definecolor{codebg}{RGB}{248,248,248}\n"
        "\\definecolor{codeframe}{RGB}{210,210,210}\n"
        "\\lstdefinelanguage{diff}{\n"
        "    morecomment=[f][\\color{blue!70!black}\\bfseries]{@@},\n"
        "    morecomment=[f][\\color{red!75!black}]{-},\n"
        "    morecomment=[f][\\color{green!45!black}]{+}\n"
        "}\n"
        f"\\lstdefinestyle{{{style_name}}}{{\n"
        "    language=diff,\n"
        "    backgroundcolor=\\color{codebg},\n"
        "    frame=single,\n"
        "    rulecolor=\\color{codeframe},\n"
        "    basicstyle=\\ttfamily\\footnotesize,\n"
        "    numbers=left,\n"
        "    numberstyle=\\tiny\\color{gray},\n"
        "    numbersep=8pt,\n"
        "    tabsize=4,\n"
        "    breaklines=true,\n"
        "    showstringspaces=false,\n"
        "    captionpos=b\n"
        "}\n\n"
        "\\begin{document}\n"
        f"\\section*{{{escaped_title}}}\n\n"
        f"{listings_body}"
        "\\end{document}\n"
    )


def load_diff_text(diff_file: str | None, left: str | None, right: str | None) -> str:
    if diff_file:
        diff_path = Path(diff_file)
        if not diff_path.exists():
            raise FileNotFoundError(f"未找到 diff 文件: {diff_path}")
        return diff_path.read_text(encoding="utf-8", errors="replace")

    if left and right:
        try:
            result = subprocess.run(
                ["diff", "-rub", left, right],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("未找到 diff 命令，请先安装并确保可在 PATH 中使用") from exc

        if result.returncode not in (0, 1):
            err = result.stderr.strip() or "未知错误"
            raise RuntimeError(f"执行 diff 失败（退出码 {result.returncode}）：{err}")
        return result.stdout

    raise ValueError("请提供 --diff，或同时提供位置参数 left 和 right")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="读取 diff 结果并生成 LaTeX lstlisting 代码块。",
    )
    parser.add_argument(
        "left",
        nargs="?",
        help="要比较的左侧文件/目录路径（位置参数）",
    )
    parser.add_argument(
        "right",
        nargs="?",
        help="要比较的右侧文件/目录路径（位置参数）",
    )
    parser.add_argument(
        "--diff",
        help="diff 输出文件路径（例如 diff.txt）",
    )
    parser.add_argument(
        "--output",
        default="output.tex",
        help="生成的 LaTeX 文件路径（例如 diff_listings.tex）",
    )
    parser.add_argument(
        "--style",
        default="diffstyle",
        help="lstlisting 使用的 style 名称，默认 diffstyle",
    )
    parser.add_argument(
        "--title",
        default="Diff Listings",
        help="生成文档的标题（section 标题）",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="最多处理多少个文件（0 表示全部）",
    )
    parser.add_argument(
        "--max-line-len",
        type=int,
        default=75,
        help="LaTeX listing 内容区目标最大行宽（默认 75）",
    )
    parser.add_argument(
        "--context-lines",
        type=int,
        default=2,
        choices=[1, 2],
        help="每处修改保留的上下文行数（1 或 2，默认 2）",
    )
    parser.add_argument(
        "--long-comment-len",
        type=int,
        default=90,
        help="过滤掉长度超过该值的注释行（默认 90）",
    )

    args = parser.parse_args()
    output_path = Path(args.output)

    if args.diff and (args.left or args.right):
        raise ValueError("使用 --diff 时请不要再提供位置参数 left/right")
    if not args.diff and (not args.left or not args.right):
        raise ValueError("请使用：python gen.py <left> <right> --output <file>，或改用 --diff")

    diff_text = load_diff_text(args.diff, args.left, args.right)
    hunks = parse_diff_hunks(diff_text)
    if not hunks:
        raise ValueError("未在 diff 文件中解析到任何 '@@ ... @@' 片段")

    latex_body = build_latex_blocks_by_hunk(
        hunks,
        style=args.style,
        max_files=args.max_files,
        max_width=args.max_line_len,
        context_lines=args.context_lines,
        long_comment_len=args.long_comment_len,
    )
    if not latex_body.strip():
        raise ValueError("过滤后没有可输出内容，请放宽 --max-line-len / --long-comment-len")
    full_latex = build_standalone_latex(latex_body, style_name=args.style, title=args.title)
    print(full_latex, end="")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(full_latex, encoding="utf-8")
    print(f"\n[OK] 已写入: {output_path}")


if __name__ == "__main__":
    main()
