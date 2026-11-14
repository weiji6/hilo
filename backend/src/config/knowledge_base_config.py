from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class QdrantConfig(BaseModel):
    """Configuration for Qdrant vector database."""

    mode: Literal["local", "server"] = Field(
        default="local",
        description="Qdrant mode: 'local' (embedded) or 'server' (client-server).",
    )
    local_path: str = Field(
        default=".deer-flow/qdrant",
        description="Path for local Qdrant storage (only used when mode='local').",
    )
    url: str | None = Field(
        default=None,
        description="Qdrant server URL (only used when mode='server').",
    )
    api_key: str | None = Field(
        default=None,
        description="Qdrant API key (only used when mode='server').",
    )
    collection_name: str = Field(
        default="knowledge_base",
        description="Name of the Qdrant collection.",
    )
    request_timeout: int = Field(
        default=3600,
        description="Timeout in seconds for Qdrant HTTP requests when using server mode.",
    )
    upsert_batch_size: int = Field(
        default=64,
        ge=1,
        le=1024,
        description="Number of chunks written to Qdrant per batch.",
    )
    upsert_parallelism: int = Field(
        default=2,
        ge=1,
        le=8,
        description="Maximum parallel shard uploads for a single document during fresh global reindex.",
    )


class EmbeddingConfig(BaseModel):
    """Configuration for embedding model."""

    use: str = Field(
        description="LangChain embedding class path (e.g. 'langchain_openai:OpenAIEmbeddings').",
    )
    model: str = Field(
        description="Model name/id to use.",
    )
    api_key: str | None = Field(
        default=None,
        description="API key for the embedding service.",
    )
    api_base: str | None = Field(
        default=None,
        description="API base URL for the embedding service (optional).",
    )


class ChunkingConfig(BaseModel):
    """Configuration for text chunking."""

    chunk_size: int = Field(
        default=1000,
        description="Size of text chunks in characters.",
    )
    chunk_overlap: int = Field(
        default=200,
        description="Overlap between chunks in characters.",
    )


class RetrievalConfig(BaseModel):
    """Configuration for retrieval parameters."""

    top_k: int = Field(
        default=5,
        description="Number of relevant chunks to retrieve.",
    )
    score_threshold: float = Field(
        default=0.3,
        description="Minimum similarity score threshold (0.0 to 1.0).",
    )


class MineruConfig(BaseModel):
    """Configuration for MinerU gRPC based PDF conversion."""

    enabled: bool = Field(
        default=False,
        description="Whether MinerU-based PDF → Markdown conversion is enabled.",
    )
    target: str = Field(
        default="127.0.0.1:50051",
        description="gRPC target for the internal MinerU service, e.g. host:port.",
    )
    use_tls: bool = Field(
        default=False,
        description="Whether to connect to the MinerU gRPC service with TLS.",
    )
    api_token: str | None = Field(
        default=None,
        description="Optional bearer token sent as gRPC metadata.",
    )
    model_version: str = Field(
        default="vlm",
        description="Model version passed to MinerU (e.g. 'vlm').",
    )
    request_timeout: int = Field(
        default=14400,
        description="Timeout in seconds for the MinerU gRPC request, tuned for large OCR jobs.",
    )
    keepalive_time_ms: int = Field(
        default=20000,
        ge=1,
        description=(
            "Interval in milliseconds between gRPC keepalive pings. Tuned short "
            "(20s) so that long server-side OCR queueing does not let any "
            "intermediary (or the OS) decide the TCP connection is idle. "
            "Override via MINERU_GRPC_KEEPALIVE_TIME_MS."
        ),
    )
    keepalive_timeout_ms: int = Field(
        default=20000,
        ge=1,
        description=(
            "Timeout in milliseconds for gRPC keepalive ping acknowledgements. "
            "If the server fails to ack within this window we treat the "
            "connection as dead and the call surfaces an RpcError that can be "
            "retried instead of hanging forever."
        ),
    )
    keepalive_permit_without_calls: bool = Field(
        default=True,
        description="Whether MinerU gRPC keepalive pings are allowed when there are no active RPCs.",
    )
    max_message_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=1,
        description="Maximum gRPC request/response size in bytes for MinerU.",
    )
    enable_pdf_chunking: bool = Field(
        default=True,
        description="Whether oversized PDFs should be auto-split into smaller OCR chunks before sending to MinerU.",
    )
    pdf_split_page_threshold: int = Field(
        default=1200,
        ge=1,
        description="Automatically split PDFs when page count exceeds this threshold.",
    )
    pdf_chunk_page_count: int = Field(
        default=1000,
        ge=1,
        description="Maximum number of pages per auto-split PDF chunk sent to MinerU.",
    )
    pdf_split_size_threshold_bytes: int = Field(
        default=256 * 1024 * 1024,
        ge=1,
        description="Automatically split PDFs when file size exceeds this threshold in bytes.",
    )
    max_concurrent_ocr_jobs: int = Field(
        default=12,
        ge=1,
        description="Maximum number of concurrent OCR gRPC requests issued from this process.",
    )
    retry_attempts: int = Field(
        default=3,
        ge=0,
        description="Number of retry attempts on transient gRPC errors (e.g. SSH tunnel reconnect). 0 disables retries.",
    )
    retry_delay_seconds: float = Field(
        default=5.0,
        ge=0.0,
        description="Seconds to wait between retry attempts.",
    )


class MineruApiConfig(BaseModel):
    """Configuration for MinerU remote HTTP API based document parsing."""

    enabled: bool = Field(
        default=False,
        description="Whether MinerU remote API parsing is enabled.",
    )
    api_token: str = Field(
        default="",
        description="API token for mineru.net (Bearer auth).",
    )
    base_url: str = Field(
        default="https://mineru.net",
        description="Base URL of the MinerU service.",
    )
    model_version: str = Field(
        default="vlm",
        description="Model version to use (e.g. 'vlm', 'pipeline').",
    )
    request_timeout: int = Field(
        default=300,
        description="HTTP request timeout in seconds.",
    )
    poll_interval_seconds: float = Field(
        default=5.0,
        ge=1.0,
        description="Seconds to wait between polling attempts.",
    )
    max_poll_attempts: int = Field(
        default=120,
        ge=1,
        description="Maximum number of polling attempts before giving up.",
    )

    model_config = ConfigDict(protected_namespaces=())


class TranslationRpcConfig(BaseModel):
    """Configuration for translation gRPC service."""

    enabled: bool = Field(
        default=False,
        description="Whether the translation gRPC service is enabled.",
    )
    target: str | None = Field(
        default=None,
        description="Optional gRPC target for the internal translation service. Defaults to MinerU host with the translation port when omitted.",
    )
    use_tls: bool = Field(
        default=False,
        description="Whether to connect to the translation gRPC service with TLS.",
    )
    api_token: str | None = Field(
        default=None,
        description="Optional bearer token sent as gRPC metadata.",
    )
    request_timeout: int = Field(
        default=60,
        description="Timeout in seconds for the translation gRPC request.",
    )


class BookMetadataConfig(BaseModel):
    """Configuration for AI-generated book routing metadata."""

    enabled: bool = Field(
        default=False,
        description="Whether AI-generated book metadata is enabled after OCR/parse.",
    )
    model_name: str | None = Field(
        default=None,
        description="Optional chat model name used for metadata generation. Defaults to the app default model.",
    )
    front_page_limit: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Number of leading pages to include in the metadata prompt bundle.",
    )
    body_sample_count: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Number of evenly sampled body pages to include after the front-page window.",
    )
    max_excerpt_chars: int = Field(
        default=1200,
        ge=200,
        le=4000,
        description="Maximum characters per sampled page excerpt.",
    )

    model_config = ConfigDict(protected_namespaces=())


class KnowledgeBaseConfig(BaseModel):
    """Configuration for the Knowledge Base RAG system."""

    enabled: bool = Field(
        default=False,
        description="Whether the knowledge base system is enabled.",
    )
    docs_path: str = Field(
        default="knowledge/docs",
        description="Path to the directory containing knowledge documents.",
    )
    qdrant: QdrantConfig = Field(
        default_factory=QdrantConfig,
        description="Qdrant vector database configuration.",
    )
    embedding: EmbeddingConfig | None = Field(
        default=None,
        description="Embedding model configuration.",
    )
    chunking: ChunkingConfig = Field(
        default_factory=ChunkingConfig,
        description="Text chunking configuration.",
    )
    retrieval: RetrievalConfig = Field(
        default_factory=RetrievalConfig,
        description="Retrieval parameters.",
    )
    mineru: MineruConfig | None = Field(
        default=None,
        description="Optional MinerU KIE configuration for PDF → Markdown conversion.",
    )
    mineru_api: MineruApiConfig | None = Field(
        default=None,
        description="Optional MinerU remote HTTP API configuration (mineru.net).",
    )
    translation_rpc: TranslationRpcConfig | None = Field(
        default=None,
        description="Optional translation gRPC service configuration.",
    )
    book_metadata: BookMetadataConfig | None = Field(
        default=None,
        description="Optional AI-generated book routing metadata configuration.",
    )

    model_config = ConfigDict(extra="allow")


_knowledge_base_config: KnowledgeBaseConfig | None = None


def load_knowledge_base_config_from_dict(config_dict: dict[str, Any]) -> None:
    """Load knowledge base config from a dictionary.

    Args:
        config_dict: Dictionary containing knowledge base configuration.
    """
    global _knowledge_base_config
    if config_dict:
        _knowledge_base_config = KnowledgeBaseConfig(**config_dict)
    else:
        _knowledge_base_config = KnowledgeBaseConfig(enabled=False)


def get_knowledge_base_config() -> KnowledgeBaseConfig:
    """Get the global knowledge base configuration.

    Returns:
        The knowledge base configuration object.
    """
    global _knowledge_base_config
    if _knowledge_base_config is None:
        # Return default disabled config if not loaded
        return KnowledgeBaseConfig(enabled=False)
    return _knowledge_base_config
