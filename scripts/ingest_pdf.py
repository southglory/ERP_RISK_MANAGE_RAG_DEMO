"""PDF 문서 → pgvector 인제스트 스크립트.

사용법:
    python scripts/ingest_pdf.py <pdf_path> --source-type tax_law --title "부가가치세법"
    python scripts/ingest_pdf.py docs/ --source-type court --title "대법원 판례집"

source-type 선택: tax_law | court | ruling | contract | internal
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path

# 프로젝트 루트 sys.path 등록
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)

import pdfplumber

from core.providers.base import Document
from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider
from core.providers.vectorstore.factory import get_vector_store


# ── 청킹 파라미터 ─────────────────────────────────────────────────────────────
CHUNK_SIZE    = 800   # 문자 수 기준
CHUNK_OVERLAP = 100
BATCH_SIZE    = 16    # 임베딩 배치 크기


def _extract_text(pdf_path: Path) -> str:
    """pdfplumber로 전체 텍스트 추출. 표는 텍스트로 병합."""
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
            parts.append(text)
    return "\n".join(parts)


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    1차: 빈 줄 2개 이상(단락 경계)으로 분리
    2차: size 초과 단락은 슬라이딩 윈도우로 재분할
    """
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[str] = []
    buf = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 1 <= size:
            buf = (buf + "\n" + para).strip() if buf else para
        else:
            if buf:
                chunks.append(buf)
            # 단락 자체가 size 초과면 슬라이딩 윈도우
            if len(para) > size:
                for start in range(0, len(para), size - overlap):
                    chunks.append(para[start: start + size])
                buf = ""
            else:
                buf = para

    if buf:
        chunks.append(buf)

    return [c for c in chunks if len(c.strip()) >= 30]


def _chunk_id(source_doc_id: str, idx: int, content: str) -> str:
    h = hashlib.md5(content.encode()).hexdigest()[:8]
    return f"{source_doc_id}_{idx:04d}_{h}"


async def ingest(
    pdf_path: Path,
    source_type: str,
    document_title: str,
    dsn: str | None = None,   # 호환용 — backend-agnostic 화 이후 무시. factory 가 dsn 결정
) -> None:
    print(f"[ingest] {pdf_path.name}  source_type={source_type}")

    # 1. 텍스트 추출
    text = _extract_text(pdf_path)
    print(f"  텍스트 추출: {len(text):,} 문자")

    # 2. 청킹
    chunks = _chunk_text(text)
    print(f"  청크 분할: {len(chunks)}개 (avg {sum(len(c) for c in chunks)//len(chunks):,} 문자)")

    # 3. 임베딩 (배치)
    emb_provider = InfinityEmbeddingProvider()
    all_vecs: list[list[float]] = []
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i: i + BATCH_SIZE]
        vecs = await emb_provider.embed(batch)
        all_vecs.extend(vecs)
        print(f"  임베딩 {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)}", end="\r")
    print()

    # 4. VectorStore upsert — RAG_VECTOR_BACKEND 가 결정
    source_doc_id = pdf_path.stem.lower().replace(" ", "_")
    store = get_vector_store()
    try:
        inserted = 0
        for idx, (content, vec) in enumerate(zip(chunks, all_vecs)):
            cid = _chunk_id(source_doc_id, idx, content)
            await store.upsert(Document(
                chunk_id=cid,
                source_type=source_type,
                source_doc_id=source_doc_id,
                document_title=document_title,
                content=content,
                dense_vec=vec,
                sparse_tokens={},
                metadata={},
                span_start=idx * CHUNK_SIZE,
                span_end=(idx + 1) * CHUNK_SIZE,
            ))
            inserted += 1
        print(f"  store upsert: {inserted}건")
    finally:
        await store.close()

    print(f"[완료] {pdf_path.name}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="PDF → pgvector 인제스트")
    parser.add_argument("path", help="PDF 파일 또는 디렉토리")
    parser.add_argument("--source-type", required=True,
                        choices=["tax_law", "court", "ruling", "contract", "internal"])
    parser.add_argument("--title", default="", help="문서 제목 (document_title)")
    parser.add_argument("--dsn", default=os.environ.get(
        "DATABASE_URL", "postgresql://playground:playground@localhost:5432/playground"
    ))
    args = parser.parse_args()

    target = Path(args.path)
    if target.is_dir():
        pdfs = sorted(target.glob("**/*.pdf"))
    else:
        pdfs = [target]

    if not pdfs:
        print("PDF 파일을 찾을 수 없습니다.")
        sys.exit(1)

    for pdf in pdfs:
        title = args.title or pdf.stem
        await ingest(pdf, args.source_type, title, args.dsn)


if __name__ == "__main__":
    asyncio.run(main())
