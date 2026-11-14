"""Translation gRPC integration for structured paragraph translation."""

from __future__ import annotations

import os

import grpc

from src.community.knowledge_base.translation_proto import translation_pb2, translation_pb2_grpc
from src.config.knowledge_base_config import MineruConfig, TranslationRpcConfig, get_knowledge_base_config

DEFAULT_MAX_GRPC_MESSAGE_BYTES = 32 * 1024 * 1024
DEFAULT_TRANSLATION_TARGET = "127.0.0.1:50052"


def _get_max_grpc_message_bytes() -> int:
    raw_value = (os.getenv("TRANSLATION_GRPC_MAX_MESSAGE_BYTES") or "").strip()
    if not raw_value:
        return DEFAULT_MAX_GRPC_MESSAGE_BYTES
    try:
        parsed = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_GRPC_MESSAGE_BYTES
    return parsed if parsed > 0 else DEFAULT_MAX_GRPC_MESSAGE_BYTES


def _get_translation_config() -> TranslationRpcConfig:
    config = get_knowledge_base_config().translation_rpc
    if config is None or not config.enabled:
        raise RuntimeError("Translation gRPC is not configured or is disabled")
    return config


def _get_mineru_config() -> MineruConfig | None:
    config = get_knowledge_base_config().mineru
    if config is None or not config.enabled:
        return None
    return config


def _replace_target_port(target: str, port: int) -> str:
    normalized = target.strip()
    if not normalized:
        return DEFAULT_TRANSLATION_TARGET
    if normalized.startswith("[") and "]:" in normalized:
        host, _, _ = normalized.rpartition(":")
        return f"{host}:{port}"
    if ":" in normalized:
        host, _, _ = normalized.rpartition(":")
        if host:
            return f"{host}:{port}"
    return f"{normalized}:{port}"


def _resolve_target(config: TranslationRpcConfig) -> str:
    target = str(config.target or "").strip()
    if target:
        return target

    mineru_config = _get_mineru_config()
    mineru_target = str(mineru_config.target if mineru_config else "").strip()
    if mineru_target:
        return _replace_target_port(mineru_target, 50052)
    return DEFAULT_TRANSLATION_TARGET


def _build_metadata(config: TranslationRpcConfig) -> list[tuple[str, str]]:
    api_token = str(config.api_token or "").strip()
    if not api_token:
        return []
    return [("authorization", f"Bearer {api_token}")]


def _build_channel(config: TranslationRpcConfig) -> grpc.Channel:
    max_message_bytes = _get_max_grpc_message_bytes()
    options = [
        ("grpc.max_send_message_length", max_message_bytes),
        ("grpc.max_receive_message_length", max_message_bytes),
    ]
    target = _resolve_target(config)
    if config.use_tls:
        credentials = grpc.ssl_channel_credentials()
        return grpc.secure_channel(target, credentials, options=options)
    return grpc.insecure_channel(target, options=options)


def translate_blocks_via_grpc(
    blocks: list[dict[str, str]],
    *,
    target_language: str = "zh",
    source_language_hint: str | None = None,
) -> list[dict[str, str]]:
    config = _get_translation_config()

    normalized_blocks = [
        {
            "id": str(block.get("id") or "").strip(),
            "text": str(block.get("text") or "").strip(),
        }
        for block in blocks
        if str(block.get("id") or "").strip() and str(block.get("text") or "").strip()
    ]
    if not normalized_blocks:
        return []

    request = translation_pb2.TranslateBlocksRequest(
        blocks=[
            translation_pb2.TranslationBlock(key=block["id"], text=block["text"])
            for block in normalized_blocks
        ],
        target_language=target_language,
        source_language_hint=source_language_hint or "",
    )

    try:
        with _build_channel(config) as channel:
            stub = translation_pb2_grpc.TranslationServiceStub(channel)
            response = stub.TranslateBlocks(
                request,
                timeout=config.request_timeout,
                metadata=_build_metadata(config),
            )
    except grpc.RpcError as exc:
        raise RuntimeError(f"Translation gRPC failed: {exc.code().name} {exc.details()}") from exc

    return [
        {
            "id": item.key,
            "translation": item.translation,
            "source_language": item.source_language,
        }
        for item in response.translations
        if item.key and item.translation
    ]


def translate_blocks_to_chinese_via_grpc(
    blocks: list[dict[str, str]],
    *,
    source_language_hint: str | None = None,
) -> list[dict[str, str]]:
    return translate_blocks_via_grpc(
        blocks,
        target_language="zh",
        source_language_hint=source_language_hint,
    )
