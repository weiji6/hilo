import sys
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from src.community.knowledge_base.locator import LocatedDocument
from src.gateway.routers import knowledge as knowledge_router
from src.gateway.routers import user_knowledge as user_knowledge_router


class _FakePixmap:
    def tobytes(self, fmt: str, **kwargs) -> bytes:
        assert fmt == "jpeg"
        return b"jpeg-bytes"


class _FakePage:
    def get_pixmap(self, *, dpi: int, colorspace, alpha: bool) -> _FakePixmap:
        assert dpi == 144
        assert alpha is False
        return _FakePixmap()


class _FakePdf:
    page_count = 10

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def load_page(self, page_index: int) -> _FakePage:
        assert page_index == 4
        return _FakePage()


def _install_fake_fitz(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "fitz",
        SimpleNamespace(open=lambda path: _FakePdf(), csRGB="rgb"),
    )


def test_global_page_image_uses_resolved_filename(monkeypatch, tmp_path: Path) -> None:
    real_pdf = tmp_path / "光绪朝上谕档第一七册（光绪一七年）.pdf"
    real_pdf.write_bytes(b"fake pdf")

    monkeypatch.setattr(knowledge_router, "get_global_docs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        knowledge_router,
        "locate_document",
        lambda thread_id=None, filename=None: LocatedDocument(
            doc_id="doc-1",
            title="光绪朝上谕档第一七册（光绪一七年）",
            filename=real_pdf.name,
            scope="global",
            source_url="",
            original_url="",
            payload={"pages": []},
        ),
    )
    _install_fake_fitz(monkeypatch)

    response = knowledge_router.get_knowledge_document_page_image(
        filename="光绪朝上讠档第一七册（光绪一七年）.pdf",
        pdf_page_no=5,
        request=Request({"type": "http", "headers": []}),
        dpi=144,
    )

    assert response.body == b"jpeg-bytes"


def test_user_page_image_uses_resolved_filename(monkeypatch, tmp_path: Path) -> None:
    real_pdf = tmp_path / "光绪朝东华录.pdf"
    real_pdf.write_bytes(b"fake pdf")

    monkeypatch.setattr(user_knowledge_router, "get_user_docs_dir", lambda user_id: tmp_path)
    monkeypatch.setattr(
        user_knowledge_router,
        "locate_document",
        lambda thread_id=None, user_id=None, filename=None: LocatedDocument(
            doc_id="doc-2",
            title="光绪朝东华录",
            filename=real_pdf.name,
            scope="user",
            source_url="",
            original_url="",
            payload={"pages": []},
        ),
    )
    _install_fake_fitz(monkeypatch)

    response = user_knowledge_router.get_user_knowledge_document_page_image(
        user_id="user-1",
        filename="光续朝东 华录.pdf",
        pdf_page_no=5,
        request=Request({"type": "http", "headers": []}),
        dpi=144,
    )

    assert response.body == b"jpeg-bytes"
