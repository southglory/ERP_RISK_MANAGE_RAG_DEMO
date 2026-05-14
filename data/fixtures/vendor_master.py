"""거래처 마스터 — Phase 6B 세무 리스크 판단용 참조 데이터.

프로덕션에서는 ERP 거래처 테이블에서 조회하지만,
테스트·데모 환경에서는 이 픽스처를 사용한다.
"""

from __future__ import annotations

# vendor_id → 속성 딕셔너리
# type: "domestic" | "overseas" | "unregistered"
# country: ISO 3166-1 alpha-2 (overseas만)
VENDOR_MASTER: dict[str, dict] = {
    "V-Samsung":  {"type": "domestic",     "name": "삼성전자"},
    "V-LG":       {"type": "domestic",     "name": "LG전자"},
    "V-TechPro":  {"type": "domestic",     "name": "테크프로"},
    "V-Naver":    {"type": "domestic",     "name": "네이버"},
    "V-KT":       {"type": "domestic",     "name": "KT"},
    "V-Office":   {"type": "domestic",     "name": "오피스플러스"},
    "V-AmazonKR": {"type": "overseas",     "name": "Amazon Web Services", "country": "US"},
    "V-Misc":     {"type": "domestic",     "name": "기타 국내"},
    "V-Kakao":    {"type": "domestic",     "name": "카카오"},
    "V-Unknown":  {"type": "unregistered", "name": "미등록 거래처"},
}
