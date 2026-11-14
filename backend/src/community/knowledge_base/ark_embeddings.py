"""
火山引擎 Ark 多模态向量化封装，兼容 LangChain Embeddings 接口。

使用方式：在 config.yaml 的 knowledge_base.embedding 中配置：
  use: src.community.knowledge_base.ark_embeddings:ArkEmbeddings
  model: doubao-embedding-vision-250615
  api_key: $ARK_API_KEY

环境变量 ARK_API_KEY 为必填（也可通过 config embedding.api_key 传入）。
"""

import os
from typing import List

from langchain_core.embeddings import Embeddings
from volcenginesdkarkruntime import Ark


class ArkEmbeddings(Embeddings):
    """使用火山引擎 Ark 多模态向量化 API 的 LangChain Embeddings 实现。"""

    def __init__(
        self,
        *,
        model: str = "doubao-embedding-vision-250615",
        api_key: str | None = None,
    ) -> None:
        """
        Args:
            model: 向量化模型 endpoint id，如 doubao-embedding-vision-250615。
            api_key: Ark API Key，不传则从环境变量 ARK_API_KEY 读取。
        """
        self.model = model
        key = api_key or os.environ.get("ARK_API_KEY")
        if not key:
            raise ValueError(
                "Ark embeddings 需要 api_key，请在配置中设置 api_key 或环境变量 ARK_API_KEY"
            )
        self._client = Ark(api_key=key)

    def _embed_single(self, text: str) -> List[float]:
        """对单条文本调用 multimodal_embeddings.create，返回向量。"""
        resp = self._client.multimodal_embeddings.create(
            model=self.model,
            input=[{"type": "text", "text": text}],
        )
        data = getattr(resp, "data", None)
        if data is None:
            raise ValueError("Ark multimodal_embeddings 响应中缺少 data")
        return data.embedding

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """对多段文本做向量化（逐条调用 API，每条对应一个向量）。"""
        if not texts:
            return []
        return [self._embed_single(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        """对单条查询文本做向量化。"""
        return self._embed_single(text)
