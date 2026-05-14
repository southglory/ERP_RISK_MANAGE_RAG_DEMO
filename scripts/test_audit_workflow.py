"""Phase 4-1 감사 워크플로우 스모크 테스트 — LLM/RAG 없이 순수 Python 노드 검증."""
import sys
sys.path.insert(0, ".")

from core.audit.workflow import (
    node_intake, node_classify, node_rule, node_xai, node_review,
)


def make_state(question: str, answer: str = "가산세는 0.022%입니다. 적용 가능합니다."):
    return dict(
        question=question, trace_id="test-001",
        validated=False, intake_error="",
        case_type="", rule_fired=False, rule_output={}, rule_confidence=0.0,
        retrieved_chunks=[], context="",
        answer=answer, llm_confidence=0.0,
        rule_weight=0.0, llm_weight=0.0, conflict_flag=False, rationale="",
        needs_human_review=False, review_reason="",
    )


def run_case(label: str, question: str, answer: str = "테스트 답변입니다. 적용 가능합니다."):
    print(f"\n{'='*55}")
    print(f"[{label}] {question[:50]}")
    print("=" * 55)
    s = make_state(question, answer)
    s = node_intake(s)
    print(f"  intake   → validated={s['validated']}")
    if not s["validated"]:
        print(f"           error={s['intake_error']}")
        return

    s = node_classify(s)
    print(f"  classify → case_type={s['case_type']}")

    s = node_rule(s)
    print(f"  rule     → fired={s['rule_fired']} conf={s['rule_confidence']:.0%}")
    if s["rule_fired"]:
        for k, v in s["rule_output"].items():
            print(f"             {k}: {v}")

    s = node_xai(s)
    print(f"  xai      → rule_w={s['rule_weight']:.2f} llm_w={s['llm_weight']:.2f} conflict={s['conflict_flag']}")
    print(f"             {s['rationale']}")

    s = node_review(s)
    flag = "[REVIEW]" if s["needs_human_review"] else "[AUTO]"
    print(f"  review   → {flag}  {s['review_reason']}")


# ── 테스트 케이스 ──────────────────────────────────────────────────────────────

run_case("세무1", "미국 법인에 지급한 SW 사용료의 원천세율은?")

run_case("세무2", "납부지연 가산세 계산 기준일과 요율은?")

run_case("수익인식1", "SaaS 구독 서비스의 K-IFRS 1115 수익인식 시점은?")

run_case("수익인식2", "영구 라이선스 키 전달 방식의 수익인식 방법은?")

run_case("부정탐지1", "분기말 밀어넣기 거래의 기간귀속 조작 탐지 방법은?")

run_case("계약1", "하도급 계약 위약금 기준은?",
         answer="위약금 조항은 계약서에 따라 다릅니다.")

run_case("빈질문", "")

# 충돌 케이스: 룰 hold → LLM 가능
run_case("충돌", "납부지연 가산세 계산",
         answer="이 경우에도 가산세 적용이 가능합니다.")

print("\n✅ 스모크 테스트 완료")
