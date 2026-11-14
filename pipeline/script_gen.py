"""Gemini 무료 티어로 방송 대본 생성: 기사 5~8개 묶음 단위, 429 지수 백오프."""
import json
import os
import re
import time
import requests
from .config import BATCH_SIZE, GEMINI_INTERVAL_SEC, GEMINI_MAX_RETRIES, GEMINI_MODEL

API = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"

PROMPT = """너는 한국 뉴스 라디오의 앵커다. 아래 [기사 목록]의 각 항목을 TTS가 낭독할 방송 대본으로 바꿔라.

규칙:
1. 제공된 제목·요약에 있는 사실만 사용한다. 원인·배경·전망·수치·인명을 새로 지어내지 마라. 정보가 빈약하면 짧게 쓰고, 억지로 늘리지 마라.
2. 항목마다 300~450자(정보가 적으면 120자 이상 가능). 앵커 낭독체(~했습니다, ~입니다)로 쓴다.
3. 첫 문장 안에서 출처 언론사를 밝힌다. 예: "연합뉴스 보도입니다."
4. 숫자·영문·기호는 소리 나는 대로 한글로 푼다. 예: 3.5% → 삼 점 오 퍼센트, 2026년 → 이천이십육 년, AI → 에이아이, 5G → 오지.
5. 이모지·마크다운·괄호·URL을 쓰지 않는다.
6. 항목 간 연결 멘트("다음 소식입니다" 등)는 넣지 않는다.

출력은 JSON 배열만: [{{"i": 항목번호, "script": "대본"}}, ...]

[분야] {label}
[기사 목록]
{articles}
"""


def _post(prompt: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    # GEMINI_MODEL 은 쉼표로 여러 개 지정 가능: 재시도마다 번갈아 사용(과부하 대비)
    models = [m.strip() for m in GEMINI_MODEL.split(",") if m.strip()]
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"}}
    for attempt in range(GEMINI_MAX_RETRIES):
        model = models[attempt % len(models)]
        wait = min(10 * 2 ** attempt, 80)  # 지수 백오프: 10, 20, 40, 80초…
        try:
            r = requests.post(API.format(m=model), json=body, timeout=(10, 240),
                              headers={"x-goog-api-key": key})
        except requests.RequestException as ex:  # 타임아웃·연결 오류도 재시도
            print(f"  [gemini] {model} 네트워크 오류({type(ex).__name__}), {wait}s 후 재시도 ({attempt + 1}/{GEMINI_MAX_RETRIES})")
            time.sleep(wait)
            continue
        if r.status_code == 200:
            try:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):  # 안전 필터 등으로 빈 응답
                print(f"  [gemini] {model} 빈 응답, 재시도")
                time.sleep(wait)
                continue
        if r.status_code in (429, 500, 503, 504):
            print(f"  [gemini] {model} {r.status_code}, {wait}s 후 재시도 ({attempt + 1}/{GEMINI_MAX_RETRIES})")
            time.sleep(wait)
            continue
        raise RuntimeError(f"Gemini {r.status_code} (model={model}): {r.text[:200]}")
    raise RuntimeError("Gemini 재시도 초과")


def _sanitize(text: str) -> str:
    text = re.sub(r"https?://\S+|[*_#`>\[\]{}]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def build_script(label: str, articles: list[dict], target_chars: int) -> list[dict]:
    """대본 목표 글자 수에 도달하면 중단. 반환: [{title, source, link, text}]"""
    items, total, fails = [], 0, 0
    for s in range(0, len(articles), BATCH_SIZE):
        if total >= target_chars:
            break
        batch = articles[s:s + BATCH_SIZE]
        listing = "\n".join(f"{i}. [{a['source']}] {a['title']} — {a['summary']}"
                            for i, a in enumerate(batch))
        try:
            data = json.loads(_post(PROMPT.format(label=label, articles=listing)))
            fails = 0
        except Exception as ex:
            print(f"  [gemini] 묶음 실패, 건너뜀: {ex}")
            fails += 1
            if fails >= 3:
                break
            time.sleep(GEMINI_INTERVAL_SEC)
            continue
        for d in data:  # 누락·비정상 항목은 버린다(지어내지 않음)
            try:
                a, text = batch[int(d["i"])], _sanitize(d["script"])
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            if len(text) >= 60:
                items.append({"title": a["title"], "source": a["source"],
                              "link": a["link"], "text": text})
                total += len(text)
        print(f"  [script] 누적 {total}/{target_chars}자")
        time.sleep(GEMINI_INTERVAL_SEC)  # 분당 호출 제한 대비
    if not items:
        raise RuntimeError("대본 생성 결과 없음")
    return items
