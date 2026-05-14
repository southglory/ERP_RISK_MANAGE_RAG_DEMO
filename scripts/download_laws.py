"""한국 세무·법령 문서 다운로드 + 인제스트.

실행:
    python scripts/download_laws.py            # 합성 문서 즉시 생성
    python scripts/download_laws.py --real     # 법령정보 API 실제 다운로드 (LAW_API_KEY 필요)

법령정보 Open API 키 발급 (무료, 5분):
  1. https://open.law.go.kr/LSO/openApi/openApiInfo.do 접속
  2. '활용신청' → 이메일/IP 등록
  3. 발급받은 OC 코드를 .env에: LAW_API_KEY=your_oc_code
  4. python scripts/download_laws.py --real
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)

import hashlib
import io

import boto3
from botocore.client import Config
import httpx
import asyncpg

from core.providers.embedding.infinity_provider import InfinityEmbeddingProvider


# ── MinIO (S3-compatible) 클라이언트 ─────────────────────────────────────────

def _minio_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.environ.get("MINIO_ROOT_USER", "langfuse"),
        aws_secret_access_key=os.environ.get("MINIO_ROOT_PASSWORD", "langfuse_minio"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _upload_to_minio(client, source_type: str, filename: str, content: str) -> str:
    """MinIO laws 버킷에 업로드하고 object key를 반환."""
    bucket = "laws"
    key = f"{source_type}/{filename}"
    body = content.encode("utf-8")
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=io.BytesIO(body),
        ContentType="text/plain; charset=utf-8",
        ContentLength=len(body),
    )
    return key


# ── 다운로드 대상 법령 ────────────────────────────────────────────────────────
_LAW_TARGETS = [
    # ── 세무 핵심 ──────────────────────────────────────────────────────────────
    ("부가가치세법",               "tax_law",  ""),
    ("법인세법",                   "tax_law",  ""),
    ("소득세법",                   "tax_law",  ""),
    ("국세기본법",                 "tax_law",  ""),
    ("조세특례제한법",             "tax_law",  ""),
    ("국제조세조정에 관한 법률",   "tax_law",  ""),
    ("조세범 처벌법",              "tax_law",  ""),
    # ── 회계·공시 ──────────────────────────────────────────────────────────────
    ("주식회사 등의 외부감사에 관한 법률",  "tax_law",  ""),
    ("공인회계사법",               "tax_law",  ""),
    # ── 계약·거래 ──────────────────────────────────────────────────────────────
    ("상법",                       "contract", ""),
    ("하도급거래 공정화에 관한 법률", "contract", ""),
    ("전자문서 및 전자거래 기본법", "contract", ""),
    ("전자금융거래법",             "contract", ""),
    # ── 노무·급여 ──────────────────────────────────────────────────────────────
    ("근로기준법",                 "tax_law",  ""),
    ("최저임금법",                 "tax_law",  ""),
]

# ── 합성 법령 문서 (API 키 없이 즉시 인제스트용) ──────────────────────────────
_SYNTHETIC_DOCS = [
    {
        "source_type": "tax_law",
        "title": "부가가치세법 — 재화·용역 공급 시기",
        "content": """제15조(재화의 공급 시기)
재화가 공급되는 시기는 다음 각 호의 어느 하나에 해당하는 때로 한다.
1. 재화의 이동이 필요한 경우: 재화가 인도되는 때
2. 재화의 이동이 필요하지 아니한 경우: 재화가 이용 가능하게 되는 때
3. 제1호 및 제2호를 적용할 수 없는 경우: 재화의 공급이 확정되는 때

제16조(용역의 공급 시기)
용역이 공급되는 시기는 역무의 제공이 완료되는 때로 한다.
다만, 용역의 제공이 완료되기 전에 그 용역의 공급에 대한 대가를 받는 경우에는 그 받는 때를 공급 시기로 본다.

제17조(계속적 공급의 특례)
재화 또는 용역이 계속적으로 공급되는 경우에는 다음에 따른다.
1. 기간에 걸쳐 계속 공급: 대가의 각 부분을 받기로 한 때를 공급 시기로 함
2. 월정액 SaaS·구독 서비스: 해당 역무 제공 완료일(매월 말일)을 공급 시기로 함
3. 연간 선불 구독: 각 월 말일을 공급 시기로 안분하여 세금계산서 발급""",
    },
    {
        "source_type": "tax_law",
        "title": "부가가치세법 — 영세율 및 면세",
        "content": """제11조(영세율 적용 대상)
다음 각 호의 재화 또는 용역의 공급에 대하여는 영(零)의 세율을 적용한다.
1. 수출하는 재화
2. 국외에서 공급하는 용역
3. 선박 또는 항공기에 의한 외국항행 용역
4. 외국 사업자에게 공급하는 일정 용역

제26조(면세 대상)
다음 각 호의 재화 또는 용역의 공급에는 부가가치세를 면제한다.
1. 기초생활 필수 재화(가공되지 아니한 식료품, 수돗물 등)
2. 의료·교육 용역
3. 금융·보험 용역
4. 저술가·작곡가 등이 직접 제공하는 인적 용역 (단, 소프트웨어 개발 용역은 면세 아님)

소프트웨어 라이선스 및 SaaS 서비스는 과세 대상(세율 10%)이며,
해외 사업자에게 B2B로 공급 시 영세율 적용 가능.""",
    },
    {
        "source_type": "tax_law",
        "title": "법인세법 — 외국법인 원천징수",
        "content": """제93조(외국법인의 국내원천소득)
외국법인에 대한 법인세는 다음 각 호의 국내원천소득에 대하여 부과한다.
1. 이자소득: 국내에서 발생한 이자
2. 배당소득: 내국법인으로부터 받는 배당
3. 부동산소득: 국내 소재 부동산에서 생기는 소득
4. 선박·항공기 임대소득
5. 사업소득: 국내 사업장에 귀속되는 소득
6. 인적용역소득
7. 사용료소득(로열티): 국내에서 사용되는 특허권·저작권 등의 사용 대가

제98조(원천징수세율)
외국법인의 국내원천소득에 대한 원천징수세율:
- 이자소득: 20%
- 배당소득: 20%
- 사용료소득(로열티): 20%
- 사업소득(국내 사업장 없는 경우): 2%
- 인적용역소득: 20%

조세조약 체결국의 경우 조약상 제한세율 우선 적용.
적용 요건: 비거주자/외국법인 거주자증명서 원천징수의무자에게 사전 제출 필요.""",
    },
    {
        "source_type": "tax_law",
        "title": "조세조약 — 주요국 사용료 제한세율",
        "content": """주요국 조세조약상 사용료(로열티) 제한세율 (한국 기준):

미국: 일반 사용료 15%, 특수 조건(소프트웨어 저작권) 10%
일본: 10%
중국: 10%
독일: 10%
영국: 10%
아일랜드: 0% (소프트웨어 저작권 특례 요건 충족 시)
싱가포르: 5% (소프트웨어 라이선스)
네덜란드: 10%

조약 적용 요건:
1. 소득 수취자가 해당 조약 체결국의 거주자일 것
2. 소득 수취자가 국내에 고정사업장(PE)이 없을 것
3. 거주자증명서를 지급일 전에 원천징수의무자에게 제출할 것
4. 조세조약 수혜 신청서 제출 (일부 조약)

거주자증명서 미제출 시: 조약상 제한세율 적용 불가, 국내세법 기본세율(20%) 강제 적용.
지방소득세는 별도: 원천징수세액의 10% (예: 원천세 10% → 지방세 1%, 합계 11%).""",
    },
    {
        "source_type": "tax_law",
        "title": "국세기본법 — 가산세·경정청구",
        "content": """제47조의2(무신고 가산세)
납세의무자가 기한 내 세금계산서를 발급하지 아니한 경우:
공급가액의 2% 가산세 부과.
세금계산서 미교부·허위 교부 가산세: 공급가액의 2%.

제47조의3(납부지연 가산세)
납부기한 경과 후 납부 또는 환급 지연:
미납세액 × 경과일수 × 0.022% / 1일

제45조의2(경정청구)
과세표준 및 세액을 과다 신고한 경우:
신고기한으로부터 5년 이내 경정청구 가능.
원천징수세액 과다 납부 시에도 동일하게 경정청구 적용.

제81조의6(세무조사 사전통지)
세무조사 개시 15일 전까지 납세자에게 사전통지 원칙.
납세자 권리헌장: 세무조사 기간 연장·중복조사 제한.""",
    },
    {
        "source_type": "ruling",
        "title": "국세청 예규 — SaaS 구독 서비스 공급 시기",
        "content": """[부가가치세과-1234, 2022.08.15]

질의: 클라우드 SaaS 구독 서비스를 연간 선불로 수령한 경우 부가가치세 공급 시기

회신:
클라우드 기반 SaaS 구독 서비스는 「부가가치세법」 제16조에 따른 용역의 계속적 제공에 해당하며,
「부가가치세법 시행령」 제28조에 따라 대가의 각 부분을 받기로 한 때를 공급 시기로 한다.

연간 구독료를 일괄 선불 수령한 경우:
- 매월 말일을 각 월의 공급 시기로 보아 월별로 세금계산서를 발급하여야 함
- 또는 선불 수령 시 전체 금액에 대해 세금계산서 선발급 가능 (공급 시기 특례 적용)
- 선발급 시: 선발급일 기준 부가세 신고·납부 의무 발생

실무 권장: 연간 선불 계약 시 계약 시점에 연간 금액 전체로 세금계산서 발급,
이후 환불 발생 시 수정세금계산서 발급.""",
    },
    {
        "source_type": "ruling",
        "title": "국세청 예규 — 소프트웨어 라이선스 원천세",
        "content": """[국제조세과-567, 2023.03.20]

질의: 미국 법인으로부터 소프트웨어 라이선스 도입 시 원천세율

회신:
미국 법인이 국내 법인에게 소프트웨어 저작권 사용을 허락하고 받는 대가(로열티)에 대해:

1. 한·미 조세조약 제14조(사용료 조항) 적용:
   - 일반 사용료: 15%
   - 저작권 사용료(문학·예술·학술 저작물): 10%
   → 소프트웨어는 저작권법상 저작물에 해당하므로 10% 제한세율 적용

2. 적용 요건:
   - 미국 법인의 미국 거주자 증명서(Form 6166) 제출 필수
   - 국내 고정사업장 부재 확인
   - 원천징수의무자(국내 지급자)가 증명서 보관

3. 지방소득세: 원천징수세액의 10% (1% 추가)
   → 합계 실효세율: 11%

증명서 미제출 시 「법인세법」 제98조에 따라 20%(지방세 포함 22%) 적용.""",
    },
    {
        "source_type": "court",
        "title": "판례 — 소프트웨어 유지보수 위약금 (대법원)",
        "content": """대법원 2021다12345 판결 (2021.11.15)

[사건 개요]
ERP 유지보수 계약에서 공급자가 SLA 응답 시간을 반복적으로 위반하자
고객사가 계약 해지 및 위약금 청구.

[쟁점]
소프트웨어 유지보수 계약상 위약금 조항의 효력 및 감액 기준

[판시 사항]
1. 위약금의 효력: 당사자 간 합의한 위약금 조항은 원칙적으로 유효.
   다만 「민법」 제398조에 따라 법원은 부당히 과다한 위약금을 감액 가능.

2. 감액 기준: 채무 불이행의 경위, 실손해액, 위약금 비율의 상당성 종합 고려.
   통상 실손해액의 3배 초과 시 과다 인정 경향.

3. SLA 위반의 위약금 산정:
   - 반복적·체계적 SLA 위반: 계약 해지 사유 인정
   - 개별 SLA 위반 패널티: 당월 유지보수비의 5~20% 범위가 통상 적정
   - 계약서에 패널티 산식 명시 시 그에 따름

[결론]
계약상 위약금(공급대가의 30%)이 실손해(사업 지연 비용)의 4.2배에 달하여
「민법」 제398조 적용, 실손해의 2배 수준으로 감액 판결.""",
    },
    {
        "source_type": "court",
        "title": "판례 — 하도급 대금 지연이자 (서울고법)",
        "content": """서울고등법원 2022나98765 판결 (2022.09.08)

[사건 개요]
IT 시스템 구축 원도급사가 하도급 대금을 60일 초과 지연 지급.
하수급인이 지연이자 및 지급보증 위반 손해배상 청구.

[적용 법령]
「하도급거래 공정화에 관한 법률」(하도급법) 제13조·제13조의2

[판시 사항]
1. 지연이자율: 연 15.5% (공정거래위원회 고시 기준, 2023년 현재)
   하도급법은 일반 상사법정이율(연 6%)보다 높은 특별이율 적용.

2. 지급 기산일: 목적물 수령일로부터 60일이 경과한 날의 다음 날.
   전자세금계산서 수령일이 아닌 실제 납품 확인일 기준.

3. 지급보증 의무:
   하도급 계약금액 1억원 이상 시 지급보증 의무(하도급법 제13조의2).
   미이행 시 하도급 금액의 2% 범위 내 과징금.

[결론]
원도급사의 지연이자 및 지급보증 미이행에 따른 손해배상 청구 인용.
원도급사가 연 15.5%로 산정된 지연이자 및 보증비용 상당액 지급 의무.""",
    },
    {
        "source_type": "contract",
        "title": "소프트웨어 공급 계약 표준 조항 — 검수·인도",
        "content": """제7조(검수 및 인도)
① 공급자는 계약서에 정한 납기일까지 목적물을 인도하고, 발주자는 인도일로부터
   14일 이내에 검수를 완료하여야 한다.

② 발주자가 검수 기간 내 이의를 제기하지 아니하는 경우 검수를 완료한 것으로 본다.

③ 소프트웨어 인도 방법:
   - 온프레미스: 설치 완료 및 작동 확인 시점
   - SaaS: 접속 계정 제공 및 서비스 이용 가능 시점
   - 하이브리드: 온프레미스 모듈 설치 + SaaS 연동 완료 시점

제8조(하자보증)
① 인도일로부터 1년간 하자보증 의무.
② 하자의 범위: 계약상 명세를 충족하지 못하는 기능적 결함.
   성능 저하(SLA 미달): 별도 유지보수 계약에 따른 패널티 적용.

제9조(지식재산권)
① 맞춤형 개발 소프트웨어의 저작권: 계약으로 정한 당사자에 귀속.
② 별도 약정 없는 경우: 공급자에 귀속, 발주자에게 비독점 라이선스 부여.
③ 오픈소스 포함 시: 오픈소스 목록 및 라이선스 고지 의무.""",
    },
    {
        "source_type": "tax_law",
        "title": "K-IFRS 제1115호 — 수익 인식 5단계",
        "content": """K-IFRS 제1115호 '고객과의 계약에서 생기는 수익' 핵심 요약

[Step 1: 계약 식별]
다음 5가지 요건을 모두 충족하는 경우에만 계약으로 인식:
(1) 상업적 실질 존재
(2) 계약 승인 및 의무 이행 확약
(3) 권리·지급 조건 식별 가능
(4) 대가 회수 가능성 높음
(5) 각 당사자의 집행 가능한 권리 식별

[Step 2: 수행의무 식별]
계약 내 구별되는 재화·용역별로 분리:
- 하드웨어 + 설치 서비스: 하드웨어 단독 사용 불가 시 단일 수행의무
- 소프트웨어 + 유지보수: 별도 판매 가능하면 별개 수행의무
- SaaS 구독: 기간에 걸친 단일 수행의무

[Step 3: 거래가격 산정]
변동대가(할인·환불·성과 보너스), 유의적 금융요소, 비현금 대가 고려.

[Step 4: 거래가격 배분]
개별 판매가격(SSP, Standalone Selling Price) 비율로 배분.
SSP 관측 불가 시: 조정된 시장평가 접근법·예상원가 가산법 사용.

[Step 5: 수익 인식]
- 한 시점: 고객이 통제권 획득 시 (하드웨어 인도, 소프트웨어 라이선스 전달)
- 기간에 걸쳐: SaaS·유지보수·건설계약 등 (진행률 측정)

수익 인식 시 즉시 분개: 매출(4000) / 외상매출금(1100) + 부가세예수금(2130)
기간 인식 시: 계약부채(선수수익)(2120) → 매출(4000) 월할 대체""",
    },
    # ── K-IFRS 1115 조문별 상세 ──────────────────────────────────────────────
    {
        "source_type": "tax_law",
        "title": "K-IFRS 제1115호 제35조 — 기간에 걸쳐 이행하는 수행의무 (over-time)",
        "content": """K-IFRS 제1115호 제35조 기간에 걸쳐 이행하는 수행의무

수행의무는 다음 세 가지 기준 중 하나를 충족하면 기간에 걸쳐(over-time) 이행되는 것으로 본다.

(1) 고객이 기업의 수행에서 제공하는 효익을 동시에 받아 소비하는 경우
(2) 기업의 수행이 자산을 만들거나 가치를 높이고, 고객이 그 과정에서 해당 자산을 통제하는 경우
(3) 기업의 수행이 기업 자체에는 대체 용도가 없는 자산을 만들고, 완료한 수행 부분에 대한 집행 가능한 지급청구권이 있는 경우

기간에 걸쳐 이행되는 수행의무의 실무 예시:

SaaS 구독 서비스
- 기준 (1) 충족: 고객이 서비스를 매일 수령·소비
- 수익 인식 방법: 기간 안분(정액법)이 기본, 구독 기간에 걸쳐 월 단위 안분
- SaaS 월정액 구독: 1개월 경과 시마다 해당 월 구독료를 수익으로 인식
- 연간 선불 SaaS 계약: 계약부채(선수수익)로 인식 후 매월 1/12씩 매출 대체

유지보수·지원 서비스
- 기준 (1) 충족: 고객이 지원 가용성의 효익을 지속적으로 향유
- 수익 인식: 계약 기간 정액 안분
- 예: 1년 유지보수 12,000,000원 → 월 1,000,000원 수익

건설형 소프트웨어 프로젝트(기준 2 또는 3 해당 시)
- 투입법(시간·원가 기준) 또는 산출법(마일스톤·결과물 기준)으로 진행률 측정
- 진행률에 비례해 수익 인식

수익 인식 분개 (구독 기간 안분):
월 경과 시: (차) 계약부채 1,000,000 / (대) 매출 1,000,000""",
    },
    {
        "source_type": "tax_law",
        "title": "K-IFRS 제1115호 제38조 — 한 시점에 이행하는 수행의무 (point-in-time)",
        "content": """K-IFRS 제1115호 제38조 한 시점에 이행하는 수행의무

제35조의 기간 기준을 충족하지 못하는 수행의무는 한 시점(point-in-time)에 이행하는 것으로 본다.
고객이 해당 자산에 대한 통제권을 획득하는 시점에 수익을 인식한다.

통제권 이전 시점 판단 지표 (제38조 각호):
(1) 기업의 자산에 대한 현재 지급청구권 보유 여부
(2) 고객의 자산에 대한 법적 소유권 보유 여부
(3) 기업의 물리적 점유 이전 여부 — 인도 완료
(4) 자산의 소유에 따른 유의적 위험과 보상의 고객 이전 여부
(5) 고객의 자산 인수 여부 — 검수 완료

소프트웨어 라이선스 수익 인식:
- 기능성 라이선스(지적재산권 사용권, 특정 시점 기준): 고객에게 라이선스 키 전달(인도) 시 한 시점 수익 인식
- 상징적 라이선스(접속권 등): 기간에 걸쳐 인식

하드웨어 공급:
- 설치 및 검수 완료 시점에 수익 인식
- FOB 조건: 선적지 인도 기준이면 선적 시점에 통제권 이전

주요 실무 판단:
- 검수 조항이 형식적(확인 절차)인 경우: 인도 시점 수익 인식 가능
- 검수 조항이 실질적(성능 기준)인 경우: 검수 완료 시점까지 수익 인식 지연

분개 (한 시점 라이선스 판매):
인도 시: (차) 외상매출금 11,000,000 / (대) 매출 10,000,000 + 부가세예수금 1,000,000""",
    },
    {
        "source_type": "tax_law",
        "title": "K-IFRS 제1115호 제27조 — 수행의무 구별 기준 (번들 계약 HW+SaaS)",
        "content": """번들 계약(HW+SaaS, 소프트웨어+유지보수 등 결합 계약)에서 각 재화·용역을 별도의 수행의무로 분리할지 판단하는 기준이 제27조이다.

HW와 SaaS가 결합된 번들 계약의 수행의무 구별 기준:
제27조에 따라 두 가지 조건을 모두 충족하면 구별 가능(distinct)한 별개 수행의무로 분리한다.

재화·용역이 구별 가능(distinct)한 조건 (둘 다 충족):
(1) 고객이 해당 재화·용역 자체(또는 이용 가능한 다른 자원과 결합하여)에서 효익을 얻을 수 있음
(2) 계약 내 다른 약속과 별도로 식별 가능 (상호의존성·상호연관성이 유의적이지 않음)

구별되지 않는 경우 → 단일 수행의무로 통합:
- 소프트웨어 + 유의적인 커스터마이제이션: 별도로 사용 불가 → 통합
- 하드웨어 + 필수 설치: 설치 없이 사용 불가 → 통합

구별되는 경우 → 분리하여 수행의무 식별:
- ERP 소프트웨어 라이선스 + 독립적 유지보수 계약: 분리
  → 라이선스: 인도 시 수익 인식 (point-in-time)
  → 유지보수: 기간 안분 (over-time)
- 하드웨어 + 별도 교육 서비스: 분리
  → 각각 독립적으로 판매 가능하므로 분리

분리 실무:
Step 4(거래가격 배분)와 연동: 분리된 수행의무별로 SSP 비율에 따라 거래가격 배분.
예: 소프트웨어 라이선스 SSP 8,000,000원 + 1년 유지보수 SSP 2,000,000원
계약금액 9,000,000원 → 라이선스 7,200,000원 / 유지보수 1,800,000원으로 배분""",
    },
    {
        "source_type": "tax_law",
        "title": "K-IFRS 제1115호 제50조 — 변동대가",
        "content": """K-IFRS 제1115호 제50조 변동대가

거래가격에 변동금액이 포함되는 경우: 다음 중 더 잘 예측하는 방법으로 추정.

추정 방법:
(1) 기댓값(expected value): 가능한 대가의 범위에서 확률 가중 평균
    → 유사한 계약이 많고 다양한 결과가 있을 때 적합
(2) 가장 가능성이 높은 금액(most likely amount): 가능한 결과 중 가장 가능성 높은 단일 금액
    → 결과가 두 가지뿐일 때 적합 (달성/미달성)

변동대가 유형:
- 할인(Discount): 고객에게 제공하는 가격 할인 → 거래가격 차감
- 리베이트(Rebate): 일정 구매량 초과 시 소급 환급 → 기댓값으로 추정, 계약부채 적립
- 성과 보너스(Incentive): 납기·품질 목표 달성 시 추가 수령 → 수취 가능성 높을 때만 포함
- 환불 의무(Refund liability): 반품 예상분 → 환불부채 계상, 매출 차감

변동대가 포함 제약:
누적 인식 수익이 나중에 유의적으로 환원되지 않을 가능성이 매우 높은(highly probable) 금액까지만 거래가격 포함.

리베이트 실무 예시:
연간 구매 5억 초과 시 전체 구매액의 3% 소급 리베이트 약정:
- 1분기 누적 구매 1억: 연간 5억 달성 가능성 80% → 기댓값 0.8 × 3% × 예상 연간 5억 = 120만원 계약부채 적립
- 분개: (차) 매출 1,200,000 / (대) 환불부채 1,200,000""",
    },
    {
        "source_type": "tax_law",
        "title": "K-IFRS 제1115호 제73조 — 거래가격의 수행의무별 배분 (SSP)",
        "content": """K-IFRS 제1115호 제73조 거래가격의 배분

계약 내 복수의 수행의무에 거래가격 배분:
각 수행의무의 개별 판매가격(SSP, Standalone Selling Price) 비율에 따른다.

개별 판매가격(SSP) 추정 방법 (관측 불가 시):
(1) 조정된 시장평가 접근법: 시장에서의 예상 판매가격 추정
(2) 예상원가 가산법: 원가 + 적정 마진
(3) 잔여 접근법: 관측 가능한 SSP의 합을 총 거래가격에서 차감 (특수 상황만)

거래가격 배분 계산:
수행의무 A의 배분액 = 거래가격 × (SSP_A / (SSP_A + SSP_B + ...))

실무 예시 (ERP + 유지보수 번들):
- ERP 소프트웨어 라이선스 SSP: 12,000,000원
- 1년 유지보수 서비스 SSP: 3,000,000원
- 번들 계약 거래가격: 13,500,000원 (할인 적용)

비율: ERP = 12/15 = 80%, 유지보수 = 3/15 = 20%
배분: ERP = 13,500,000 × 80% = 10,800,000원
     유지보수 = 13,500,000 × 20% = 2,700,000원

수익 인식:
- ERP 10,800,000원: 인도·검수 시점에 한 시점 인식
- 유지보수 2,700,000원: 12개월 기간 안분 → 월 225,000원

제73조는 SSP가 계약별로 달라지지 않도록 일관된 방법론 적용 의무화.
가격 목록(price list) 없는 소프트웨어 회사: 유사 거래의 평균 판매가를 SSP 추정치로 사용.""",
    },
    {
        "source_type": "tax_law",
        "title": "K-IFRS 제1115호 B34-B38 — 본인-대리인 구별 (총액/순액 인식)",
        "content": """K-IFRS 제1115호 B34-B38 본인과 대리인의 구별 — 총액·순액 수익 인식

수익 인식의 핵심 차이:
- 본인(Principal): 총액(Gross) 인식 — 고객으로부터 받는 전체 대가를 매출로 인식
- 대리인(Agent): 순액(Net) 인식 — 수수료(총액 - 원공급자 지급액)만 수익으로 인식

본인 판단의 3대 지표 (B37):
① 주된 책임(Primary Responsibility): 재화·용역을 고객에게 제공할 주된 책임을 기업이 짐
② 재고 위험(Inventory Risk): 인도 전·반품 후 재고 손실 위험 부담
③ 가격 결정 재량(Pricing Discretion): 판매가격을 기업이 자유롭게 결정 가능

대리인 판단 지표 (B38):
- 타 당사자가 공급하는 재화·용역을 고객에게 연결·주선(Arrange)만 함
- 수수료(Commission)만 수취, 재고 위험 없음

핵심 판단 기준 — 통제권:
고객에게 재화·용역이 이전되기 전에 기업이 해당 재화·용역을 통제하면 → 본인
통제하지 않고 타 당사자의 공급을 주선(Arrange)만 하면 → 대리인

실무 예시 (소프트웨어 리셀러):
총액 방식: (차) 외상매출금 10,000,000 / (대) 매출 10,000,000 + (차) 매출원가 7,000,000 / (대) 매입채무 7,000,000
순액 방식: (차) 외상매출금 3,000,000 / (대) 수수료수익 3,000,000

판단 시 핵심 질문: "재화·용역에 하자가 생기면 누가 책임지는가?"
→ 기업이 책임지면 본인, 원공급자가 책임지면 대리인.""",
    },
    {
        "source_type": "tax_law",
        "title": "K-IFRS 제1115호 제18조 — 계약 수정",
        "content": """K-IFRS 제1115호 제18조 계약 수정

계약 수정(Contract Modification): 계약 범위·가격 변경에 대한 당사자 간 합의

계약 수정의 회계처리 방법 3가지:

(1) 별도 계약으로 처리 — 두 조건 모두 충족:
  - 추가되는 재화·용역이 기존 계약과 구별 가능(distinct)
  - 추가 대가가 해당 재화·용역의 SSP를 반영
  → 원 계약과 무관하게 신규 계약으로 독립 처리

(2) 기존 계약의 취소 + 신규 계약 체결로 처리 — 잔여 수행의무에 유의적 영향:
  - 미이행 수행의무가 기존 것과 구별되는 경우
  → 수정 시점의 새 거래가격을 잔여 수행의무에 재배분 (누적 효과 조정 없음)
  → 기존 인식 수익 변경 없이 향후에만 적용

(3) 기존 계약의 일부로 처리 — 미이행 수행의무가 구별되지 않는 경우:
  - 재화·용역이 단일 수행의무의 일부인 경우
  → 수정 시점에 누적 효과(Cumulative Catch-up)를 일시 인식
  → 변경된 거래가격으로 재계산한 누적 수익 - 이미 인식한 수익 = 당기 수익 증감

실무 예시 (건설형 소프트웨어 추가 기능 수정):
진행 중인 프로젝트에 추가 기능 범위 확대, SSP 미만 가격으로 추가:
→ (3) 방법 적용: 누적 효과 일시 인식 (Catch-up 분개)
(차) 외상매출금 XX / (대) 매출 XX — 누적 조정분""",
    },
    # ── 계약 / 민법 / 노무 보완 ──────────────────────────────────────────────────
    {
        "source_type": "contract",
        "title": "민법 제544조 — 채무불이행과 계약 해제·해지",
        "content": """민법 제544조(이행지체와 해제)
당사자 일방이 그 채무를 이행하지 아니하는 때에는 상대방은 상당한 기간을 정하여 그 이행을 최고하고
그 기간 내에 이행하지 아니한 때에는 계약을 해제할 수 있다.

최고(催告): 계약 해제 전에 이행을 촉구하는 통지. 상당한 기간을 정하여 서면으로 하는 것이 원칙.
채무불이행: 이행지체, 이행불능, 불완전이행 모두 포함.

계속적 계약에서의 해지 (IT 서비스·SaaS·유지보수 계약):
- 계속적 계약(계속적 급부를 목적으로 하는 계약)은 해제가 아니라 해지(解止) 방식 적용.
- 해지는 장래에 대해서만 효력이 생기며, 이미 이행된 부분은 소급하여 무효가 되지 않음.
- 일반 원칙: 채무불이행 → 최고 → 기간 내 미이행 → 해지 가능.
- 중대한 채무불이행(예: SLA 위반이 반복적·본질적): 최고 없이 즉시 해지 가능.

즉시 해지 사유 (민법 제544조 단서 및 판례):
- 이행불능 상태가 명확한 경우
- 서비스 중단 기간이 계약의 목적을 달성할 수 없게 하는 경우
- 상대방이 이행 거부 의사를 명백히 표시한 경우

손해배상:
해지 후 손해배상 청구 가능 (민법 제551조).
계약서상 위약금 조항이 있으면 그에 따르며, 부당히 과다한 경우 법원이 감액 가능 (민법 제398조 제2항).""",
    },
    {
        "source_type": "tax_law",
        "title": "최저임금법 제28조 — 최저임금 위반 벌칙 및 2026년 최저임금",
        "content": """최저임금법 제28조(벌칙)
최저임금액보다 적은 임금을 지급하거나 최저임금을 이유로 종전의 임금을 낮춘 자는
3년 이하의 징역 또는 2천만원 이하의 벌금에 처한다.
징역과 벌금은 이를 병과(倂科)할 수 있다.

2026년 최저임금 (고용노동부 고시):
시간급 최저임금: 10,030원

월 환산 기준 (소정근로시간 209시간):
  월 최저임금 = 10,030원 × 209시간 = 2,096,270원

주 40시간제 사업장 기준 (주휴시간 포함):
  1일 8시간 × 5일 + 주휴 8시간 = 48시간 → 월 209시간

위반 유형:
1. 최저임금 미달 지급: 시간급 10,030원 미만 지급
2. 상여금·복리후생비 일부는 최저임금 산입 범위 적용
3. 수습 근로자: 1년 미만 계약이 아닌 경우 수습 3개월 내 10% 감액 가능 (최저임금법 제5조)

사용자의 의무:
- 최저임금 주지 의무: 사업장 게시 또는 근로자에게 교부
- 미준수 시 근로감독관 진정 → 과태료 또는 형사처벌""",
    },
    {
        "source_type": "contract",
        "title": "전자상거래법 제17조 — 청약철회권 및 행사 기간",
        "content": """전자상거래등에서의소비자보호에관한법률 제17조(청약철회등)

핵심 요약:
소비자는 재화 수령일(또는 계약서 수령일) 로부터 7일 이내에 청약을 철회할 수 있다.
전자상거래 제17조 청약철회권 행사 기간 = 7일.

① 소비자는 다음 각 호의 기간(거래당사자가 더 긴 기간을 정한 경우에는 그 기간) 이내에 청약을 철회할 수 있다.
  1. 계약서를 받은 날: 7일. 다만 공급이 계약서 수령 뒤 이루어진 경우에는 재화를 공급받거나 용역 공급이 시작된 날로부터 7일.
  2. 계약서를 받지 못한 경우, 통신판매업자의 주소 등이 없는 경우, 변경된 경우: 주소를 안 날 또는 알 수 있었던 날로부터 7일.

② 다음 각 호에 해당하는 경우 소비자는 청약을 철회할 수 없다.
  1. 소비자에게 책임 있는 사유로 재화 등이 분실·훼손된 경우
  2. 소비자의 사용 또는 일부 소비로 재화 등의 가치가 현저히 감소한 경우
  3. 시간이 지나 재판매가 곤란할 정도로 재화 등의 가치가 현저히 감소한 경우
  4. 복제 가능한 재화 등의 포장을 훼손한 경우
  5. 용역 또는 디지털콘텐츠(소프트웨어 다운로드·설치 완료 포함)의 제공이 개시된 경우

소프트웨어·디지털콘텐츠 관련:
- 소프트웨어 다운로드 또는 설치가 이미 완료된 경우: 청약철회 불가
- 단, 다운로드·설치 전에 소비자가 청약철회 불가 사유에 동의하지 않은 경우: 철회 가능
- ERP·SaaS 계정 활성화 후 이용 개시 시점부터 철회 불가로 볼 수 있음

위반 시 제재:
- 정당한 철회를 방해한 사업자: 과태료 1,000만원 이하 (제45조)
- 환급 지연 시 환급 금액에 연 15% 지연이자 부과""",
    },
    {
        "source_type": "contract",
        "title": "상법 제397조 — 이사의 경업금지 의무",
        "content": """상법 제397조(경업금지)
① 이사는 이사회의 승인이 없으면 자기 또는 제3자의 계산으로 회사의 영업 부류에 속한 거래를 하지 못하며
   동종 영업을 목적으로 하는 다른 회사의 무한책임사원 또는 이사가 되지 못한다.
② 이사가 전항의 규정에 위반하여 거래를 한 때에는 회사는 이사회의 결의로 그 거래가 회사를 위하여 한 것으로 볼 수 있다.
③ 전항의 경우에 그 이사의 개입권은 이사회가 그 거래를 안 날로부터 2주간, 그 거래가 있은 날로부터 1년을 경과하면 소멸한다.

경업 금지 의무의 범위:
- "회사의 영업 부류에 속한 거래": 회사가 현재 영위하는 사업과 동종 또는 유사한 거래
- 이사회의 승인: 이사 전원 과반수 출석, 출석 이사 과반수 찬성으로 의결
- 직접 거래 및 제3자 명의 거래 모두 포함

위반 시 제재:
1. 회사가 해당 거래를 회사 계산으로 귀속시킬 수 있음 (개입권)
2. 손해배상 청구: 이사에게 손해 발생 시 손해배상 청구 가능 (상법 제399조)
3. 이사해임 사유: 중대한 법령 위반으로 해임 청구 가능 (상법 제385조)

ERP 관련 실무:
- IT 서비스 회사 이사가 동종 SI 사업을 별도 법인으로 영위: 경업 금지 위반
- 이사회 사전 승인 없이 회사 고객에게 직접 영업: 위반
- 이사회의 승인을 받은 경우: 적법 (의사록 보존 필수)""",
    },
    # ── 내부감사 — 부정 탐지 가이드라인 ────────────────────────────────────────
    {
        "source_type": "internal",
        "title": "내부감사 부정탐지 — 벤포드 법칙 분석",
        "content": """내부감사 부정탐지 기법: 벤포드 법칙(Benford's Law) 분석

개요:
자연 발생 숫자 집합에서 첫째 자리(Leading Digit) 분포는 균등하지 않고 편향된다.
d로 시작하는 숫자의 예상 빈도: P(d) = log10(1 + 1/d)

이론적 벤포드 분포 (첫째 자리별):
1: 30.10%, 2: 17.61%, 3: 12.49%, 4: 9.69%
5: 7.92%, 6: 6.69%, 7: 5.80%, 8: 5.12%, 9: 4.58%

특히 1로 시작하는 숫자 비율이 가장 높고, 9는 가장 낮다.
2로 시작하는 숫자의 이론치는 17.61%(약 17.6%), 흔히 20.09%와 대비.
(주: 첫째 자리 1·2 합계 = 30.10 + 17.61 = 47.71%)

적용 대상 데이터:
- 거래 금액(매입, 매출, 비용)
- 급여, 출장 경비
- 세금계산서 금액

이상 감지 방법 — 카이제곱(Chi-squared) 검정:
귀무가설: 실제 분포 = 벤포드 이론 분포
카이제곱 통계량 = Σ [(관측 - 기대)² / 기대] (자유도 8)
유의수준 5%: 임계값 15.507
통계량 > 임계값 → 분포 이탈 → 추가 감사 필요

실무 해석:
- 특정 첫째 자리 비율 과대: 해당 금액대 집중 입력 의심 (예: 결재 한도 직전 금액)
- 9로 시작하는 비율 과대: 9,xxx 원 집중 → 한도 분할 패턴
- 5로 시작하는 비율 과대: 5,000원 라운드 넘버 집중

Python 예시:
  expected = {1: 0.301, 2: 0.176, 3: 0.125, ...}
  chi2 = sum((obs-exp)**2/exp for obs, exp in zip(observed, expected.values()))""",
    },
    {
        "source_type": "internal",
        "title": "내부감사 부정탐지 — 결재 한도 분할 거래",
        "content": """내부감사 부정탐지 기법: 결재 한도 분할(Split Transaction) 감지

개념:
결재 권한 임계금액 바로 아래로 거래를 분할해 상위 결재를 회피하는 부정 유형.
예: 팀장 결재 한도 500,000원 → 490,000원 + 490,000원으로 2건 처리.

탐지 쿼리 패턴:
동일 벤더·동일 날짜·금액 합산이 결재 한도의 1.5배 이상이면서
개별 건이 모두 한도 미만인 경우를 조회.

```sql
SELECT vendor_id, DATE(transaction_date) AS tdate,
       COUNT(*) AS cnt, SUM(amount) AS total
FROM   transactions
GROUP  BY vendor_id, DATE(transaction_date)
HAVING COUNT(*) >= 2
   AND SUM(amount) > :limit * 1.5
   AND MAX(amount) < :limit;
```

위험 지표:
- 동일 직원이 동일 날짜·동일 벤더에 복수 건 입력
- 건당 금액이 결재 한도의 90~99% 구간에 집중
- 특정 금액대(예: 490,000원, 990,000원)에 빈도 이상

결재 권한(Authorization Limit) 체계:
- 팀원: 100,000원 이하 자기결재
- 팀장: 500,000원 이하
- 부서장: 2,000,000원 이하
- 임원: 10,000,000원 이하

통제 방안:
- 동일 벤더·동일 날짜 복수 건 자동 플래그
- 월간 누적 집중 모니터링
- 거래 분할 여부 결재자 확인 필드 추가""",
    },
    {
        "source_type": "internal",
        "title": "내부감사 부정탐지 — 라운드 넘버 이상",
        "content": """내부감사 부정탐지 기법: 라운드 넘버(Round Number) 이상 감지

개념:
실제 거래는 임의 금액(예: 47,300원, 182,500원)이 정상.
부정·오류 거래는 1,000원·10,000원·100,000원 단위의 라운드 넘버(끝자리 0 집중)로 나타나는 경향.

이론적 기대치:
무작위 금액에서 끝자리 0 비율: 약 10-11%
1,000원 단위(끝자리 세 자리가 000): 약 1%
실제 관측 비율이 40% 이상이면 유의한 이상치로 판단.

탐지 방법:
1. 끝자리 0 비율 계산:
   round_pct = COUNT(amount % 1000 = 0) / COUNT(*) × 100
   → 40% 초과 시 라운드 넘버 집중 경보

2. 특정 금액 빈도 분석:
   자주 등장하는 금액 Top 10 추출
   동일 금액이 전체 건수의 5% 이상: 이상

3. 끝자리 분포 검정:
   끝자리(0-9) 분포 카이제곱 검정
   균등분포(10%) 대비 유의한 편차 탐지

실무 기준:
- 경비 청구에서 1,000원 단위 금액 비율 > 40%: 감사 대상
- 동일 금액이 3회 이상 반복: 고정 허위 청구 의심
- 10,000원 이하 소액에서 9,000원·8,000원 집중: 한도 미만 분산 의심

벤포드 법칙과 병행:
라운드 넘버 이상은 벤포드 분석에서 특정 첫째 자리 과다로도 나타남.
두 분석을 교차 검증하면 탐지 정확도 향상.""",
    },
    {
        "source_type": "internal",
        "title": "내부감사 부정탐지 — 중복 거래 감지",
        "content": """내부감사 부정탐지 기법: 중복 거래(Duplicate Transaction) 감지

개념:
동일한 거래를 두 번 이상 처리해 이중 지급하거나 수익을 과대 계상하는 부정 유형.
주요 유형:
- 동일 세금계산서 번호 복수 처리
- 동일 금액·동일 벤더·동일 날짜 복수 건
- 유사 금액·유사 날짜(±1~3일)·동일 벤더

탐지 SQL:
```sql
-- 완전 중복: 동일 금액 + 동일 벤더 + 동일 날짜
SELECT vendor_id, amount, DATE(transaction_date) AS tdate, COUNT(*) AS dup_cnt
FROM   ap_transactions
GROUP  BY vendor_id, amount, DATE(transaction_date)
HAVING COUNT(*) >= 2;

-- 유사 중복: 동일 금액 + 동일 벤더 + 날짜 ±3일
SELECT a.txn_id, b.txn_id AS dup_txn_id, a.vendor_id, a.amount
FROM   ap_transactions a
JOIN   ap_transactions b
  ON   a.vendor_id = b.vendor_id
  AND  a.amount    = b.amount
  AND  ABS(EXTRACT(DAY FROM a.transaction_date - b.transaction_date)) <= 3
  AND  a.txn_id < b.txn_id;
```

위험 지표:
- 동일 세금계산서 번호 2회 이상 입력
- 동일 금액 · 동일 벤더 · 동일 날짜 복수 건
- 역분개(Reversal) 없이 동일 거래 재처리

통제 방안:
- ERP에서 세금계산서 번호 중복 방지 로직 구현
- AP 입력 시 자동 중복 스캔 후 경고 표시
- 월 마감 전 중복 거래 보고서 정기 발행""",
    },
    {
        "source_type": "internal",
        "title": "내부감사 부정탐지 — 비업무시간대 거래",
        "content": """내부감사 부정탐지 기법: 비업무시간대(Off-hours) 거래 감지

탐지 기준 (핵심):
- 새벽 시간 00:00~06:00 거래: 자동화 스크립트 또는 접근 권한 오용 의심 → 즉시 MEDIUM 이상 경보
- 업무 전후(06:00~08:59, 18:01~23:59) 고액 거래: 내부 통제 우회 가능성
- 주말·공휴일 수동 입력 거래: 승인 체계 이탈 위험

개념:
정상 업무 시간(09:00~18:00, 평일)을 벗어난 새벽·주말·공휴일 거래는 내부 통제가 취약한 시간대로, 부정 거래 위험이 높다.

비업무시간대 정의:
- 새벽 시간: 00:00~06:00 (심야 무인 입력)
- 업무 전: 06:00~08:59 (사전 조작 가능)
- 업무 후: 18:01~23:59
- 주말·공휴일: 토요일, 일요일, 법정 공휴일

탐지 SQL:
```sql
SELECT txn_id, created_by, amount,
       transaction_datetime,
       EXTRACT(HOUR FROM transaction_datetime) AS txn_hour,
       EXTRACT(DOW FROM transaction_datetime)  AS day_of_week
FROM   transactions
WHERE  EXTRACT(HOUR FROM transaction_datetime) BETWEEN 0 AND 5  -- 00:00~05:59
   OR  EXTRACT(DOW FROM transaction_datetime) IN (0, 6);        -- 일요일=0, 토요일=6
```

위험 지표:
- 00:00~06:00 구간 거래: 자동화 스크립트 또는 접근 권한 오용 의심
- 특정 사용자가 주말에만 고액 거래 집중
- 비업무시간 로그인 IP가 평소와 다른 경우 (위치 이상)

내부 통제 강화 방안:
- 비업무시간대 고액 거래(예: 1,000,000원 이상) 자동 보류 + 다음 업무일 상위 결재
- 비업무시간 로그인 알림 발송 (이메일/SMS)
- 비업무시간대 거래 비율 KPI로 모니터링 (목표: 전체 거래의 5% 미만)""",
    },
    {
        "source_type": "internal",
        "title": "내부감사 부정탐지 — 거래 속도 이상(Velocity) 감지",
        "content": """내부감사 부정탐지 기법: 거래 속도(Velocity) 이상 감지

개념:
단기간 내 동일 벤더·계정·사용자에 대한 거래 건수 또는 금액이 비정상적으로 급증하는 패턴.
분기말·월말에 집중되는 속도 이상은 기간귀속(Period-cut-off) 오류 또는 부정의 신호.

탐지 지표:
1. 기간별 건수 비교:
   이전 동기 대비 2배 이상 증가 → 이상 경보
   예: 1분기 월평균 거래 건수 50건 → 2분기 3월 100건 이상 → 속도 이상

2. 분기말 집중도:
   분기 마지막 2주(15일)에 분기 전체 거래의 50% 이상 집중 → 기간귀속 위험
   특히 매입·비용 거래의 분기말 집중: 이익 조정 의심

3. 특정 사용자 속도:
   동일 사용자가 1시간 내 10건 이상 입력 → 일괄 조작 의심

탐지 SQL (분기말 집중 분석):
```sql
SELECT vendor_id,
       SUM(CASE WHEN transaction_date >= DATE_TRUNC('quarter', CURRENT_DATE) + INTERVAL '75 days'
                THEN amount ELSE 0 END) AS last_2weeks_amt,
       SUM(amount) AS quarter_total_amt,
       ROUND(100.0 * SUM(CASE WHEN transaction_date >= DATE_TRUNC('quarter', CURRENT_DATE) + INTERVAL '75 days'
                              THEN amount ELSE 0 END) / NULLIF(SUM(amount), 0), 1) AS last2w_pct
FROM   transactions
WHERE  transaction_date >= DATE_TRUNC('quarter', CURRENT_DATE)
GROUP  BY vendor_id
HAVING ROUND(100.0 * SUM(CASE WHEN transaction_date >= DATE_TRUNC('quarter', CURRENT_DATE) + INTERVAL '75 days'
                               THEN amount ELSE 0 END) / NULLIF(SUM(amount), 0), 1) > 50;
```

통제 방안:
- 분기말 2주 거래 자동 플래그 및 추가 검토
- 전기 동기 대비 2배 증가 시 부서장 확인 의무화""",
    },
    {
        "source_type": "internal",
        "title": "내부감사 부정탐지 — 분기말 기간귀속 오류",
        "content": """내부감사 부정탐지 기법: 분기말 기간귀속(Period Cut-off) 오류 감지

개념:
기간귀속이란 수익·비용을 올바른 회계 기간에 인식하는 원칙(발생주의).
분기말에 다음 기간의 매출을 앞당기거나 이번 기간의 비용을 다음 기간으로 미루는 조작이 가능.

주요 패턴:
1. 가공매입 기간귀속 오류:
   - 분기 마감일(3월 31일, 6월 30일 등) 기준 마지막 2주 내 매입 집중
   - 실제 납품 없이 세금계산서만 수령 → 비용 과대 계상
   - 다음 분기 초에 역분개(취소)하는 패턴 → '수정 거래' 증가

2. 매출 조기 인식:
   - 납기일 전에 인도 처리하여 매출 인식
   - 검수 완료 전 청구서 발행

위험 신호:
- 분기 마지막 2주에 전체 분기 매입의 50% 이상 집중
- 분기말 입력 거래 중 다음 분기 초 7일 내 수정(역분개) 비율 > 20%
- 동일 벤더에서 분기말마다 반복적 고액 청구

탐지 SQL (수정 거래 비율):
```sql
SELECT t.vendor_id, t.amount, t.transaction_date,
       r.reversal_date, r.reversal_amount
FROM   transactions t
LEFT JOIN reversals r ON t.txn_id = r.original_txn_id
WHERE  t.transaction_date >= DATE_TRUNC('quarter', t.transaction_date) + INTERVAL '75 days'
  AND  r.reversal_date <= DATE_TRUNC('quarter', t.transaction_date) + INTERVAL '3 months' + INTERVAL '7 days';
```

감사 절차:
1. 분기말 2주 매입 목록 추출
2. 납품 확인서(물품 수령증) 현물 대사
3. 다음 분기 초 수정 거래 일치 여부 확인""",
    },
]

CHUNK_SIZE    = 800
CHUNK_OVERLAP = 100
BATCH_SIZE    = 8

_DATA_DIR = _ROOT / "data" / "laws"


def _safe_filename(title: str) -> str:
    import re
    return re.sub(r'[\\/:*?"<>|]', "_", title)[:80]


def _save_txt(source_type: str, title: str, content: str) -> Path:
    folder = _DATA_DIR / source_type
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_safe_filename(title)}.txt"
    path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
    return path


def _chunk_text(text: str) -> list[str]:
    import re
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) + 1 <= CHUNK_SIZE:
            buf = (buf + "\n" + p).strip() if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p if len(p) <= CHUNK_SIZE else p[:CHUNK_SIZE]
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) >= 30]


def _chunk_id(title: str, idx: int, content: str) -> str:
    h = hashlib.md5(content.encode()).hexdigest()[:8]
    slug = title[:20].replace(" ", "_")
    return f"synth_{slug}_{idx:03d}_{h}"


async def _ingest_doc(
    conn, emb, minio_cli,
    source_type: str, title: str, content: str, origin: str,
) -> int:
    """단일 문서: 로컬 저장 → MinIO 업로드 → document_chunk 인제스트 → documents upsert."""
    saved = _save_txt(source_type, title, content)
    filename = saved.name
    file_bytes = saved.read_bytes()

    # MinIO 업로드
    storage_path = _upload_to_minio(minio_cli, source_type, filename, content)

    # 청킹 + 임베딩
    chunks = _chunk_text(content)
    vecs = await emb.embed(chunks)
    doc_id = _chunk_id(title, 0, title)
    new = 0
    for idx, (chunk_content, vec) in enumerate(zip(chunks, vecs)):
        cid = _chunk_id(title, idx, chunk_content)
        vec_str = "[" + ",".join(str(v) for v in vec) + "]"
        result = await conn.execute(
            """INSERT INTO document_chunk
                 (chunk_id, source_type, source_doc_id, document_title,
                  content, span_start, span_end, dense_vec)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8::vector)
               ON CONFLICT (chunk_id) DO NOTHING""",
            cid, source_type, doc_id, title,
            chunk_content, idx * CHUNK_SIZE, (idx + 1) * CHUNK_SIZE, vec_str,
        )
        if result == "INSERT 0 1":
            new += 1

    # documents 메타데이터 upsert
    await conn.execute(
        """INSERT INTO documents
             (doc_id, title, source_type, origin, file_format,
              storage_path, file_size_bytes, chunk_count, ingested_at)
           VALUES ($1,$2,$3,$4,'txt',$5,$6,$7,now())
           ON CONFLICT (doc_id) DO UPDATE SET
             chunk_count   = EXCLUDED.chunk_count,
             ingested_at   = EXCLUDED.ingested_at,
             storage_path  = EXCLUDED.storage_path""",
        doc_id, title, source_type, origin,
        storage_path, len(file_bytes), len(chunks),
    )
    return new


async def ingest_synthetic(dsn: str) -> None:
    print("\n[합성 문서 인제스트]")
    emb = InfinityEmbeddingProvider()
    minio_cli = _minio_client()
    conn = await asyncpg.connect(dsn)

    try:
        await conn.execute(
            "ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS document_title TEXT NOT NULL DEFAULT ''"
        )
        await _ensure_documents_table(conn)

        total_new = 0
        for doc in _SYNTHETIC_DOCS:
            new = await _ingest_doc(
                conn, emb, minio_cli,
                doc["source_type"], doc["title"], doc["content"], "synthetic",
            )
            total_new += new
            print(f"  {doc['title'][:40]:<42} {new}청크")

        print(f"\n  합계: {len(_SYNTHETIC_DOCS)}문서 / 신규 {total_new}청크 저장")
    finally:
        await conn.close()


async def _ensure_documents_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
          doc_id          TEXT PRIMARY KEY,
          title           TEXT NOT NULL,
          source_type     TEXT NOT NULL,
          origin          TEXT NOT NULL DEFAULT 'synthetic',
          file_format     TEXT NOT NULL DEFAULT 'txt',
          storage_path    TEXT NOT NULL,
          file_size_bytes BIGINT,
          chunk_count     INT NOT NULL DEFAULT 0,
          ingested_at     TIMESTAMPTZ,
          created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


async def ingest_real(dsn: str, oc_key: str) -> None:
    """법령정보 Open API로 실제 법령 다운로드 + 인제스트."""
    print("\n[실제 법령 다운로드 — 법령정보 Open API]")
    emb = InfinityEmbeddingProvider()
    minio_cli = _minio_client()
    conn = await asyncpg.connect(dsn)

    await conn.execute(
        "ALTER TABLE document_chunk ADD COLUMN IF NOT EXISTS document_title TEXT NOT NULL DEFAULT ''"
    )
    await _ensure_documents_table(conn)

    async with httpx.AsyncClient(timeout=30) as client:
        for law_name, source_type, _ in _LAW_TARGETS:
            print(f"  검색 중: {law_name}")
            try:
                # 1. 법령 일련번호(MST) 조회
                r = await client.get(
                    "https://www.law.go.kr/DRF/lawSearch.do",
                    params={"OC": oc_key, "query": law_name, "target": "law",
                            "type": "JSON", "display": "1", "page": "1"},
                )
                data = r.json()
                laws = data.get("LawSearch", {}).get("law", [])
                if not laws:
                    print(f"    검색 결과 없음: {law_name}")
                    continue
                if isinstance(laws, dict):
                    laws = [laws]
                mst = laws[0].get("법령일련번호", "")
                if not mst:
                    print(f"    MST 코드 없음: {law_name}")
                    continue

                # 2. 법령 XML 본문 다운로드
                r2 = await client.get(
                    "https://www.law.go.kr/DRF/lawService.do",
                    params={"OC": oc_key, "target": "law", "MST": mst, "type": "XML"},
                )
                root = ET.fromstring(r2.content.decode("utf-8", errors="replace"))

                # 3. 조문 추출
                articles: list[str] = []
                for jo in root.iter("조문단위"):
                    num   = jo.findtext("조문번호", "")
                    title = jo.findtext("조문제목", "")
                    body  = jo.findtext("조문내용", "")
                    if body and body.strip():
                        header = f"제{num}조({title})" if title else f"제{num}조"
                        articles.append(f"{header}\n{body.strip()}")

                text = "\n\n".join(articles)
                if not text:
                    print(f"    본문 추출 실패: {law_name}")
                    continue

                # 4. 저장 + 인제스트
                new = await _ingest_doc(
                    conn, emb, minio_cli, source_type, law_name, text, "law_api",
                )
                print(f"    {law_name}: 신규 {new}청크")

            except Exception as e:
                print(f"    오류 ({law_name}): {e}")

    await conn.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true",
                        help="법령정보 Open API로 실제 법령 다운로드 (LAW_API_KEY 필요)")
    parser.add_argument("--dsn", default=os.environ.get(
        "DATABASE_URL", "postgresql://playground:playground@localhost:5432/playground"))
    args = parser.parse_args()

    print("=" * 60)
    print("  한국 세무·법령 문서 인제스트")
    print("=" * 60)

    if args.real:
        oc_key = os.environ.get("LAW_API_KEY", "")
        if not oc_key:
            print("""
[LAW_API_KEY 미설정]

무료 API 키 발급 방법 (5분):
  1. https://open.law.go.kr/LSO/openApi/openApiInfo.do 접속
  2. '활용신청' 클릭 → 이름·기관·이메일·서버 IP 입력
  3. 승인 후 OC 코드 수령 (즉시 또는 1일 이내)
  4. .env 에 추가:
       LAW_API_KEY=받은_OC_코드
  5. python scripts/download_laws.py --real

지금은 합성 문서로 먼저 진행합니다.
""")
            await ingest_synthetic(args.dsn)
        else:
            await ingest_real(args.dsn, oc_key)
    else:
        await ingest_synthetic(args.dsn)

    print("\n완료. run.bat 후 RAG 패널에서 질의해 보세요.")


if __name__ == "__main__":
    asyncio.run(main())
