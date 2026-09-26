"""完整论文真实性、篇幅、引用与个人信息质量测试。"""

import re
from types import SimpleNamespace
from typing import cast

import pytest

from models.paper import PaperOrder
from schemas.thesis_material import ReferenceRecord
from services.thesis.business.order_service import PaperOrderService
from services.thesis.content.fulltext_service import count_visible_words
from services.thesis.content.quality_service import (
    constrain_fulltext_length,
    normalize_chapter_count_statement,
    normalize_citation_integrity,
    remove_ai_image_figures,
    sanitize_abstract_truth,
    sanitize_generated_claims,
)
from services.thesis.profile_policy import acknowledgment_placeholder, thesis_profile_placeholders


# 订单归一化应识别规范字段和常见下游别名
def test_normalize_generate_input_keeps_full_paper_configuration() -> None:
    """验证目标字数、文献配置和补充要求不会在订单链路中丢失。"""

    order = cast(
        PaperOrder,
        SimpleNamespace(
            title="基于Spring Boot与Vue的校园二手交易平台设计与实现",
            outline_json=[{"chapter": "绪论", "sections": [{"name": "背景", "abstract": "背景"}]}],
            config_form={
                "about_msg": "避免编造真实运营数据。",
                "target_word_count": 5000,
                "chinese_reference_count": 8,
                "english_reference_count": 4,
            },
        ),
    )

    normalized = PaperOrderService.normalize_generate_input(order)

    assert normalized.target_word_count == 5000
    assert normalized.chinese_reference_count == 8
    assert normalized.english_reference_count == 4
    assert normalized.writing_requirements == "避免编造真实运营数据。"


# 无真实测试数据时应把数值结论降级为待确认建议并移除数据图
def test_sanitize_generated_claims_rejects_unverified_metrics_and_chart() -> None:
    """验证未提供证据时不把模型示例数据包装成实测结论。"""

    full_text = """\
# 1 摘要说明
测试结果表明，100并发用户下平均响应时间低于300ms，错误率为0%。
<<FIGURE>>
{"caption":"图 1.1 性能趋势","render_method":"chart","chart_type":"line","categories":["1"],"series":[{"name":"响应时间","data":[256]}]}
<</FIGURE>>
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"spring boot", "vue"},
    )

    assert "测试结果表明" not in sanitized
    assert "错误率为0" not in sanitized
    assert "待补充真实测试数据" in sanitized
    assert '"render_method":"chart"' not in sanitized
    assert "empirical_metrics" in suggestion_fields
    assert "chart_data" in suggestion_fields


# 正文真实性清理不得改写 Mermaid 等结构化图形协议
def test_sanitize_generated_claims_preserves_mermaid_payload() -> None:
    """验证图题含测试词时 Mermaid JSON 仍保持原样并可被后续渲染器解析。"""

    figure = """\
<<FIGURE>>
{"caption":"图 6.1 系统测试流程","render_method":"mermaid","mermaid_code":"flowchart TD; A-->B"}
<</FIGURE>>
"""

    sanitized, _ = sanitize_generated_claims(
        f"# 6 系统测试\n{figure}",
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert figure.strip() in sanitized
    assert '"render_method":"mermaid"' in sanitized
    assert "建议测试方案（待执行）" not in sanitized


def test_sanitize_generated_claims_sanitizes_unconfirmed_figure_technology() -> None:
    """结构图中的未确认技术也必须按 JSON 协议安全改写。"""

    full_text = """\
# 5 系统实现
```mermaid
<<FIGURE>>
{"caption":"架构图","render_method":"mermaid","mermaid_code":"flowchart TD; A[Vuex]-->B[MySQL数据库]"}
<</FIGURE>>
```
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "Vuex" not in sanitized
    assert "MySQL" not in sanitized
    assert "状态管理方案（待确认）" in sanitized
    assert "关系型数据库（待确认）" in sanitized
    assert "```" not in sanitized
    assert "unconfirmed_technology" in suggestion_fields


def test_remove_ai_image_figures_keeps_deterministic_diagrams() -> None:
    """调试禁用 AI 生图时只移除 ai_image，不影响 Mermaid 图。"""

    full_text = """\
<<FIGURE>>
{"caption":"插画","render_method":"ai_image","prompt":"校园平台"}
<</FIGURE>>
<<FIGURE>>
{"caption":"架构图","render_method":"mermaid","mermaid_code":"flowchart TD; A-->B"}
<</FIGURE>>
"""

    sanitized, removed = remove_ai_image_figures(full_text)

    assert removed is True
    assert '"render_method":"ai_image"' not in sanitized
    assert '"render_method":"mermaid"' in sanitized


def test_sanitize_generated_claims_removes_result_claims_without_numbers() -> None:
    """没有实测证据时，纯文字测试结论和总结中的完成态也必须降级。"""

    full_text = """\
# 6 系统测试
测试结果验证了用户模块各功能点的正确性。
测试结果确认了系统能够抵御常见攻击。
经测试，各功能均能正确执行预期逻辑。测试还验证了交易安全机制。
经测试相关功能均可正常运行。测试结果验证系统在常规场景下保持稳定响应。
性能测试从三个维度展开，验证系统在当前测试环境下的性能表现满足设计预期。
安全测试结果确认系统各项安全机制均有效生效。
# 7 总结与展望
本文对系统进行了功能测试与部分性能验证。测试覆盖了主要流程，验证了系统各项功能。
本文完成了系统的完整开发，并构建了前后端分离的 Web 应用体系。
本文设计并实现了一套校园平台。尽管系统完成了既定功能，仍存在不足。
尽管系统基本实现了预期功能，但仍存在不足。
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "测试结果验证" not in sanitized
    assert "测试结果确认" not in sanitized
    assert "本文对系统进行了" not in sanitized
    assert "完成了系统的完整开发" not in sanitized
    assert "构建了前后端分离" not in sanitized
    assert "经测试" not in sanitized
    assert "测试结果验证系统" not in sanitized
    assert "测试还验证了" not in sanitized
    assert "设计并实现了一套" not in sanitized
    assert "系统完成了既定功能" not in sanitized
    assert "系统基本实现了预期功能" not in sanitized
    assert "性能表现满足设计预期" not in sanitized
    assert "安全测试结果确认" not in sanitized
    assert "待执行测试将用于验证" in sanitized
    assert "形成了系统的完整设计与实现方案" in sanitized
    assert "test_execution" in suggestion_fields


def test_sanitize_generated_claims_marks_research_content_as_plan() -> None:
    """研究内容小节不得把缺少项目材料的实现与测试任务写成已完成事实。"""

    full_text = """\
# 1 绪论
## 1.3 研究内容与组织结构
### 1.3.1 研究内容
主要工作包括：基于 Spring Boot 实现后端；基于 Vue 实现前端；对系统进行功能测试与安全验证。
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "研究方案（待项目材料确认）" in sanitized
    assert "implementation_facts" in suggestion_fields


def test_sanitize_generated_claims_marks_conclusion_as_unconfirmed() -> None:
    """总结章节不得把未提供材料的实现与测试写成既成成果。"""

    full_text = """\
# 7 总结与展望
系统实现了预期功能，并通过测试验证了主要流程。
本文完成了系统总体架构设计，实现了商品发布功能。
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "系统实现了预期功能" not in sanitized
    assert "通过测试验证了" not in sanitized
    assert "完成了系统总体架构设计" not in sanitized
    assert "实现了商品发布功能" not in sanitized
    assert "讨论了系统总体架构设计" in sanitized
    assert "设计拟覆盖商品发布功能" in sanitized
    assert "待项目材料确认" in sanitized
    assert "implementation_facts" in suggestion_fields


def test_sanitize_generated_claims_adds_chapter_fact_boundaries() -> None:
    """设计、实现、测试和总结章节应显式声明事实边界。"""

    full_text = """\
# 4 系统设计
## 4.1 数据库设计
| 字段 | 类型 |
| --- | --- |
| id | INT |
# 5 系统实现
## 5.1 前端实现
页面组件说明。
# 6 系统测试
## 6.1 测试方法
黑盒测试说明。
# 7 总结与展望
## 7.1 总结
系统实现了预期功能。
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert sanitized.count("【事实边界：") == 4
    assert "数据结构、接口与安全方案需结合真实项目材料确认" in sanitized
    assert "不代表已经执行测试或达到指标" in sanitized
    assert "fact_boundary" in suggestion_fields


def test_sanitize_generated_claims_keeps_unexecuted_test_table_empty() -> None:
    """未提供测试记录时，测试表不得把预期结果伪装成实际结果。"""

    full_text = """\
# 6 系统测试
| 用例编号 | 测试场景 | 预期结果 | 实际结果 |
| --- | --- | --- | --- |
| UT-001 | 正确信息注册 | 注册成功并跳转登录 | 与预期一致 |
| UT-002 | 密码错误 | 提示密码错误 | 通过 |
| UT-003 | 修改资料 | 页面显示新资料 | 一致 |
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "实际结果" not in sanitized
    assert "与预期一致" not in sanitized
    assert "| 通过 |" not in sanitized
    assert "| 一致 |" not in sanitized
    assert sanitized.count("【待补充真实测试数据】") == 3
    assert "test_execution" in suggestion_fields


def test_sanitize_generated_claims_preserves_table_in_combined_implementation_test_chapter() -> None:
    """实现与测试合并章节的 Markdown 表格协议不得被事实边界前缀破坏。"""

    full_text = """\
# 5 系统实现与测试
## 5.1 核心功能实现与测试方案
表 5.1 核心功能测试用例设计
| 用例编号 | 测试场景 | 预期结果 |
| --- | --- | --- |
| TC-01 | 正确账号登录 | 登录成功并跳转首页 |
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "【事实边界：本章仅给出建议实现方案、测试用例与预期结果" in sanitized
    assert "表 5.1 核心功能测试用例设计" in sanitized
    assert "| 用例编号 | 测试场景 | 预期结果 |" in sanitized
    assert "实现方案建议（待项目材料确认）：|" not in sanitized
    assert "fact_boundary" in suggestion_fields


def test_sanitize_generated_claims_removes_unverified_test_statistics() -> None:
    """测试统计表中的用例数、通过数和通过率必须等待真实记录。"""

    full_text = """\
# 6 系统测试
| 测试模块 | 测试用例数 | 通过数 | 通过率 |
| --- | --- | --- | --- |
| 用户注册登录 | 18 | 18 | 100% |
| 商品发布浏览 | 20 | 19 | 95% |
"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        full_text,
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "100%" not in sanitized
    assert "95%" not in sanitized
    assert "| 18 |" not in sanitized
    assert sanitized.count("【待补充真实测试数据】") == 6
    assert "empirical_metrics" in suggestion_fields


def test_sanitize_generated_claims_replaces_insecure_md5_suggestion() -> None:
    """生成建议不得推荐 MD5 保存用户密码。"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        "# 5 系统实现\n实现方案建议（待确认）：用户密码采用 MD5 加盐方式存储。",
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "MD5" not in sanitized
    assert "BCrypt 或 Argon2" in sanitized
    assert "unconfirmed_technology" in suggestion_fields


# 标题确认 Vue 时不得把微信小程序写成既成实现
def test_sanitize_generated_claims_replaces_conflicting_frontend() -> None:
    """验证与用户确认技术栈冲突的实现描述会被显式改写。"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        "# 5 系统实现\n前端基于微信小程序开发，并已完成页面联调。",
        writing_requirements="侧重前后端分离架构。",
        confirmed_technologies={"spring boot", "vue"},
    )

    assert "微信小程序" not in sanitized
    assert "Vue" in sanitized
    assert "待确认" in sanitized
    assert "unconfirmed_technology" in suggestion_fields


def test_sanitize_generated_claims_marks_unconfirmed_api_style() -> None:
    """题目只确认前后端框架时，不得把 RESTful API 写成既成实现。"""

    sanitized, suggestion_fields = sanitize_generated_claims(
        "# 2 相关技术介绍\n本系统所有核心功能均通过 RESTful API 对外提供。",
        writing_requirements="侧重前后端分离架构。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert "建议实现方案（待确认）" in sanitized
    assert "unconfirmed_technology" in suggestion_fields


def test_sanitize_generated_claims_preserves_code_fence_balance() -> None:
    """代码围栏不能被事实清理移除，否则后续章节会被 Word 构建器当作代码。"""

    original = "# 1 系统实现\n```java\nclass Demo {}\n```\n# 2 系统测试\n测试方案待确认。"

    sanitized, _ = sanitize_generated_claims(
        original,
        writing_requirements="用户确认使用 Java",
        confirmed_technologies={"Java"},
    )

    assert sanitized.count("```") == 2
    assert "```java\nclass Demo {}\n```\n# 2 系统测试" in sanitized


# 超长正文应收敛到目标容差且保留完整标题结构
def test_constrain_fulltext_length_preserves_headings() -> None:
    """验证正文篇幅收敛不会删除用户确认的大纲标题。"""

    full_text = "\n".join(
        (
            "# 1 绪论",
            "## 1.1 研究背景",
            "校园二手交易平台研究内容。" * 80,
            "# 2 系统设计",
            "## 2.1 总体架构",
            "前后端分离架构设计内容。" * 80,
        )
    )

    constrained = constrain_fulltext_length(full_text, target_word_count=500)

    assert 450 <= count_visible_words(constrained) <= 550
    for heading in ("# 1 绪论", "## 1.1 研究背景", "# 2 系统设计", "## 2.1 总体架构"):
        assert heading in constrained


def test_constrain_fulltext_length_allows_small_shortfall_with_quality_warning() -> None:
    """略低于 90% 的完整正文应交付并由任务元数据标记字数告警。"""

    text = "# 1 绪论\n" + "研究内容与方法。" * 56
    actual = count_visible_words(text)
    target = round(actual / 0.884)

    assert 0.85 <= actual / target < 0.9
    assert constrain_fulltext_length(text, target_word_count=target) == text


def test_constrain_fulltext_length_still_rejects_severely_short_body() -> None:
    """正文严重不足时仍应拒绝，避免把残缺论文包装成成功产物。"""

    text = "# 1 绪论\n" + "研究内容与方法。" * 40
    actual = count_visible_words(text)
    target = round(actual / 0.75)

    with pytest.raises(RuntimeError, match="低于最低要求"):
        constrain_fulltext_length(text, target_word_count=target)


# 引用应按首次出现顺序重排并形成正文与文末列表闭环
def test_normalize_citation_integrity_closes_reference_loop() -> None:
    """验证无效引用被移除、乱序引用被稳定编号且每篇文献均被引用。"""

    references = [
        ReferenceRecord(
            index=index,
            title=f"校园二手交易研究{index}",
            authors=["测试作者"],
            year="2025",
            formatted=f"[{index}]测试作者.校园二手交易研究{index}[J].测试期刊,2025(1):1-5.",
            language="zh",
        )
        for index in range(1, 4)
    ]

    full_text, normalized_references = normalize_citation_integrity(
        "# 1 绪论\n相关题名与本课题有关[3][1]，无效编号不应保留[9]。",
        references,
    )

    citations = [int(value) for value in re.findall(r"\[(\d+)\]", full_text)]
    assert citations[:2] == [1, 2]
    assert set(citations) == {1, 2, 3}
    assert "[9]" not in full_text
    assert normalized_references[0].title == "校园二手交易研究3"
    assert [item.index for item in normalized_references] == [1, 2, 3]
    assert all(f"[{index}]" in full_text for index in range(1, 4))


def test_normalize_citation_integrity_attaches_missing_citation_to_existing_title() -> None:
    """正文已提到真实题名时应补引用，不应再插入一段重复的研究线索。"""

    references = [
        ReferenceRecord(
            index=1,
            title="校园二手商品交易平台设计",
            authors=["测试作者"],
            year="2025",
            formatted="[1]测试作者.校园二手商品交易平台设计[J].测试期刊,2025(1):1-5.",
            language="zh",
        )
    ]

    full_text, normalized_references = normalize_citation_integrity(
        "# 1 绪论\n现有文献题名与来源显示，《校园二手商品交易平台设计》可作为研究线索。",
        references,
    )

    assert full_text.count("校园二手商品交易平台设计") == 1
    assert "研究线索。[1]" in full_text
    assert len(normalized_references) == 1


# 零文献时单编号、合并编号及模型擅自添加的书目都必须清理
def test_zero_references_removes_all_citation_forms_and_generated_bibliography() -> None:
    """保留正文数字和后续章节，不把模型编号作为真实来源。"""
    text, records = normalize_citation_integrity(
        "# 1 绪论\n研究方向[1][2,3][1-9][2，4]，目标为25篇。\n# 参考文献\n[1]虚构作者.虚构书目。\n# 2 方法\n方法计划。",
        [],
    )
    assert records == []
    assert "[" not in text
    assert "虚构" not in text
    assert "25篇" in text and "# 2 方法" in text


# 缺失个人信息应转换成醒目的待补充字段
def test_normalize_thesis_profile_marks_missing_fields() -> None:
    """验证论文封面和声明页不会继续输出隐蔽旧占位值。"""

    profile, missing_fields = thesis_profile_placeholders()

    assert set(missing_fields) == {
        "author",
        "advisor",
        "major",
        "school",
        "year_month",
        "student_id",
        "student_class",
        "degree_type",
    }
    assert profile["author"] == "【待补充：作者姓名】"
    assert profile["school"] == "【待补充：学院（系）】"


def test_mark_acknowledgment_as_draft_when_profile_is_missing() -> None:
    """个人信息缺失时，致谢不得伪装成用户真实经历。"""

    acknowledgment = acknowledgment_placeholder()

    assert acknowledgment.startswith("【待补充：致谢内容需依据本人真实经历填写")
    assert "感谢导师和同学" not in acknowledgment


def test_sanitize_abstract_truth_uses_research_disclaimer_for_experiment_paper() -> None:
    """非软件项目论文不得附加源码、数据库和安全等无关免责声明。"""

    sanitized, changed = sanitize_abstract_truth(
        {
            "abstract_zh": "本文提出图像分类模型及实验方案。",
            "abstract_en": "This paper proposes an image-classification model and experiment plan.",
        },
        writing_requirements="未提供训练数据、实验环境和测试结果，不得编造准确率。",
        confirmed_technologies={"CNN", "Vision Transformer"},
    )

    assert changed is True
    assert "原始数据、实验记录或结果材料" in sanitized["abstract_zh"]
    assert "系统源码" not in sanitized["abstract_zh"]
    assert "original data, experiment records, or result materials" in sanitized["abstract_en"]
    assert "source code" not in sanitized["abstract_en"]


def test_sanitize_abstract_truth_downgrades_unconfirmed_results() -> None:
    """摘要不得把设计建议和未执行测试改写为既成成果。"""

    sanitized, changed = sanitize_abstract_truth(
        {
            "abstract_zh": "本文设计并实现了一套平台。测试结果表明系统运行正常。",
            "abstract_en": "This paper designs and implements a platform. The test results indicate normal operation.",
        },
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert changed is True
    assert "设计并实现" not in sanitized["abstract_zh"]
    assert "测试结果" not in sanitized["abstract_zh"]
    assert "designs and implements" not in sanitized["abstract_en"].lower()
    assert "test results" not in sanitized["abstract_en"].lower()


def test_sanitize_abstract_truth_marks_proposals_and_normalizes_english_spacing() -> None:
    """摘要中的实现态应改成建议态，英文句号后应保留空格。"""

    sanitized, changed = sanitize_abstract_truth(
        {
            "abstract_zh": (
                "系统涵盖用户与订单模块，基于 E-R 模型构建三张数据表。"
                "系统实现过程中，前端采用 Vuex 状态管理，后端通过分层服务并集成 Spring Security。"
                "系统对用户密码采用 BCrypt，同时设计订单状态校验。测试环节采用黑盒测试并验证了主要流程。"
                "系统完成系统的总体设计，确定采用 Spring Data JPA 作为数据访问方案。"
                "在系统测试阶段，对系统关键功能进行了验证。"
                "测试方案拟采用黑盒测试，对用户管理、商品管理与订单管理进行了验证。"
                "系统实现部分阐述了前端开发方案。"
                "本文工作表明，该平台通过 MySQL 数据库、Vuex、Vue Router、JWT 与 BCrypt 统一管理有效改善了信息不对称，提升了交易效率。"
            ),
            "abstract_en": (
                "The back-end is built on Spring Boot. The front-end is constructed using Vue. Js. "
                "The system encompasses three modules. Three core data tables are constructed. "
                "With the front-end is constructed using Vue and the back-end is based on Spring Boot providing APIs, "
                "the MySQL database stores data. The feasibility of the platform was demonstrated. "
                "During system implementation, the system employs BCrypt and implements encryption. "
                "The paper completes the overall system design and adopts Spring Data JPA. "
                "This paper adopts a software engineering approach, conducting research following the process of "
                "requirements analysis, system design, system implementation, and system testing. "
                "The testing phase adopts black-box testing and verifies the main workflow. "
                "Three modules were identified. The front-end sends requests through the Axios library."
            ),
        },
        writing_requirements="避免编造真实运营数据。",
        confirmed_technologies={"Spring Boot", "Vue"},
    )

    assert changed is True
    assert "给出了建议" in sanitized["abstract_zh"]
    assert "本文工作表明" not in sanitized["abstract_zh"]
    assert "拟通过" in sanitized["abstract_zh"]
    assert "MySQL" not in sanitized["abstract_zh"]
    assert "数据库数据库" not in sanitized["abstract_zh"]
    assert "Vuex" not in sanitized["abstract_zh"]
    assert "Vue Router" not in sanitized["abstract_zh"]
    assert "JWT" not in sanitized["abstract_zh"]
    assert "BCrypt" not in sanitized["abstract_zh"]
    assert "Spring Data JPA" not in sanitized["abstract_zh"]
    assert "拟完成系统总体设计" in sanitized["abstract_zh"]
    assert "待确认" in sanitized["abstract_zh"]
    assert "不作为已实现或实测结论" in sanitized["abstract_zh"]
    assert "系统功能拟涵盖" in sanitized["abstract_zh"]
    assert "建议基于 E-R 模型设计" in sanitized["abstract_zh"]
    assert "测试方案拟采用" in sanitized["abstract_zh"]
    assert "对系统关键功能进行了验证" not in sanitized["abstract_zh"]
    assert "规划了系统关键功能验证方案" in sanitized["abstract_zh"]
    assert "对用户管理、商品管理与订单管理进行了验证" not in sanitized["abstract_zh"]
    assert "拟对用户管理、商品管理与订单管理开展验证" in sanitized["abstract_zh"]
    assert "并验证了" not in sanitized["abstract_zh"]
    assert "proposed back-end" in sanitized["abstract_en"].lower()
    assert "proposed system is planned to encompass" in sanitized["abstract_en"].lower()
    assert "proposed testing phase may adopt" in sanitized["abstract_en"].lower()
    assert "and verifies" not in sanitized["abstract_en"].lower()
    assert "spring data jpa" not in sanitized["abstract_en"].lower()
    assert "proposes the overall system design" in sanitized["abstract_en"].lower()
    assert "implementation planning, and test planning" in sanitized["abstract_en"].lower()
    assert "to be confirmed database" not in sanitized["abstract_en"].lower()
    assert "was demonstrated" not in sanitized["abstract_en"].lower()
    assert "not implementation or measured results" in sanitized["abstract_en"].lower()
    assert ". The" in sanitized["abstract_en"]
    assert "Vue.js" in sanitized["abstract_en"]
    assert "the an HTTP client" not in sanitized["abstract_en"]


def test_sanitize_abstract_truth_does_not_duplicate_proposal_marker() -> None:
    """模型已使用“拟”时，事实降级不得生成“拟拟设计”等病句。"""

    sanitized, changed = sanitize_abstract_truth(
        {"abstract_zh": "本文拟设计并实现校园二手交易平台。", "abstract_en": ""},
        writing_requirements="未提供系统实现材料。",
        confirmed_technologies={"Spring Boot", "Vue"},
        include_disclaimer=False,
    )

    assert "拟拟" not in sanitized["abstract_zh"]
    assert "本文拟设计校园二手交易平台" in sanitized["abstract_zh"]
    assert changed is True


def test_normalize_chapter_count_statement_uses_actual_headings() -> None:
    """论文组织结构中的章节数量及枚举应与一级标题一致。"""

    full_text = "全文共分六章。第五章说明系统实现与测试，第六章为总结。\n" + "\n".join(
        f"# {index} 章节{index}" for index in range(1, 8)
    )

    normalized = normalize_chapter_count_statement(full_text)
    assert "本文共分为七章" in normalized
    assert "第七章为章节7" in normalized
    assert "系统实现与测试" not in normalized
