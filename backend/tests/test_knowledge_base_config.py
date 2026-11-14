"""Tests for knowledge base configuration, including MinerU settings."""

from src.config.knowledge_base_config import (
    BookMetadataConfig,
    KnowledgeBaseConfig,
    MineruConfig,
    TranslationRpcConfig,
    load_knowledge_base_config_from_dict,
    get_knowledge_base_config,
)


class TestMineruConfig:
    """Tests for MineruConfig defaults and integration with KnowledgeBaseConfig."""

    def test_mineru_default_disabled(self):
        """MineruConfig should be disabled by default when not provided."""
        cfg = KnowledgeBaseConfig()
        assert cfg.mineru is None

    def test_qdrant_request_timeout_default_is_one_hour(self):
        cfg = KnowledgeBaseConfig()
        assert cfg.qdrant.request_timeout == 3600
        assert cfg.qdrant.upsert_batch_size == 64
        assert cfg.qdrant.upsert_parallelism == 2

    def test_mineru_request_timeout_default_supports_long_jobs(self):
        cfg = MineruConfig()
        assert cfg.request_timeout == 14400
        assert cfg.keepalive_time_ms == 180000
        assert cfg.keepalive_timeout_ms == 180000
        assert cfg.keepalive_permit_without_calls is True
        assert cfg.max_message_bytes == 512 * 1024 * 1024
        assert cfg.enable_pdf_chunking is True
        assert cfg.pdf_split_page_threshold == 1200
        assert cfg.pdf_chunk_page_count == 1000
        assert cfg.pdf_split_size_threshold_bytes == 256 * 1024 * 1024

    def test_mineru_custom_config(self):
        """Custom Mineru configuration should be loaded correctly."""
        data = {
            "enabled": True,
            "docs_path": "knowledge/docs",
            "mineru": {
                "enabled": True,
                "target": "mineru.internal:50051",
                "use_tls": True,
                "api_token": "test-token",
                "model_version": "vlm-test",
                "request_timeout": 10,
                "keepalive_time_ms": 45000,
                "keepalive_timeout_ms": 15000,
                "keepalive_permit_without_calls": False,
                "max_message_bytes": 1024,
                "enable_pdf_chunking": True,
                "pdf_split_page_threshold": 200,
                "pdf_chunk_page_count": 40,
                "pdf_split_size_threshold_bytes": 2048,
            },
        }

        load_knowledge_base_config_from_dict(data)
        cfg = get_knowledge_base_config()

        assert cfg.enabled is True
        assert isinstance(cfg.mineru, MineruConfig)
        assert cfg.mineru.enabled is True
        assert cfg.mineru.target == "mineru.internal:50051"
        assert cfg.mineru.use_tls is True
        assert cfg.mineru.api_token == "test-token"
        assert cfg.mineru.model_version == "vlm-test"
        assert cfg.mineru.request_timeout == 10
        assert cfg.mineru.keepalive_time_ms == 45000
        assert cfg.mineru.keepalive_timeout_ms == 15000
        assert cfg.mineru.keepalive_permit_without_calls is False
        assert cfg.mineru.max_message_bytes == 1024
        assert cfg.mineru.enable_pdf_chunking is True
        assert cfg.mineru.pdf_split_page_threshold == 200
        assert cfg.mineru.pdf_chunk_page_count == 40
        assert cfg.mineru.pdf_split_size_threshold_bytes == 2048

    def test_book_metadata_custom_config(self):
        data = {
            "enabled": True,
            "docs_path": "knowledge/docs",
            "book_metadata": {
                "enabled": True,
                "model_name": "doubao-seed-2.0-pro",
                "front_page_limit": 12,
                "body_sample_count": 4,
                "max_excerpt_chars": 1600,
            },
        }

        load_knowledge_base_config_from_dict(data)
        cfg = get_knowledge_base_config()

        assert isinstance(cfg.book_metadata, BookMetadataConfig)
        assert cfg.book_metadata.enabled is True
        assert cfg.book_metadata.model_name == "doubao-seed-2.0-pro"
        assert cfg.book_metadata.front_page_limit == 12
        assert cfg.book_metadata.body_sample_count == 4
        assert cfg.book_metadata.max_excerpt_chars == 1600

    def test_translation_rpc_custom_config(self):
        data = {
            "enabled": True,
            "docs_path": "knowledge/docs",
            "translation_rpc": {
                "enabled": True,
                "target": "translation.internal:50052",
                "use_tls": True,
                "api_token": "translation-token",
                "request_timeout": 25,
            },
        }

        load_knowledge_base_config_from_dict(data)
        cfg = get_knowledge_base_config()

        assert isinstance(cfg.translation_rpc, TranslationRpcConfig)
        assert cfg.translation_rpc.enabled is True
        assert cfg.translation_rpc.target == "translation.internal:50052"
        assert cfg.translation_rpc.use_tls is True
        assert cfg.translation_rpc.api_token == "translation-token"
        assert cfg.translation_rpc.request_timeout == 25
