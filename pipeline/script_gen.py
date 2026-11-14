"""대본 생성.

여러 LLM 제공자를 순서대로 시도한다(LLM_CHAIN, 기본 gemini → groq → openrouter).
한 제공자가 재시도 후에도 실패하면 다음 제공자로 넘어가고, 전부 실패하면
AI 없이 RSS 제목·요약만으로 만든 템플릿 대본을 쓴다(파이프라인이 멈추지 않음).
"""
import json
import os
import re
import time
import requests
from .config import BATCH_SIZE, GEMINI_INTERVAL_SEC, GEMINI_MAX_RETRIES, GEMINI_MODEL

PROMPT = """너는 한국 뉴스 라디오의 앵커다. 아래 [기사 목록]의 각 항목을 TTS가 낭독할 방송 대본으로 바꿔라.

규칙:
1. 제공된 제목·요약에 있는 사실만 사용한다. 원인·배경·전망·수치·인명을 새로 지어내지 마라. 정보가 빈약하면 짧게 쓰고, 억지로 늘리지 마라.
2. 항목마다 300~450자(정보가 적으면 120자 이상 가능). 앵커 낭독체(~했습니다, ~입니다)로 쓴다.
3. 첫 문장 안에서 출처 언론사를 밝힌다. 예: "연합뉴스 보도입니다."
4. 숫자·영문·기호는 소리 나는 대로 한글로 푼다. 예: 3.5% → 삼 점 오 퍼센트, 2026년 → 이천이십육 년, AI → 에이아이, 5G → 오지.
5. 이모지·마크다운·괄호·URL을 쓰지 않는다.
6. 항목 간 연결 멘트("다음 소식입니다" 등)는 넣지 않는다.

출력은 JSON 객체만: {{"items": [{{"i": 항목번호, "script": "대본"}}, ...]}}

[분야] {label}
[기사 목록]
{articles}
"""

RETRY_CODES = (429, 500, 502, 503, 504)


class _Retryable(Exception):
    """일시 오류(429/5xx/타임아웃): 백오프 후 재시도."""


class ProviderError(Exception):
    """이 제공자로는 더 시도해도 소용없음: 다음 제공자로 전환."""


# ── 제공자 구현 ──────────────────────────────────────────────────────────
def _gemini(prompt: str, attempt: int) -> str:
    models = [m.strip() for m in GEMINI_MODEL.split(",") if m.strip()]  # 쉼표로 여러 모델 가능
    model = models[attempt % len(models)]                                # 재시도마다 번갈아 사용
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}}
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            json=body, timeout=(10, 120), headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    except requests.RequestException as ex:
        raise _Retryable(f"{model} {type(ex).__name__}")
    if r.status_code == 200:
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise _Retryable(f"{model} 빈 응답")
    if r.status_code in RETRY_CODES:
        raise _Retryable(f"{model} {r.status_code}")
    raise ProviderError(f"{model} {r.status_code}: {r.text[:150]}")


def _chat(url: str, key: str, model: str, prompt: str, json_mode: bool) -> str:
    """OpenAI 호환 chat/completions (Groq, OpenRouter 공용)."""
    body = {"model": model, "temperature": 0.4, "messages": [{"role": "user", "content": prompt}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = requests.post(url, json=body, timeout=(10, 120), headers={"Authorization": f"Bearer {key}"})
    except requests.RequestException as ex:
        raise _Retryable(f"{model} {type(ex).__name__}")
    if r.status_code == 200:
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise _Retryable(f"{model} 빈 응답")
    if r.status_code in RETRY_CODES:
        raise _Retryable(f"{model} {r.status_code}")
    raise ProviderError(f"{model} {r.status_code}: {r.text[:150]}")


PROVIDERS = {
    "gemini": {"key": "GEMINI_API_KEY", "fn": _gemini},
    "groq": {"key": "GROQ_API_KEY", "fn": lambda p, a: _chat(
        "https://api.groq.com/openai/v1/chat/completions", os.environ["GROQ_API_KEY"],
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), p, True)},
    "openrouter": {"key": "OPENROUTER_API_KEY", "fn": lambda p, a: _chat(
        "https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"],
        os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"), p, False)},
}


def _retry(call, name: str):
    for attempt in range(GEMINI_MAX_RETRIES):
        try:
            return call(attempt)
        except _Retryable as ex:
            wait = min(5 * 2 ** attempt, 40)  # 지수 백오프: 5, 10, 20, 40초
            print(f"  [llm] {name} 일시 오류({ex}) ({attempt + 1}/{GEMINI_MAX_RETRIES})")
            if attempt < GEMINI_MAX_RETRIES - 1:
                time.sleep(wait)
    raise ProviderError(f"{name} 재시도 초과")


def _parse(text: str) -> list:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("items") or next((v for v in data.values() if isinstance(v, list)), [])
    if not isinstance(data, list):
        raise ValueError("목록 형식이 아님")
    return data


class Chain:
    """제공자 순차 시도 + 실패한 제공자는 잠시(2묶음) 건너뛰기."""

    def __init__(self):
        names = [n.strip() for n in os.getenv("LLM_CHAIN", "gemini,groq,openrouter").split(",")]
        self.providers = [(n, PROVIDERS[n]) for n in names
                          if n in PROVIDERS and os.getenv(PROVIDERS[n]["key"])]
        self.cool, self.n = {}, 0
        print("  [llm] 사용 순서:", [n for n, _ in self.providers] or "없음 → 템플릿 대본")

    def run(self, prompt: str):
        self.n += 1
        for name, p in self.providers:
            if self.cool.get(name, 0) > self.n:
                continue
            try:
                return _parse(_retry(lambda a: p["fn"](prompt, a), name)), name
            except (ProviderError, ValueError) as ex:  # JSON 파싱 실패(ValueError)도 전환 사유
                print(f"  [llm] {name} 실패 → 다음 제공자: {ex}")
                self.cool[name] = self.n + 2
        return None, "plain"


def _sanitize(text: str) -> str:
    text = re.sub(r"https?://\S+|[*_#`>\[\]{}]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _plain(a: dict) -> str:
    """AI 없이 만든 대본: RSS 제목·요약 그대로(사실 추가 없음). 숫자 읽기는 TTS에 맡김."""
    body = a["summary"] if a["summary"][:20] != a["title"][:20] else ""
    return _sanitize(f"{a['source']} 보도입니다. {a['title']}. {body}")


def build_script(label: str, articles: list[dict], target_chars: int) -> list[dict]:
    """목표 글자 수에 도달하면 중단. 반환: [{title, source, link, text}]"""
    chain, items, total, n_plain = Chain(), [], 0, 0
    for s in range(0, len(articles), BATCH_SIZE):
        if total >= target_chars:
            break
        batch = articles[s:s + BATCH_SIZE]
        listing = "\n".join(f"{i}. [{a['source']}] {a['title']} — {a['summary']}"
                            for i, a in enumerate(batch))
        data, used = chain.run(PROMPT.format(label=label, articles=listing))
        if data is None:  # 모든 제공자 실패 → 템플릿 대본
            data = [{"i": i, "script": _plain(a)} for i, a in enumerate(batch)]
            n_plain += len(batch)
        for d in data:  # 누락·비정상 항목은 버린다(지어내지 않음)
            try:
                a, text = batch[int(d["i"])], _sanitize(d["script"])
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            if len(text) >= 40:
                items.append({"title": a["title"], "source": a["source"],
                              "link": a["link"], "text": text})
                total += len(text)
        print(f"  [script] ({used}) 누적 {total}/{target_chars}자")
        if used != "plain":
            time.sleep(GEMINI_INTERVAL_SEC)  # 분당 호출 제한 대비
    if n_plain:
        print(f"  [script] ⚠ AI 실패로 템플릿 대본 {n_plain}건 사용")
    if not items:
        raise RuntimeError("대본 생성 결과 없음")
    return items
