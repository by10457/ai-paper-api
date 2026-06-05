"""Mermaid 图片渲染实现。"""

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from services.thesis.image.utils import auto_crop_whitespace_fast

logger = logging.getLogger(__name__)

_FLOWCHART_START_PATTERN = re.compile(r"^(?:graph|flowchart)\s+(?:TD|TB|BT|LR|RL)\b", re.IGNORECASE)


def _mermaid_node_id(prefix: str, index: int) -> str:
    """生成 Mermaid flowchart 安全节点 ID。"""

    return f"{prefix}_{index}"


def _flowchart_label(text: str) -> str:
    """转义 flowchart 节点标签。"""

    return text.replace('"', '\\"')


def _normalize_mermaid_code(mermaid_code: str) -> str:
    """修正当前 Mermaid CLI 不支持的常见图类型。"""

    code = mermaid_code.strip()
    code = re.sub(r"^```(?:mermaid)?\s*", "", code, flags=re.IGNORECASE)
    code = re.sub(r"\s*```$", "", code).strip()
    if code.lower().startswith("usecasediagram"):
        return _convert_usecase_diagram_to_flowchart(code)
    if _FLOWCHART_START_PATTERN.match(code):
        return _normalize_flowchart_code(code)
    return code


def _normalize_flowchart_code(mermaid_code: str) -> str:
    """修正 flowchart 中 LLM 常生成的高风险语法。"""

    lines = _split_flowchart_lines(mermaid_code)
    normalized: list[str] = []
    subgraph_index = 0

    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if index == 0:
            normalized.append(_normalize_flowchart_header(line))
            continue

        line, subgraph_index = _normalize_subgraph_line(line, subgraph_index)
        line = _quote_flowchart_node_labels(line)
        line = _normalize_colon_edge_label(line)
        normalized.append(line)

    return "\n".join(normalized)


def _split_flowchart_lines(mermaid_code: str) -> list[str]:
    """把 LLM 常输出的一行分号 Mermaid 拆成多行。"""

    lines: list[str] = []
    for raw_line in mermaid_code.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ";" not in line:
            lines.append(raw_line.rstrip(";"))
            continue
        parts = [part.strip() for part in line.split(";") if part.strip()]
        if parts:
            lines.extend(parts)
    return lines


def _normalize_flowchart_header(line: str) -> str:
    """统一 flowchart 头部声明。"""

    header = line.strip().rstrip(";")
    return re.sub(r"^graph\b", "flowchart", header, flags=re.IGNORECASE)


def _normalize_subgraph_line(line: str, subgraph_index: int) -> tuple[str, int]:
    """把中文 subgraph 标题改为带安全 ID 的写法。"""

    indent = line[: len(line) - len(line.lstrip())]
    stripped = line.strip().rstrip(";")
    match = re.match(r"^subgraph\s+(.+)$", stripped, flags=re.IGNORECASE)
    if not match:
        return line, subgraph_index

    body = match.group(1).strip()
    if re.match(r"^[A-Za-z][A-Za-z0-9_]*\s*(?:\[|\()", body):
        return line, subgraph_index
    if re.match(r"^[A-Za-z][A-Za-z0-9_]*$", body):
        return line, subgraph_index

    subgraph_index += 1
    label = body.strip('"')
    return f'{indent}subgraph SUBGRAPH_{subgraph_index}["{_flowchart_label(label)}"]', subgraph_index


def _normalize_colon_edge_label(line: str) -> str:
    """把 A --> B : 标签 修正为 A -->|标签| B。"""

    match = re.match(
        r"^(?P<indent>\s*)(?P<source>.+?)\s*(?P<arrow>-->|---|-.->|==>)\s*(?P<target>.+?)\s+:\s+(?P<label>.+)$",
        line.rstrip(";"),
    )
    if not match:
        return line

    source = match.group("source").strip()
    arrow = match.group("arrow")
    target = match.group("target").strip()
    label = _flowchart_label(match.group("label").strip().strip('"'))
    return f'{match.group("indent")}{source} {arrow}|"{label}"| {target}'


def _quote_flowchart_node_labels(line: str) -> str:
    """给 flowchart 节点标签加引号，降低中文标点导致的解析失败。"""

    line = _replace_node_label(line, r"(?P<id>\b[A-Za-z][A-Za-z0-9_]*)\s*\[\[(?P<label>[^\]\n]+?)\]\]", "[[", "]]")
    line = _replace_node_label(line, r"(?P<id>\b[A-Za-z][A-Za-z0-9_]*)\s*\(\((?P<label>[^)\n]+?)\)\)", "((", "))")
    line = _replace_node_label(line, r"(?P<id>\b[A-Za-z][A-Za-z0-9_]*)\s*\[(?P<label>[^\]\n]+?)\]", "[", "]")
    line = _replace_node_label(line, r"(?P<id>\b[A-Za-z][A-Za-z0-9_]*)\s*\{(?P<label>[^}\n]+?)\}", "{", "}")
    line = _replace_node_label(line, r"(?P<id>\b[A-Za-z][A-Za-z0-9_]*)\s*\((?P<label>[^)\n]+?)\)", "(", ")")
    return line


def _replace_node_label(line: str, pattern: str, opening: str, closing: str) -> str:
    """替换单类 Mermaid 节点标签。"""

    def repl(match: re.Match[str]) -> str:
        label = match.group("label").strip()
        if label.startswith('"') and label.endswith('"'):
            return match.group(0)
        return f'{match.group("id")}{opening}"{_flowchart_label(label.strip(chr(34)))}"{closing}'

    return re.sub(pattern, repl, line)


def _convert_usecase_diagram_to_flowchart(mermaid_code: str) -> str:
    """把 usecaseDiagram 转为 mmdc 支持更稳定的 flowchart。"""

    lines = [line.strip() for line in mermaid_code.splitlines() if line.strip()]
    alias_map: dict[str, str] = {}
    output: list[str] = ["flowchart TD"]
    actor_index = 0
    package_index = 0

    for line in lines[1:]:
        if line == "}":
            output.append("end")
            continue

        package_match = re.match(r'package\s+"(.+?)"\s*\{', line)
        if package_match:
            package_index += 1
            package_id = _mermaid_node_id("PKG", package_index)
            output.append(f'    subgraph {package_id}["{_flowchart_label(package_match.group(1))}"]')
            continue

        actor_match = re.match(r"actor\s+(.+?)(?:\s+as\s+([A-Za-z0-9_]+))?$", line)
        if actor_match:
            actor_index += 1
            actor_label = actor_match.group(1).strip().strip('"')
            actor_id = actor_match.group(2) or _mermaid_node_id("ACTOR", actor_index)
            alias_map[actor_label] = actor_id
            alias_map[actor_id] = actor_id
            output.append(f'    {actor_id}["{_flowchart_label(actor_label)}"]')
            continue

        usecase_match = re.match(r'usecase\s+"(.+?)"\s+as\s+([A-Za-z0-9_]+)', line)
        if usecase_match:
            label, alias = usecase_match.groups()
            alias_map[alias] = alias
            output.append(f'    {alias}(["{_flowchart_label(label)}"])')
            continue

        relation_match = re.match(r"(.+?)\s*-->\s*(.+?)(?:\s*:\s*(.+))?$", line)
        if relation_match:
            source, target, label = relation_match.groups()
            source_id = alias_map.get(source.strip().strip('"'), source.strip())
            target_id = alias_map.get(target.strip().strip('"'), target.strip())
            if label:
                output.append(f'    {source_id} -->|"{_flowchart_label(label.strip())}"| {target_id}')
            else:
                output.append(f"    {source_id} --> {target_id}")

    return "\n".join(output)


def _summarize_mermaid_stderr(stderr_text: str) -> str:
    """压缩 Mermaid CLI 错误输出。"""

    return stderr_text.strip().splitlines()[0][:500] if stderr_text.strip() else "未知错误"


async def render_mermaid(mermaid_code: str, output_path: str) -> str:
    """将 Mermaid 代码渲染为 PNG。"""

    if not shutil.which("mmdc"):
        raise RuntimeError("Mermaid CLI 未安装，无法渲染 Mermaid 图，请安装 @mermaid-js/mermaid-cli")

    normalized_code = _normalize_mermaid_code(mermaid_code)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".mmd", delete=False) as temp_file:
        temp_file.write(normalized_code)
        mmd_path = temp_file.name

    puppeteer_config: dict[str, object] = {
        "args": ["--no-sandbox", "--disable-setuid-sandbox"],
    }
    if executable_path := os.getenv("PUPPETEER_EXECUTABLE_PATH"):
        puppeteer_config["executablePath"] = executable_path

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as temp_config:
        json.dump(puppeteer_config, temp_config, ensure_ascii=False)
        pptr_config_path = temp_config.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "mmdc",
            "-i",
            mmd_path,
            "-o",
            output_path,
            "-p",
            pptr_config_path,
            "-b",
            "white",
            "-w",
            "1024",
            "-s",
            "2",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Mermaid 渲染失败 (exit {proc.returncode}): {_summarize_mermaid_stderr(stderr.decode())}"
            )
    finally:
        Path(mmd_path).unlink(missing_ok=True)
        Path(pptr_config_path).unlink(missing_ok=True)

    try:
        auto_crop_whitespace_fast(output_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mermaid 图白边裁剪失败，使用原图: %s", exc)

    return output_path
