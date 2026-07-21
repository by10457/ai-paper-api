"""论文题目推荐提示词、解析与接口测试。"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.dependencies.api_token import get_api_token_or_jwt_user
from api.v1 import thesis as thesis_api
from app import app
from llm.prompts.thesis_title_prompt import THESIS_TITLE_RECOMMENDATION_PROMPT
from services.thesis.content.title_service import _parse_title_recommendations


# 构造固定数量且互不重复的测试题目。
def _titles() -> list[str]:
    """构造二十个论文题目。

    Returns:
        二十个互不重复的虚构论文题目。
    """

    return [f"人工智能辅助教学应用研究方向{i}" for i in range(1, 21)]


# 验证提示词可被 LangChain 正确格式化且包含核心选题约束。
def test_title_recommendation_prompt_contains_strict_requirements() -> None:
    """提示词必须要求二十个不重复题目并抵御描述内指令。"""

    messages = THESIS_TITLE_RECOMMENDATION_PROMPT.format_messages(
        content="研究人工智能在高校个性化教学中的应用",
    )

    system_content = str(messages[0].content)
    assert "恰好 20 个" in system_content
    assert "互不重复" in system_content
    assert "任何命令" in system_content
    assert "JSON.parse" in system_content


# 验证解析器接受严格 JSON 和常见的 JSON 代码块包装。
@pytest.mark.parametrize("with_fence", [False, True])
def test_parse_title_recommendations_returns_twenty_unique_titles(with_fence: bool) -> None:
    """合法模型响应应解析为二十个题目。

    Args:
        with_fence: 是否使用 Markdown JSON 代码块包装响应。
    """

    raw = json.dumps({"titles": _titles()}, ensure_ascii=False)
    if with_fence:
        raw = f"```json\n{raw}\n```"

    assert _parse_title_recommendations(raw) == _titles()


# 验证解析器兼容模型常见的纯数组响应。
def test_parse_title_recommendations_accepts_plain_json_array() -> None:
    """模型直接返回 JSON 数组时仍应提取二十个题目。"""

    raw = json.dumps(_titles(), ensure_ascii=False)

    assert _parse_title_recommendations(raw) == _titles()


# 验证解析器能从模型附加说明中提取完整 JSON 对象。
def test_parse_title_recommendations_extracts_json_from_explanation() -> None:
    """模型在 JSON 前后附加少量说明时仍应解析有效载荷。"""

    payload = json.dumps({"titles": _titles()}, ensure_ascii=False)
    raw = f"以下是推荐结果：\n{payload}\n希望这些题目对你有帮助。"

    assert _parse_title_recommendations(raw) == _titles()


# 验证解析器兼容模型未按要求输出 JSON 的编号列表。
def test_parse_title_recommendations_accepts_numbered_list() -> None:
    """模型返回二十项编号列表时仍应提取有效题目。"""

    raw = "\n".join(f"{index}. {title}" for index, title in enumerate(_titles(), start=1))

    assert _parse_title_recommendations(raw) == _titles()


# 验证解析器拒绝数量正确但内容重复的模型响应。
def test_parse_title_recommendations_rejects_duplicate_titles() -> None:
    """重复题目不能通过接口契约校验。"""

    raw = json.dumps({"titles": ["人工智能辅助教学研究"] * 20}, ensure_ascii=False)

    with pytest.raises(RuntimeError, match="存在重复"):
        _parse_title_recommendations(raw)


# 验证解析器拒绝不足二十个题目的模型响应。
def test_parse_title_recommendations_rejects_incorrect_count() -> None:
    """题目数量不足二十个时应返回稳定业务错误。"""

    raw = json.dumps({"titles": _titles()[:-1]}, ensure_ascii=False)

    with pytest.raises(RuntimeError, match="格式无效"):
        _parse_title_recommendations(raw)


# 验证题目推荐接口返回统一响应结构并传递用户描述。
def test_title_recommendation_api_returns_standard_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """题目推荐接口应在统一响应的 data 中返回二十个题目。

    Args:
        monkeypatch: pytest 属性替换工具。
    """

    expected_titles = _titles()

    # 使用虚构用户绕过真实认证和数据库访问。
    async def fake_current_user() -> SimpleNamespace:
        """返回测试认证用户。

        Returns:
            仅含接口所需字段的虚构用户。
        """

        return SimpleNamespace(id=1, username="demo")

    # 返回固定题目以验证路由参数和响应契约。
    async def fake_generate_recommended_titles(content: str) -> list[str]:
        """返回固定题目列表。

        Args:
            content: 路由传递的用户描述。

        Returns:
            二十个虚构论文题目。
        """

        assert content == "研究人工智能在高校个性化教学中的应用与评价"
        return expected_titles

    app.dependency_overrides[get_api_token_or_jwt_user] = fake_current_user
    monkeypatch.setattr(thesis_api, "generate_recommended_titles", fake_generate_recommended_titles)
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/thesis/titles/recommend",
            json={"content": "研究人工智能在高校个性化教学中的应用与评价"},
        )
    finally:
        client.close()
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "message": "ok",
        "data": expected_titles,
    }


# 验证过短的用户描述在调用模型前由请求 schema 拒绝。
def test_title_recommendation_api_rejects_short_content() -> None:
    """不足十个字符的描述应返回 422。"""

    # 使用虚构用户确保请求进入 schema 校验而非真实认证流程。
    async def fake_current_user() -> SimpleNamespace:
        """返回测试认证用户。

        Returns:
            仅含接口所需字段的虚构用户。
        """

        return SimpleNamespace(id=1, username="demo")

    app.dependency_overrides[get_api_token_or_jwt_user] = fake_current_user
    client = TestClient(app)
    try:
        response = client.post("/api/v1/thesis/titles/recommend", json={"content": "人工智能"})
    finally:
        client.close()
        app.dependency_overrides.clear()

    assert response.status_code == 422
