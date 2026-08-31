"""完整论文正文真实性、篇幅与引用闭环质量控制。"""

from __future__ import annotations

import json
import re

from schemas.thesis import FIGURE_BLOCK_PATTERN
from schemas.thesis_material import ReferenceRecord
from services.thesis.content.fulltext_service import count_visible_words

# 实测结论必须同时包含测试语义和可被误认为结果的数值。
_EMPIRICAL_TERMS = re.compile(
    r"并发|响应时间|错误率|吞吐|覆盖率|准确率|性能测试|压力测试|测试结果|实验结果|结果表明|经测试",
    re.IGNORECASE,
)
_NUMERIC_METRIC = re.compile(r"\d+(?:\.\d+)?\s*(?:%|ms|毫秒|秒|分钟|人|用户|次|MB|GB|TPS|QPS)", re.IGNORECASE)
_ENGLISH_EMPIRICAL_TERMS = re.compile(
    r"concurrent|response\s+time|error\s+rate|throughput|coverage|performance\s+test|test\s+results?",
    re.IGNORECASE,
)
# 没有项目材料时，这些措辞会把设计建议伪装成已经完成的事实。
_ASSERTIVE_IMPLEMENTATION = re.compile(r"已实现|已经实现|完成了|经测试|测试表明|结果表明|部署于|本系统采用|系统采用")
# 常见但不能从论文标题自动推断为真实实现的技术细节。
_KNOWN_TECHNOLOGIES = (
    "微信小程序",
    "RESTful API",
    "Vuex",
    "Vue Router",
    "Axios",
    "Element UI",
    "Spring Data JPA",
    "MyBatis",
    "MyBatis-Plus",
    "Spring Security",
    "Redis",
    "Nginx",
    "JMeter",
    "JWT",
    "BCrypt",
    "MySQL",
    "IntelliJ IDEA",
    "Postman",
    "Chrome",
    "Windows 10",
    "JDK1.8",
    "Docker",
    "Kubernetes",
    "React",
    "Angular",
)
_FIGURE_TECHNOLOGY_REPLACEMENTS = {
    "微信小程序": "前端运行载体（待确认）",
    "RESTful API": "接口风格（待确认）",
    "Vuex": "状态管理方案（待确认）",
    "Vue Router": "前端路由方案（待确认）",
    "Axios": "HTTP 客户端方案（待确认）",
    "Spring Data JPA": "数据访问方案（待确认）",
    "MyBatis-Plus": "数据访问方案（待确认）",
    "MyBatis": "数据访问方案（待确认）",
    "Spring Security": "认证授权方案（待确认）",
    "Redis": "缓存方案（待确认）",
    "Nginx": "反向代理方案（待确认）",
    "JMeter": "压力测试工具（待确认）",
    "JWT": "令牌机制（待确认）",
    "BCrypt": "密码哈希方案（待确认）",
    "MySQL": "关系型数据库（待确认）",
}
_CITATION = re.compile(r"\[(\d+)\]")
_CITATION_GROUP = re.compile(r"(?:\[\d+\]){2,}")
_HEADING = re.compile(r"^#{1,3}\s+")
_TOP_LEVEL_HEADING = re.compile(r"^#(?!#)\s+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])")
_CHAPTER_FACT_BOUNDARIES = {
    "系统设计": "【事实边界：本章内容为依据题目和需求生成的设计建议，数据结构、接口与安全方案需结合真实项目材料确认。】",
    "系统实现": "【事实边界：本章内容为建议实现方案；未经用户材料确认的组件、版本、部署环境和完成状态均不作为既成事实。】",
    "系统测试": "【事实边界：本章仅给出建议测试方案和预期结果；在补充真实测试记录前，不代表已经执行测试或达到指标。】",
    "总结与展望": "【事实边界：本章成果总结需结合真实项目材料复核，待确认内容不代表系统已经实现或完成验收。】",
}


def _downgrade_unverified_conclusions(line: str) -> tuple[str, bool]:
    """把没有证据的完成态、测试结论改成方案或验收目标。"""

    replacements = (
        (r"安全测试结果确认系统各项安全机制均有效生效", "待执行安全测试将用于核验各项安全机制是否有效"),
        (r"验证系统在当前测试环境下的性能表现满足设计预期", "用于核验系统性能是否满足设计预期"),
        (r"经测试，各功能均能正确执行预期逻辑", "待执行测试将用于核验各功能是否符合预期逻辑"),
        (r"测试还验证了", "待执行测试还将用于验证"),
        (r"测试结果验证了", "待执行测试将用于验证"),
        (r"测试结果确认(?:了)?", "待执行测试将用于确认"),
        (r"测试结果显示", "待执行测试应记录"),
        (r"测试结果表明", "待执行测试应核验"),
        (r"通过测试验证了", "待执行测试将用于验证"),
        (r"测试验证了", "待执行测试将用于验证"),
        (r"测试结果为", "待执行测试将为"),
        (r"本文对系统进行了功能测试与部分性能验证", "本文规划了功能测试与性能验证方案"),
        (r"测试覆盖了", "测试方案覆盖"),
        (r"验证了系统各项功能", "用于验证系统各项功能"),
        (r"完成了系统的完整开发", "形成了系统的完整设计与实现方案"),
        (r"设计并实现了一套", "提出了一套"),
        (r"尽管系统(?:基本)?(?:完成|实现)了(?:既定|预期)功能", "当前设计方案虽覆盖预期功能"),
        (r"完成了从需求分析到系统测试的全过程工作", "给出了从需求分析到系统测试的全过程设计方案"),
        (r"系统实现了预期功能", "系统设计覆盖了预期功能"),
        (r"编码实现与测试验证", "实现方案与测试规划"),
        (r"构建了前后端分离的\s*Web\s*应用体系", "提出了前后端分离的 Web 应用体系设计"),
        (r"实现基于\s*Spring Boot", "拟实现基于 Spring Boot"),
        (r"并对系统进行功能测试", "并拟对系统进行功能测试"),
    )
    rewritten = line
    changed = False
    for pattern, replacement in replacements:
        rewritten, count = re.subn(pattern, replacement, rewritten, flags=re.IGNORECASE)
        changed = changed or count > 0
    rewritten, count = re.subn(
        r"(?:经测试|测试结果(?:验证|确认|显示|表明)?)[^。！？]*[。！？]?",
        "待执行测试将用于核验上述测试项是否符合预期。",
        rewritten,
        flags=re.IGNORECASE,
    )
    changed = changed or count > 0
    return rewritten, changed


# 判断用户补充要求是否包含可核验的实测数据
def has_user_empirical_evidence(writing_requirements: str) -> bool:
    """判断用户是否提供了可作为论文事实使用的测试数据。

    Args:
        writing_requirements: 用户填写的写作方向或补充材料。

    Returns:
        同时包含测试语义和带单位数值时返回 True。
    """

    return bool(_EMPIRICAL_TERMS.search(writing_requirements) and _NUMERIC_METRIC.search(writing_requirements))


# 归一化技术名称，便于比较用户确认事实和模型输出
def _technology_key(value: str) -> str:
    """生成不区分空白与大小写的技术名称键。

    Args:
        value: 技术名称。

    Returns:
        用于集合比较的归一化键。
    """

    return re.sub(r"[\s._-]+", "", value).casefold()


def extract_confirmed_technologies(user_text: str) -> set[str]:
    """从用户标题和补充要求中提取明确出现的技术名称。"""

    candidates = (*_KNOWN_TECHNOLOGIES, "Spring Boot", "Vue", "Java", "MySQL")
    normalized_text = _technology_key(user_text)
    return {item for item in candidates if _technology_key(item) in normalized_text}


# 保持 Markdown 表格列数并移除其中未经确认的测试数字
def _sanitize_empirical_table_line(line: str) -> str:
    """把表格中的伪实测单元格替换成待补充提示。

    Args:
        line: Markdown 表格行。

    Returns:
        保持原列数的安全表格行。
    """

    cells = line.split("|")
    for index, cell in enumerate(cells):
        if _EMPIRICAL_TERMS.search(cell) or _NUMERIC_METRIC.search(cell):
            cells[index] = " 【待补充真实测试数据】 "
    return "|".join(cells)


# 删除无证据的数据图，避免渲染出看似真实的趋势图
def _remove_unverified_charts(full_text: str, allow_empirical_data: bool) -> tuple[str, bool]:
    """移除没有用户数据支撑的 chart 占位符。

    Args:
        full_text: 模型生成的完整 Markdown 正文。
        allow_empirical_data: 用户是否提供了可核验数据。

    Returns:
        处理后的正文和是否移除了图表。
    """

    if allow_empirical_data:
        return full_text, False
    removed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return match.group(0)
        if isinstance(payload, dict) and payload.get("render_method") == "chart":
            removed = True
            return "【待补充真实测试数据后生成该图】"
        return match.group(0)

    return FIGURE_BLOCK_PATTERN.sub(replace, full_text), removed


def remove_ai_image_figures(full_text: str) -> tuple[str, bool]:
    """移除显式禁用的 AI 生图占位符，保留 Mermaid 与有证据的数据图。"""

    removed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return match.group(0)
        if isinstance(payload, dict) and payload.get("render_method") == "ai_image":
            removed = True
            return ""
        return match.group(0)

    return FIGURE_BLOCK_PATTERN.sub(replace, full_text), removed


# 把未确认的实测结论和技术实现降级为明确建议
def sanitize_generated_claims(
    full_text: str,
    *,
    writing_requirements: str,
    confirmed_technologies: set[str],
) -> tuple[str, list[str]]:
    """清理模型生成正文中的未确认事实。

    Args:
        full_text: 模型生成的 Markdown 正文。
        writing_requirements: 用户补充要求，用于判断是否提供实测证据。
        confirmed_technologies: 用户标题或补充要求中明确出现的技术栈。

    Returns:
        清理后的正文和被降级为建议的字段类型。
    """

    allow_empirical_data = has_user_empirical_evidence(writing_requirements)
    sanitized, removed_chart = _remove_unverified_charts(full_text, allow_empirical_data)
    suggestion_fields: set[str] = {"chart_data"} if removed_chart else set()
    protected_figures: list[str] = []
    confirmed_keys = {_technology_key(item) for item in confirmed_technologies}

    def protect_figure(match: re.Match[str]) -> str:
        figure = match.group(0)
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):

            def sanitize_value(value: object) -> object:
                if isinstance(value, str):
                    result = value
                    for technology, replacement in _FIGURE_TECHNOLOGY_REPLACEMENTS.items():
                        if _technology_key(technology) in confirmed_keys:
                            continue
                        result, count = re.subn(re.escape(technology), replacement, result, flags=re.IGNORECASE)
                        if count:
                            suggestion_fields.add("unconfirmed_technology")
                    return result
                if isinstance(value, list):
                    return [sanitize_value(item) for item in value]
                if isinstance(value, dict):
                    return {key: sanitize_value(item) for key, item in value.items()}
                return value

            safe_payload = sanitize_value(payload)
            figure = f"<<FIGURE>>\n{json.dumps(safe_payload, ensure_ascii=False, separators=(',', ':'))}\n<</FIGURE>>"
        token = f"@@THESIS_FIGURE_BLOCK_{len(protected_figures)}@@"
        protected_figures.append(figure)
        return token

    # Mermaid/AI 图片使用结构化 JSON 协议。正文真实性改写只能处理自然语言，
    # 否则“系统测试”等图题会被加上建议前缀并破坏 render_method 字段。
    sanitized = FIGURE_BLOCK_PATTERN.sub(protect_figure, sanitized)
    vue_confirmed = "vue" in confirmed_keys
    lines: list[str] = []
    current_chapter = ""
    current_heading = ""
    test_result_columns: set[int] = set()
    for line in sanitized.splitlines():
        stripped = line.strip()
        if _TOP_LEVEL_HEADING.match(stripped):
            current_chapter = stripped
            test_result_columns.clear()
        if _HEADING.match(stripped):
            current_heading = stripped
        if stripped in {"```", "```json", "```mermaid"}:
            continue
        if _HEADING.match(stripped):
            lines.append(line)
            if _TOP_LEVEL_HEADING.match(stripped):
                for chapter_name, boundary in _CHAPTER_FACT_BOUNDARIES.items():
                    if chapter_name in stripped:
                        lines.append(boundary)
                        suggestion_fields.add("fact_boundary")
                        break
            continue
        if not stripped or stripped.startswith("@@THESIS_FIGURE_BLOCK_"):
            if not stripped:
                test_result_columns.clear()
            lines.append(line)
            continue
        if not allow_empirical_data:
            line, conclusion_changed = _downgrade_unverified_conclusions(line)
            stripped = line.strip()
            if conclusion_changed:
                suggestion_fields.add("test_execution")
        if not allow_empirical_data and _EMPIRICAL_TERMS.search(stripped) and _NUMERIC_METRIC.search(stripped):
            suggestion_fields.add("empirical_metrics")
            if stripped.startswith("|"):
                lines.append(_sanitize_empirical_table_line(line))
            else:
                lines.append("【待补充真实测试数据：用户未提供可核验测试记录，本段不得作为实测结论。】")
            continue
        if not allow_empirical_data and "系统测试" in current_chapter and stripped.startswith("|"):
            cells = line.split("|")
            header_columns = {
                index
                for index, cell in enumerate(cells)
                if re.search(r"测试用例数|通过数|失败数|通过率|实际结果|执行记录|实测结果", cell)
            }
            if header_columns:
                test_result_columns = header_columns
                lines.append(line.replace("实际结果", "执行记录"))
                suggestion_fields.add("test_execution")
                continue
            if test_result_columns and not all(
                not cell.strip() or re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells
            ):
                for index in test_result_columns:
                    if index < len(cells) and cells[index].strip():
                        cells[index] = " 【待补充真实测试数据】 "
                lines.append("|".join(cells))
                suggestion_fields.update({"empirical_metrics", "test_execution"})
                continue
            rewritten = line.replace("实际结果", "执行记录")
            rewritten, count = re.subn(
                r"\|\s*(?:与预期一致|符合预期|一致|通过|成功)\s*(?=\|)",
                "| 【待执行】 ",
                rewritten,
            )
            if rewritten != line or count:
                suggestion_fields.add("test_execution")
            lines.append(rewritten)
            continue
        if not allow_empirical_data and re.search(r"MD5\s*加盐", stripped, re.IGNORECASE):
            line = re.sub(
                r"MD5\s*加盐(?:方式)?",
                "现代自适应密码哈希算法（如 BCrypt 或 Argon2，具体方案待确认）",
                line,
                flags=re.IGNORECASE,
            )
            stripped = line.strip()
            suggestion_fields.add("unconfirmed_technology")
        if vue_confirmed and "微信小程序" in stripped and "微信小程序" not in confirmed_keys:
            suggestion_fields.add("unconfirmed_technology")
            lines.append("建议实现方案（待确认）：前端遵循已确认的 Vue 技术路线，具体运行载体需结合实际项目材料确认。")
            continue
        unconfirmed = [
            technology
            for technology in _KNOWN_TECHNOLOGIES
            if _technology_key(technology) in _technology_key(stripped)
            and _technology_key(technology) not in confirmed_keys
        ]
        if unconfirmed and not re.search(r"建议|待确认|拟采用|可采用|可选", stripped):
            suggestion_fields.add("unconfirmed_technology")
            lines.append(f"建议实现方案（待确认）：{stripped}")
            continue
        if "系统实现" in current_chapter and not re.search(r"建议|待确认|拟采用|可采用|设计说明", stripped):
            suggestion_fields.add("implementation_facts")
            lines.append(f"实现方案建议（待项目材料确认）：{stripped}")
            continue
        if "研究内容" in current_heading and re.search(r"实现|测试|验证", stripped) and not re.search(
            r"建议|待确认|拟采用|可采用|设计说明",
            stripped,
        ):
            suggestion_fields.add("implementation_facts")
            lines.append(f"研究方案（待项目材料确认）：{stripped}")
            continue
        if "系统测试" in current_chapter and not stripped.startswith("|") and not re.search(
            r"建议|待确认|待执行|拟采用|可采用|设计说明",
            stripped,
        ):
            suggestion_fields.add("test_execution")
            lines.append(f"建议测试方案（待执行）：{stripped}")
            continue
        if "总结与展望" in current_chapter and re.search(r"完成|实现|验证|测试结果", stripped) and not re.search(
            r"建议|待确认|拟采用|可采用|设计说明|总结说明",
            stripped,
        ):
            suggestion_fields.add("implementation_facts")
            lines.append(f"总结说明（待项目材料确认）：{stripped}")
            continue
        if "/api/" in stripped and not re.search(r"建议|待确认|拟定|可采用", stripped):
            suggestion_fields.add("interface_details")
            lines.append(f"接口设计建议（待确认）：{stripped}")
            continue
        if _ASSERTIVE_IMPLEMENTATION.search(stripped) and not re.search(r"建议|待确认|拟采用|可采用", stripped):
            suggestion_fields.add("implementation_facts")
            lines.append(f"设计说明（待项目材料确认）：{stripped}")
            continue
        lines.append(line)
    result = "\n".join(lines).strip()
    for index, figure in enumerate(protected_figures):
        result = result.replace(f"@@THESIS_FIGURE_BLOCK_{index}@@", figure)
    return result, sorted(suggestion_fields)


# 按正文统计口径把单行内容裁剪到指定上限
def _trim_line_to_word_limit(line: str, maximum: int) -> str:
    """在尽量保留完整句子的前提下裁剪一行正文。

    Args:
        line: 普通正文行。
        maximum: 本行允许的最大可见字数。

    Returns:
        不超过指定字数的正文行。
    """

    if count_visible_words(line) <= maximum:
        return line
    citations = list(dict.fromkeys(_CITATION.findall(line)))
    citation_suffix = "".join(f"[{value}]" for value in citations)
    content = _CITATION.sub("", line).rstrip()
    content_maximum = max(maximum - count_visible_words(citation_suffix), 1)
    sentences = [item for item in _SENTENCE_BOUNDARY.split(content) if item]
    kept: list[str] = []
    for sentence in sentences:
        candidate = "".join([*kept, sentence])
        if count_visible_words(candidate) > content_maximum:
            break
        kept.append(sentence)
    if kept:
        return "".join(kept).strip() + citation_suffix

    low, high = 1, len(content)
    while low < high:
        middle = (low + high + 1) // 2
        if count_visible_words(content[:middle]) <= content_maximum:
            low = middle
        else:
            high = middle - 1
    return content[:low].rstrip("，,；;：:。. ") + "。" + citation_suffix


# 在保留标题、表格、图和引用句的前提下收敛正文总量
def constrain_fulltext_length(full_text: str, *, target_word_count: int) -> str:
    """把完整论文正文控制在目标字数正负 10% 内。

    Args:
        full_text: 已完成真实性清理的 Markdown 正文。
        target_word_count: 用户要求的正文目标字数。

    Returns:
        保留大纲标题和结构化内容的收敛正文。

    Raises:
        RuntimeError: 模型正文低于最低交付字数，或受保护内容本身已超过上限。
    """

    minimum = round(target_word_count * 0.9)
    maximum = round(target_word_count * 1.1)
    current = count_visible_words(full_text)
    if current < minimum:
        raise RuntimeError(f"正文有效字数{current}低于最低要求{minimum}")
    if current <= maximum:
        return full_text.strip()

    desired = round(target_word_count * 1.03)
    lines = full_text.splitlines()
    candidates = [
        index
        for index, line in enumerate(lines)
        if line.strip()
        and not _HEADING.match(line.strip())
        and not line.strip().startswith("|")
        and "<<FIGURE>>" not in line
        and "<</FIGURE>>" not in line
    ]
    reducible = sum(max(count_visible_words(lines[index]) - 60, 0) for index in candidates)
    required = current - desired
    if reducible < required:
        raise RuntimeError("正文受保护内容过多，无法在不破坏标题、图表和引用的前提下收敛字数")

    remaining = required
    for index in sorted(candidates, key=lambda item: count_visible_words(lines[item]), reverse=True):
        if remaining <= 0:
            break
        line_length = count_visible_words(lines[index])
        removable = max(line_length - 60, 0)
        removed = min(removable, remaining)
        lines[index] = _trim_line_to_word_limit(lines[index], line_length - removed)
        remaining -= max(line_length - count_visible_words(lines[index]), 0)

    constrained = "\n".join(lines).strip()
    final_count = count_visible_words(constrained)
    if not minimum <= final_count <= maximum:
        raise RuntimeError(f"正文有效字数{final_count}不在{minimum}-{maximum}范围内")
    return constrained


def sanitize_abstract_truth(
    abstract_data: dict[str, str],
    *,
    writing_requirements: str,
    confirmed_technologies: set[str] | None = None,
) -> tuple[dict[str, str], bool]:
    """移除摘要中未经用户证据支持的中英文实测数字。"""

    if has_user_empirical_evidence(writing_requirements):
        return abstract_data, False
    sanitized = dict(abstract_data)
    confirmed_keys = {_technology_key(item) for item in (confirmed_technologies or set())}
    changed = False
    for key in ("abstract_zh", "abstract_en"):
        text = sanitized.get(key, "")
        boundary = _SENTENCE_BOUNDARY if key == "abstract_zh" else re.compile(r"(?<=[.!?])\s+")
        sentences = [item for item in boundary.split(text) if item]
        kept: list[str] = []
        for sentence in sentences:
            empirical = _EMPIRICAL_TERMS.search(sentence) or _ENGLISH_EMPIRICAL_TERMS.search(sentence)
            if empirical and (_NUMERIC_METRIC.search(sentence) or re.search(r"结果表明|test results?", sentence, re.I)):
                changed = True
                continue
            rewritten = sentence
            if key == "abstract_zh":
                replacements: list[tuple[str, str]] = [
                    (r"Vuex\s*状态管理", "待确认的状态管理方案"),
                    (r"完成系统的总体设计", "拟完成系统总体设计"),
                    (r"确定采用", "技术方案拟采用"),
                    (r"MySQL\s*数据库", "待确认的关系型数据库"),
                    (r"本文设计并实现了(?:一个|一套)?", "本文围绕"),
                    (r"设计并实现了(?:一个|一套)?", "拟设计"),
                    (r"系统涵盖", "系统功能拟涵盖"),
                    (r"系统后端采用", "后端方案拟采用"),
                    (r"前端采用", "前端方案拟采用"),
                    (r"二者通过", "二者拟通过"),
                    (r"系统完整覆盖了", "系统功能设计拟覆盖"),
                    (r"系统实现了", "系统设计拟实现"),
                    (r"实现了", "拟实现"),
                    (r"形成了", "拟形成"),
                    (r"规划了", "拟规划"),
                    (r"并通过外键关联保障", "并拟通过外键关联保障"),
                    (r"有效降低了", "以降低"),
                    (r"系统测试采用", "测试方案拟采用"),
                    (r"对系统关键功能进行了验证", "规划了系统关键功能验证方案"),
                    (r"对([^。；]+?)进行了验证", r"拟对\1开展验证"),
                    (r"进行了功能验证", "拟开展功能验证"),
                    (r"并明确了", "并提出了"),
                    (r"基于\s*E-R\s*模型构建", "建议基于 E-R 模型设计"),
                    (r"并通过订单状态字段", "并拟通过订单状态字段"),
                    (r"系统实现过程中", "在系统实现方案中"),
                    (r"系统前端采用", "前端设计建议采用"),
                    (r"后端基于", "后端设计建议基于"),
                    (r"数据库选用", "数据库设计建议选用"),
                    (r"在系统实现阶段", "在系统实现方案中"),
                    (r"前端实现了", "前端拟实现"),
                    (r"后端实现了", "后端拟实现"),
                    (r"完成了", "讨论了"),
                    (r"开展了", "规划了"),
                    (r"能够满足", "预期可满足"),
                    (r"系统实现部分阐述了", "系统实现部分给出了建议"),
                    (r"在系统实现方案中，前端采用", "在系统实现方案中，前端建议采用"),
                    (r"后端通过", "后端拟通过"),
                    (r"并集成", "并拟集成"),
                    (r"后端分层实现", "后端拟分层实现"),
                    (r"系统对用户密码采用", "安全设计建议对用户密码采用"),
                    (r"同时设计", "同时拟设计"),
                    (r"测试环节采用", "测试方案拟采用"),
                    (r"并验证了", "，用于验证"),
                    (r"本文工作表明，该平台通过", "从设计目标看，该平台拟通过"),
                    (r"有效改善了", "改善"),
                    (r"提升了", "提升"),
                    (r"符合绿色校园和可持续发展的理念，具有重要的应用价值", "以绿色校园和可持续发展为目标，具备潜在应用价值"),
                ]
            else:
                replacements = [
                    (r"Vuex(?:-based)?\s+state management", "a state-management option to be confirmed"),
                    (r"MySQL\s+database", "a relational database solution to be confirmed"),
                    (r"this paper designs and implements", "this paper studies the proposed design of"),
                    (
                        r"conducting research following the process of requirements analysis, system design, "
                        r"system implementation, and system testing",
                        "organizing the proposed research around requirements analysis, system design, "
                        "implementation planning, and test planning",
                    ),
                    (r"completes the overall system design", "proposes the overall system design"),
                    (r"and adopts Spring Boot", "and proposes Spring Boot"),
                    (r"the system functions are divided", "the proposed system functions are divided"),
                    (r"the database design adopts", "the database design proposes"),
                    (r"the front-end adopts", "the proposed front-end may adopt"),
                    (r"the back-end is based on", "the proposed back-end may be based on"),
                    (r"the back-end is built on", "the proposed back-end may be built on"),
                    (r"the front-end is constructed using", "the proposed front-end may use"),
                    (r"the system adopts", "the proposed system may adopt"),
                    (r"the system back-end adopts", "the back-end design is proposed to use"),
                    (r"the front-end uses", "the front-end design is proposed to use"),
                    (r"the two sides interact", "the two sides are planned to interact"),
                    (r"the system fully covers", "the functional design is planned to cover"),
                    (r"the system implements mechanisms", "the security design proposes mechanisms"),
                    (r"effectively reducing", "to reduce"),
                    (r"forming a closed loop", "to form a closed loop"),
                    (r"achieving decoupling", "to support decoupling"),
                    (r"the system encompasses", "the proposed system is planned to encompass"),
                    (r"(?:three|four|five) core data tables? (?:are|is) constructed", "the core data tables are proposed"),
                    (r"during system implementation", "in the proposed implementation"),
                    (r"the system design adopts", "the proposed system design may adopt"),
                    (r"the front[ -]end (?:is )?built on", "the proposed front-end design may use"),
                    (r"the back[ -]end (?:is )?based on", "the proposed back-end design may be based on"),
                    (r"were identified", "are proposed"),
                    (r"were defined", "are proposed"),
                    (r"were completed", "are discussed as design options"),
                    (r"implemented", "is proposed to implement"),
                    (r"were conducted", "are proposed"),
                    (r"the system employs", "the security design is proposed to use"),
                    (r"implements encryption", "proposes encryption"),
                    (r"designs order status", "proposes order-status"),
                    (r"the testing phase adopts", "the proposed testing phase may adopt"),
                    (r"and verifies", "to verify"),
                    (r"can meet", "is expected to meet"),
                ]
            for pattern, replacement in replacements:
                rewritten, count = re.subn(pattern, replacement, rewritten, flags=re.IGNORECASE)
                changed = changed or count > 0
            technology_replacements = {
                "zh": {
                    "MySQL": "待确认的关系型数据库",
                    "Spring Data JPA": "待确认的数据访问方案",
                    "Vuex": "待确认的状态管理方案",
                    "Vue Router": "待确认的前端路由方案",
                    "Axios": "待确认的 HTTP 客户端方案",
                    "MyBatis": "待确认的数据访问方案",
                    "Spring Security": "待确认的认证授权方案",
                    "Redis": "待确认的缓存方案",
                    "Nginx": "待确认的反向代理方案",
                    "JMeter": "待确认的压力测试工具",
                    "JWT": "待确认的令牌机制",
                    "BCrypt": "待确认的密码哈希方案",
                    "IntelliJ IDEA": "待确认的开发工具",
                    "Postman": "待确认的接口调试工具",
                    "Chrome": "待确认的测试浏览器",
                },
                "en": {
                    "MySQL": "a relational database to be confirmed",
                    "Spring Data JPA": "a data-access option to be confirmed",
                    "Vuex": "a state-management option to be confirmed",
                    "Vue Router": "a front-end routing option to be confirmed",
                    "Axios": "an HTTP client option to be confirmed",
                    "MyBatis": "a data-access option to be confirmed",
                    "Spring Security": "an authentication option to be confirmed",
                    "Redis": "a cache option to be confirmed",
                    "Nginx": "a reverse-proxy option to be confirmed",
                    "JMeter": "a load-testing tool to be confirmed",
                    "JWT": "a token mechanism to be confirmed",
                    "BCrypt": "a password-hashing option to be confirmed",
                    "IntelliJ IDEA": "a development tool to be confirmed",
                    "Postman": "an API debugging tool to be confirmed",
                    "Chrome": "a test browser to be confirmed",
                },
            }
            language_key = "zh" if key == "abstract_zh" else "en"
            for technology, replacement in technology_replacements[language_key].items():
                if _technology_key(technology) in confirmed_keys:
                    continue
                rewritten, count = re.subn(re.escape(technology), replacement, rewritten, flags=re.IGNORECASE)
                changed = changed or count > 0
            if key == "abstract_en":
                rewritten = re.sub(
                    r"with the proposed front-end design may use",
                    "with the front end planned around",
                    rewritten,
                    flags=re.IGNORECASE,
                )
                rewritten = re.sub(
                    r"the proposed back-end design may be based on (.+?) providing",
                    r"the back end planned around \1 to provide",
                    rewritten,
                    flags=re.IGNORECASE,
                )
                rewritten = re.sub(
                    r"a relational database to be confirmed database",
                    "a relational database solution to be confirmed",
                    rewritten,
                    flags=re.IGNORECASE,
                )
                rewritten = re.sub(
                    r"\bthe\s+an\s+HTTP client option to be confirmed\b",
                    "an HTTP client option to be confirmed",
                    rewritten,
                    flags=re.IGNORECASE,
                )
                rewritten = re.sub(
                    r"the feasibility of (.+?) was demonstrated",
                    r"the feasibility of \1 is discussed",
                    rewritten,
                    flags=re.IGNORECASE,
                )
                rewritten = re.sub(r"\bis is proposed\b", "is proposed", rewritten, flags=re.IGNORECASE)
                rewritten = re.sub(r"(?<=[.!?])(?=[A-Za-z])", " ", rewritten)
                rewritten = re.sub(r"\bVue\.\s+Js\b", "Vue.js", rewritten, flags=re.IGNORECASE)
                rewritten = rewritten[:1].upper() + rewritten[1:]
                rewritten = re.sub(
                    r"(?<=[.!?]\s)([a-z])",
                    lambda match: match.group(1).upper(),
                    rewritten,
                )
            kept.append(rewritten)
        separator = " " if key == "abstract_en" else ""
        sanitized[key] = separator.join(kept).strip()
        if key == "abstract_en":
            sanitized[key] = re.sub(r"\bVue\.\s+Js\b", "Vue.js", sanitized[key], flags=re.IGNORECASE)
            disclaimer = (
                "Note: Because no source code, implementation records, or test data were provided, "
                "the functional, database, security, and testing descriptions above are design proposals "
                "subject to confirmation, not implementation or measured results."
            )
            if disclaimer not in sanitized[key]:
                sanitized[key] = f"{sanitized[key]} {disclaimer}".strip()
                changed = True
        else:
            disclaimer = (
                "说明：用户未提供系统源码、实现记录或测试数据，以上功能、数据库、安全与测试内容均为设计建议，"
                "需据真实项目材料补充确认，不作为已实现或实测结论。"
            )
            if disclaimer not in sanitized[key]:
                sanitized[key] = f"{sanitized[key]}{disclaimer}".strip()
                changed = True
    return sanitized, changed


def normalize_chapter_count_statement(full_text: str) -> str:
    """按实际一级标题重写章节总数和组织结构枚举。"""

    chapter_titles: list[str] = []
    for line in full_text.splitlines():
        stripped = line.strip()
        if not _TOP_LEVEL_HEADING.match(stripped):
            continue
        title = _TOP_LEVEL_HEADING.sub("", stripped)
        chapter_titles.append(re.sub(r"^\d+(?:\.\d+)*\s*", "", title).strip())
    chapter_count = len(chapter_titles)
    numerals = "零一二三四五六七八九十"
    if not 1 <= chapter_count < len(numerals):
        return full_text
    organization = "本文共分为" + numerals[chapter_count] + "章。" + "；".join(
        f"第{numerals[index]}章为{title}" for index, title in enumerate(chapter_titles, start=1)
    ) + "。"
    statement = re.compile(
        r"^(?=.*(?:本文|论文|全文)(?:共)?分(?:为)?[一二三四五六七八九十\d]+章).+$",
        re.MULTILINE,
    )
    return statement.sub(organization, full_text)


# 将引用支持性表述降级为题名和来源可直接核验的范围
def _normalize_supported_citation_claims(full_text: str, references: list[ReferenceRecord]) -> str:
    """清理无法由文献题名和元数据直接支持的确定性结论。

    Args:
        full_text: 带引用的 Markdown 正文。
        references: 最终筛选后的真实文献。

    Returns:
        仅保留可核验引用语义的正文。
    """

    unsupported_claim = re.compile(
        r"发现|证明|验证|表明|揭示|显示|显著|提升|提高|降低|改善|证实|提出|构建了|实现了|设计了|"
        r"强调|采用|使用|引入|聚焦|关注|指出|认为|提到|探讨|分析|研究了|进行了"
    )
    normalized_lines: list[str] = []
    for line in full_text.splitlines():
        if not _CITATION.search(line) or _HEADING.match(line) or not unsupported_claim.search(line):
            normalized_lines.append(line)
            continue
        sentences = [item for item in _SENTENCE_BOUNDARY.split(line) if item]
        kept: list[str] = []
        for sentence in sentences:
            if _CITATION.search(sentence) and unsupported_claim.search(sentence):
                sentence = _CITATION.sub("", sentence)
            kept.append(sentence)
        normalized_lines.append("".join(kept))
    return "\n".join(normalized_lines)


# 把缺少引用的真实文献作为保守研究线索插入第一章末尾
def _insert_missing_reference_clues(
    full_text: str,
    references: list[ReferenceRecord],
    missing_indexes: list[int],
) -> str:
    """为尚未引用的真实文献补充可由题名直接支持的研究线索。

    Args:
        full_text: 已清理无效编号的正文。
        references: 最终真实文献列表。
        missing_indexes: 尚未在正文出现的旧编号。

    Returns:
        每篇最终文献至少出现一次引用的正文。
    """

    if not missing_indexes:
        return full_text
    by_index = {item.index: item for item in references}
    clue_lines: list[str] = []
    available = [index for index in missing_indexes if index in by_index]
    for start in range(0, len(available), 3):
        group = available[start : start + 3]
        titles = "、".join(f"《{by_index[index].title}》" for index in group)
        citations = "".join(f"[{index}]" for index in group)
        clue_lines.append(f"现有文献题名与来源显示，{titles}可作为本课题的相关研究线索{citations}。")
    clues = "\n".join(clue_lines)
    lines = full_text.splitlines()
    insert_at = next(
        (index for index, line in enumerate(lines[1:], start=1) if re.match(r"^#(?!#)\s+", line.strip())),
        len(lines),
    )
    return "\n".join([*lines[:insert_at], clues, *lines[insert_at:]]).strip()


# 规范引用编号、排序文献并验证正文与文末列表完全闭环
def normalize_citation_integrity(
    full_text: str,
    references: list[ReferenceRecord],
) -> tuple[str, list[ReferenceRecord]]:
    """按引用首次出现顺序重排编号，并保证每篇最终文献均被引用。

    Args:
        full_text: 已完成事实和篇幅处理的正文。
        references: 相关性筛选后的真实文献。

    Returns:
        引用编号稳定的正文和同步重排的文献列表。

    Raises:
        RuntimeError: 最终引用仍存在无效编号或闭环不完整。
    """

    # 模型不负责文末书目；去掉擅自附加的书目区，防止与检索结果形成两份列表。
    full_text = re.sub(
        r"^#{1,6}[ \t]*(?:参考文献|References)[ \t]*\n.*?(?=^#{1,6}[ \t]+|\Z)",
        "", full_text, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    # 兼容模型生成的合并引用；仅展开实际存在的编号，不为范围表达式制造新来源。
    valid_indexes = {item.index for item in references}

    # 将数字范围约束到真实编号集合，避免扩展任意大范围
    def expand_citations(match: re.Match[str]) -> str:
        """将合并编号转换成待统一排序的单编号，丢弃不存在的来源。"""
        selected: set[int] = set()
        for part in re.split(r"[,，、]", match.group(1)):
            bounds = re.split(r"[-–]", part.strip())
            if len(bounds) == 1:
                selected.update({int(bounds[0])} & valid_indexes)
            else:
                low, high = int(bounds[0]), int(bounds[-1])
                selected.update(index for index in valid_indexes if low <= index <= high)
        return "".join(f"[{index}]" for index in sorted(selected))

    full_text = re.sub(r"\[(\d+(?:\s*[-–,，、]\s*\d+)+)\]", expand_citations, full_text)
    if not references:
        return _CITATION.sub("", full_text).strip(), []
    cleaned = _CITATION.sub(
        lambda match: match.group(0) if int(match.group(1)) in valid_indexes else "",
        full_text,
    )
    cleaned = _normalize_supported_citation_claims(cleaned, references)
    cited = [int(value) for value in _CITATION.findall(cleaned)]
    missing = [item.index for item in references if item.index not in cited]
    cleaned = _insert_missing_reference_clues(cleaned, references, missing)

    first_seen: list[int] = []
    for value in _CITATION.findall(cleaned):
        index = int(value)
        if index not in first_seen:
            first_seen.append(index)
    mapping = {old_index: new_index for new_index, old_index in enumerate(first_seen, start=1)}
    normalized_text = _CITATION.sub(lambda match: f"[{mapping[int(match.group(1))]}]", cleaned)

    def sort_group(match: re.Match[str]) -> str:
        indexes = sorted({int(value) for value in _CITATION.findall(match.group(0))})
        return "".join(f"[{index}]" for index in indexes)

    normalized_text = _CITATION_GROUP.sub(sort_group, normalized_text)
    by_index = {item.index: item for item in references}
    normalized_references: list[ReferenceRecord] = []
    for new_index, old_index in enumerate(first_seen, start=1):
        item = by_index[old_index]
        formatted = re.sub(r"^\[\d+\]", f"[{new_index}]", item.formatted, count=1)
        normalized_references.append(item.model_copy(update={"index": new_index, "formatted": formatted}))

    final_citations = {int(value) for value in _CITATION.findall(normalized_text)}
    expected = set(range(1, len(normalized_references) + 1))
    if final_citations != expected:
        raise RuntimeError(f"正文引用闭环不完整：正文{sorted(final_citations)}，文献{sorted(expected)}")
    return normalized_text.strip(), normalized_references


__all__ = [
    "constrain_fulltext_length",
    "extract_confirmed_technologies",
    "has_user_empirical_evidence",
    "normalize_chapter_count_statement",
    "normalize_citation_integrity",
    "sanitize_abstract_truth",
    "sanitize_generated_claims",
]
