from src.community.knowledge_base.translation_grpc import (
    _build_metadata,
    _resolve_target,
)
from src.config.knowledge_base_config import get_knowledge_base_config, load_knowledge_base_config_from_dict


def test_translation_grpc_inherits_mineru_host_only() -> None:
    load_knowledge_base_config_from_dict(
        {
            "enabled": True,
            "mineru": {
                "enabled": True,
                "target": "mineru.internal:50051",
                "use_tls": True,
                "api_token": "mineru-token",
            },
            "translation_rpc": {
                "enabled": True,
                "request_timeout": 30,
            },
        }
    )

    config = get_knowledge_base_config().translation_rpc
    assert config is not None

    assert _resolve_target(config) == "mineru.internal:50052"
    assert config.use_tls is False
    assert _build_metadata(config) == []
