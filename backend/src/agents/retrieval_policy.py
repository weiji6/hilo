"""Bound ordinary knowledge questions; require explicit intent for deep research."""

import re

from langchain_core.messages import HumanMessage

OVERVIEW_INSTRUCTION = """本轮由主助手直接取证回答，不要派发子任务，不调用 write_todos 或 task。
先用 book_search 选择覆盖问题主题和适用范围的资料；首次查询只用简短的核心主题，
不同版本、阶段、功能或机制放入正文 queries，不要堆砌成一条长书目查询。
优先用 knowledge_locate(doc_id=..., queries=[主题一, 主题二, ...], pages_per_query=2)
批量检索整本书正文，最多八个独立主题；根据真实 PDF 页码补读上下文，必要时用第二份资料核对。
目录、标题、版权页和空白页不能支持正文事实；只看到目录时必须继续定位正文。
每项主要断言引用相应正文，没有读到证据的部分明确写未核实，不用常识填空。
区分已实施行为、建议方案和作者判断；注意资料的版本、时间与适用范围。
PDF 页号与印刷页码不能混用，使用工具返回的物理 PDF 页码和真实 citation。
统计数字保留原文的时段、分母、单位与估算限定；不补写未核实的作者背景。
直接回答问题，省略过程叙述；效率来自批量定位，不靠截断回答或省略必要证据。
"""

OVERVIEW_SUBAGENT_PROMPT = """你负责一个有明确范围的知识概况取证子任务。
只阅读主任务明确指定的 doc_id，逐字复制，不自行选书，不调用 book_search。
不知道章节时先用 knowledge_locate(doc_id=...) 查看导航；然后只读最多两组最相关正文，
每组 3–5 页，用 page_no_end 或 pdf_page_no_end 指定结束页。
可把互不依赖的读页合并在一次模型响应中调用。禁止反复续读以追求覆盖所有主题。
总共最多 4 次工具调用；已有足够证据时提前结束，取不到的内容如实记为缺口。
完成后必须调用一次 submit_task_result，不要写独立 Markdown 报告：
summary 用 100–150 字直接概括已证实的信息并附工具返回的 [citation:N]；
findings 最多 3 条短句，每条不超过 35 字，均附真实 citation；citations 最多 3 个工具返回的编号；
gaps 最多 1 条短句。整个提交不超过 300 字，不重复长篇原文。
只能使用实际读到的证据，不能编造事实、页码和引用。提交后立即结束。
"""

_DEEP = re.compile(
    r"深入|详细|详尽|考证|比较|对比|逐页|全文|文献综述|全面|系统研究|检索所有|不要简略|不要概括"
    r"|原文|页码|引用|出处"
    r"|(?:给出|提供|列出|整理|核对|介绍|查询|查找|检索|逐年|历年).{0,16}(?:数据|统计数据)"
    r"|(?:写|撰写|生成|制作|完成).{0,16}(?:论文|报告)"
    r"|^(?:请|帮我|请帮我|我想|我想要|希望)?研究"
    r"|^research\b"
    r"|\b(?:in[- ]depth|detailed|comprehensive|compare|citations?|page references?)\b",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"(?:你好|您好|嗨|谢谢|多谢|好的|好|收到|继续|停止|取消|重试|再试一次|hello|hi|thanks|stop|continue)[！!。.?？\s]*", re.IGNORECASE)
_ACTION = re.compile(r"(?:请|帮我|请帮我|麻烦|能否|可以)?(?:导出|下载|上传|删除|修改|编辑|部署|安装|运行|执行|创建|新建|翻译|转成|转换|export|download|upload|delete|deploy|install)", re.IGNORECASE)


def is_overview_question(text: str) -> bool:
    if isinstance(text, list):
        if any(not isinstance(part, dict) or part.get("type") != "text" for part in text):
            return False
        text = "\n".join(str(part.get("text", "")) for part in text)
    if not isinstance(text, str):
        return False
    text = text.strip()
    # Default to bounded retrieval, rather than guessing depth from the topic's
    # breadth or enumerating all possible ways to ask for an overview.
    return bool(text) and not (_DEEP.search(text) or _CONTROL.fullmatch(text) or _ACTION.match(text))


def overview_from_messages(messages: list) -> bool:
    """Use only the latest user turn, never an earlier introductory question."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return is_overview_question(message.content)
        if isinstance(message, dict) and message.get("type", message.get("role")) in {"human", "user"}:
            return is_overview_question(message.get("content", ""))
    return False
