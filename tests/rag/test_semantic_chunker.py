"""Phase 3-1-6 — SemanticChunker 의 sanity test (실제 임베딩 무관 fake provider)."""

from __future__ import annotations


from core.rag.semantic_chunker import SemanticChunker


class _FakeEmb:
    """첫 키워드로 cluster 결정 — 의미 경계 시뮬레이션."""

    async def embed(self, texts):
        result = []
        for t in texts:
            t_low = t.lower()
            # 키워드 기반 cluster: A (재무) / B (기술)
            if any(k in t_low for k in ["매출", "원가", "회계", "재무", "수익"]):
                result.append([1.0, 0.0, 0.0] + [0.0] * 1021)
            else:
                result.append([0.0, 1.0, 0.0] + [0.0] * 1021)
        return result


async def test_split_short_text_returns_single_chunk():
    chunker = SemanticChunker(_FakeEmb())
    out = await chunker.split("짧은 문장.")
    assert len(out) == 1


async def test_split_respects_max_chars():
    chunker = SemanticChunker(_FakeEmb(), max_chars_per_chunk=80)
    # 4 문장, 모두 짧은 cluster → 의미 경계 없음 but max_chars 가 강제 분리
    text = "첫 문장 길이 30자입니다 abc def. 둘째 문장도 짧습니다 ghi. 셋째 문장 jkl mno. 넷째 마지막입니다."
    out = await chunker.split(text)
    assert all(len(c) <= 100 for c in out)   # 약간 여유 두고 검증


async def test_split_detects_semantic_boundary():
    chunker = SemanticChunker(_FakeEmb(), threshold_percentile=50.0, min_sentences_per_chunk=1)
    # 재무 cluster 2 개 + 기술 cluster 2 개 — 의미 경계
    text = (
        "당사의 매출 인식 정책은 1115호를 따른다. "
        "원가 산정은 표준원가법 적용. "
        "서버 인프라는 클라우드 기반으로 구성. "
        "네트워크 보안은 zero-trust 모델."
    )
    out = await chunker.split(text)
    assert len(out) >= 2   # 의미 경계에서 분리
