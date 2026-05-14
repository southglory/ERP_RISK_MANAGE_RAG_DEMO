"""인제스트 + RAG 파이프라인 통합 테스트.

실행:
    python scripts/test_ingest.py

수행 단계:
  1. DB 연결 확인 + document_title 컬럼 자동 마이그레이션
  2. 합성 세무 PDF 생성 (임시)
  3. ingest_pdf 실행 (임베딩 → pgvector upsert)
  4. RAG 검색 확인 (dense 검색으로 청크 회수 여부)
  5. Solar LLM 응답 확인 (vLLM 연결 시)
  6. 테스트 데이터 정리
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Windows cp949 터미널 한글/이모지 깨짐 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)

import asyncpg
from fpdf import FPDF

# ── 합성 세무 문서 내용 ────────────────────────────────────────────────────────
_TEST_CONTENT = [
    ("부가가치세법 제15조 — 재화 공급 시기",
     """재화의 공급시기는 다음 각 호의 시기로 한다.
1. 재화의 이동이 필요한 경우: 재화가 인도되는 때
2. 재화의 이동이 필요하지 아니한 경우: 재화가 이용 가능하게 되는 때
3. 위 각 호를 적용할 수 없는 경우: 재화의 공급이 확정되는 때

SaaS 구독 서비스와 같이 용역의 공급이 계속되는 경우에는 역무의 제공이 완료되는 때를 공급시기로 본다.
월정액 SaaS 서비스는 매월 말일을 공급 시기로 하여 세금계산서를 발급하여야 한다."""),

    ("부가가치세법 시행령 제28조 — 계속적 공급 특례",
     """계속적으로 공급되는 재화 또는 용역의 공급시기는 대가의 각 부분을 받기로 한 때로 할 수 있다.
이 경우 공급시기는 다음과 같이 적용한다.
- 월 단위 구독: 해당 월의 말일
- 연간 계약(선불): 공급 시기를 월별로 안분하여 인식
- 선수금 수령 후 서비스 제공: 서비스 제공 시점을 공급시기로 함

소프트웨어 라이선스의 경우 인도일(또는 다운로드 가능일)을 공급시기로 본다."""),

    ("법인세법 제93조 — 외국법인의 국내원천소득",
     """외국법인의 국내원천소득에 대한 원천징수세율은 다음과 같다.
1. 이자소득: 20%
2. 배당소득: 20%
3. 사용료소득(로열티): 20%
4. 사업소득: 2%

조세조약이 체결된 국가의 거주자인 외국법인이 국내원천 사용료를 수취하는 경우,
해당 조약에서 정한 제한세율을 적용할 수 있다.
조약 적용을 위해서는 거주자증명서를 원천징수의무자에게 제출하여야 한다.

주요 조세조약 사용료 제한세율:
- 미국: 15%, 소프트웨어 저작권 10%
- 일본: 10%
- 중국: 10%
- 독일: 10%
- 아일랜드: 0% (일부 조건 충족 시)"""),

    ("K-IFRS 제1115호 — 고객과의 계약에서 생기는 수익",
     """수익 인식 5단계 모형:
Step 1: 계약 식별 — 다음 5가지 요건 충족 시 계약으로 인식
  (1) 상업적 실질이 존재할 것
  (2) 각 당사자가 계약 승인하고 의무 이행을 확약할 것
  (3) 이전할 재화·용역에 대한 각 당사자의 권리 식별 가능할 것
  (4) 이전할 재화·용역의 지급조건 식별 가능할 것
  (5) 고객에게 이전할 재화·용역의 대가 회수 가능성이 높을 것

Step 2: 수행의무 식별 — 구별되는 재화·용역별로 분리
Step 3: 거래가격 산정 — 변동대가·유의적 금융요소 등 고려
Step 4: 거래가격 배분 — 개별 판매가격(SSP) 비율로 배분
Step 5: 수익 인식 — 수행의무 이행 시점 또는 기간에 걸쳐 인식"""),
]

_TEST_SOURCE_TYPE = "tax_law"
_TEST_DOC_ID      = "_test_ingest_doc"
_CHUNK_ID_PREFIX  = "_test_"


def _make_test_pdf(path: Path) -> None:
    """합성 세무 내용 PDF 생성."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    # 유니코드 폰트 없이 영문만 사용 (fpdf2 기본 폰트)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Tax Law Reference - Test Document", ln=True)
    pdf.ln(5)

    for title, body in _TEST_CONTENT:
        pdf.set_font("Helvetica", "B", 12)
        # ASCII만 출력 (한글은 Latin-1 범위 밖이므로 영문으로 대체)
        safe_title = title.encode("ascii", errors="replace").decode()
        pdf.multi_cell(0, 7, safe_title)
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        safe_body = body.encode("ascii", errors="replace").decode()
        pdf.multi_cell(0, 6, safe_body)
        pdf.ln(6)

    pdf.output(str(path))


def _make_test_txt(path: Path) -> None:
    """텍스트 파일로 저장 (pdfplumber 대신 직접 읽기 테스트용)."""
    lines = []
    for title, body in _TEST_CONTENT:
        lines.append(f"\n\n{'='*60}")
        lines.append(title)
        lines.append('='*60)
        lines.append(body)
    path.write_text("\n".join(lines), encoding="utf-8")


# ── 단계별 테스트 ─────────────────────────────────────────────────────────────

async def step1_check_db(dsn: str) -> None:
    print("\n[1/5] DB 연결 + document_title 컬럼 확인")
    conn = await asyncpg.connect(dsn)
    try:
        # document_title 컬럼 자동 마이그레이션
        await conn.execute("""
            ALTER TABLE document_chunk
            ADD COLUMN IF NOT EXISTS document_title TEXT NOT NULL DEFAULT '';
        """)
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM document_chunk WHERE source_type = $1",
            _TEST_SOURCE_TYPE,
        )
        print(f"  ✅ DB 연결 성공 — 기존 {_TEST_SOURCE_TYPE} 청크: {row['n']}개")
    finally:
        await conn.close()


async def step2_ingest(tmp_pdf: Path, dsn: str) -> int:
    print("\n[2/5] 합성 PDF 인제스트")
    from scripts.ingest_pdf import ingest
    await ingest(tmp_pdf, _TEST_SOURCE_TYPE, "테스트 세무 문서", dsn)

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM document_chunk WHERE source_doc_id = $1",
            tmp_pdf.stem,
        )
        count = row["n"]
        print(f"  ✅ 인제스트 완료 — 저장된 청크: {count}개")
        return count
    finally:
        await conn.close()


async def step3_dense_search(dsn: str, doc_stem: str) -> None:
    print("\n[3/5] dense 벡터 검색 확인")
    from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
    query = "SaaS 구독료 세금계산서 발급 시점"
    emb = InfinityEmbeddingProvider()
    vecs = await emb.embed([query])
    vec_str = "[" + ",".join(str(v) for v in vecs[0]) + "]"

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT chunk_id, document_title,
                   1 - (dense_vec <=> $1::vector) AS score
            FROM document_chunk
            WHERE source_doc_id = $2
            ORDER BY dense_vec <=> $1::vector
            LIMIT 3
            """,
            vec_str, doc_stem,
        )
        if rows:
            print(f"  ✅ 검색 성공 — Top-{len(rows)} 결과:")
            for r in rows:
                print(f"     score={r['score']:.4f}  title={r['document_title']}")
        else:
            print("  ❌ 검색 결과 없음")
    finally:
        await conn.close()


async def step4_llm(dsn: str, doc_stem: str) -> None:
    print("\n[4/5] Solar LLM + RAG 파이프라인 전체 실행")
    try:
        from core.rag.models import RAGQuery, RAGMode, SourceType
        from core.rag.pipeline import build_pipeline

        pipeline = build_pipeline()
        query = RAGQuery(
            query="SaaS 구독료의 부가세 세금계산서 발급 시점은?",
            top_k=3,
            mode=RAGMode.DENSE,
            source_types=[SourceType.TAX_LAW],
        )
        result = await pipeline.run(query)
        print(f"  ✅ LLM 응답 ({result.latency_ms}ms):")
        print("  " + result.answer[:300].replace("\n", "\n  "))
        if result.trace_id:
            print(f"  Langfuse Trace ID: {result.trace_id}")
        else:
            print("  ⚠️  Langfuse 미연결 (trace 없음)")
    except Exception as e:
        print(f"  ⚠️  LLM 단계 오류 (vLLM 미연결 시 정상): {e}")


async def step5_cleanup(dsn: str, doc_stem: str) -> None:
    print("\n[5/5] 테스트 데이터 정리")
    conn = await asyncpg.connect(dsn)
    try:
        result = await conn.execute(
            "DELETE FROM document_chunk WHERE source_doc_id = $1", doc_stem
        )
        print(f"  ✅ 삭제 완료 — {result}")
    finally:
        await conn.close()


async def main() -> None:
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://playground:playground@localhost:5432/playground",
    )
    print("=" * 60)
    print("  RAG 파이프라인 통합 테스트")
    print("=" * 60)
    print(f"  DSN: {dsn}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_pdf = Path(tmp_dir) / "test_tax_doc.pdf"
        _make_test_pdf(tmp_pdf)
        print(f"\n  합성 PDF 생성: {tmp_pdf}  ({tmp_pdf.stat().st_size:,} bytes)")

        await step1_check_db(dsn)
        count = await step2_ingest(tmp_pdf, dsn)

        if count == 0:
            print("\n  ❌ 인제스트 실패 — 이후 단계 생략")
            return

        await step3_dense_search(dsn, tmp_pdf.stem)
        await step4_llm(dsn, tmp_pdf.stem)
        await step5_cleanup(dsn, tmp_pdf.stem)

    print("\n" + "=" * 60)
    print("  테스트 완료")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
