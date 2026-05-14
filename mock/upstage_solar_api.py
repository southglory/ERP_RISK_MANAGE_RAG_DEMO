"""Phase 5-5 — Upstage Solar API mock (OpenAI 호환).

회사 API 응답 형식만 흉내. 실제 추론은 안 함. echo 응답.

사용:
    python mock/upstage_solar_api.py   # localhost:8088 에서 기동

검증:
    VLLM_BASE_URL=http://localhost:8088/v1 VLLM_MODEL=solar-pro \
      python scripts/eval_ragas.py --keyword --limit 5
"""

import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="Mock Upstage Solar API")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float = 0.1
    max_tokens: int = 1024
    stream: bool = False


@app.get("/v1/models")
def models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id":       "solar-pro",
                "object":   "model",
                "created":  int(time.time()),
                "owned_by": "upstage",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest) -> dict:
    """마지막 user 메시지를 echo 형태로 반환 — RAG 평가의 키워드 매칭 sanity check 용."""
    last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    answer = f"[mock-solar 응답] {last_user[:300]}\n\n[출처: 참고 문서 확인 불가]"
    return {
        "id":      f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object":  "chat.completion",
        "created": int(time.time()),
        "model":   req.model,
        "choices": [
            {
                "index":         0,
                "message":       {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens":     100,
            "completion_tokens": 50,
            "total_tokens":      150,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8088)
