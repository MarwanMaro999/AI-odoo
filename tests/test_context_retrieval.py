from src.chatter_ai.sessions import _chunk_text, _cosine_similarity, _detect_language


def test_chunking_preserves_unicode_and_respects_the_byte_limit() -> None:
    chunks = _chunk_text("English text. " * 80 + "النص العربي مهم. " * 80, 300)

    assert len(chunks) > 1
    assert all(len(chunk.encode("utf-8")) <= 300 for chunk in chunks)
    assert "العربي" in "".join(chunks)


def test_retrieval_helpers_support_arabic_and_english_similarity() -> None:
    assert _detect_language("The project is ready") == "en"
    assert _detect_language("المشروع جاهز") == "ar"
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0
