"""RSS 수집: 제목 + 요약만 사용한다. 기사 본문 페이지는 절대 요청하지 않는다."""
import html
import re
import time
import requests
import feedparser
from .config import CATEGORIES, MAX_AGE_HOURS

UA = {"User-Agent": "Mozilla/5.0 (personal news-audio bot; RSS only)"}


def _clean(text: str, limit: int) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


# 요약 앞뒤의 송고 표기("(서울=연합뉴스) 홍길동 기자 =", "[서울=뉴시스]")와 기자 이메일 제거
_DATELINE = re.compile(r"^\s*[\(\[【<][^\)\]】>]{1,30}[\)\]】>]\s*")
_REPORTER = re.compile(r"^\s*[가-힣]{2,4}\s*(?:선임|수석|특파원|인턴)?\s*(?:기자|특파원)\s*=\s*")
_TAIL = re.compile(r"\s*(?:\(끝\)|(?:[가-힣]{2,4}\s*기자\s*)?\S+@\S+)\s*$")


def strip_byline(text: str) -> str:
    for _ in range(2):
        text = _REPORTER.sub("", _DATELINE.sub("", text))
    return _TAIL.sub("", text).strip(" =:·")


def fetch_feed(source: str, url: str) -> list[dict]:
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    out = []
    for e in feedparser.parse(r.content).entries:
        ts = e.get("published_parsed") or e.get("updated_parsed")
        out.append({
            "title": _clean(e.get("title", ""), 150),
            "summary": strip_byline(_clean(e.get("summary", "") or e.get("description", ""), 400)),
            "link": e.get("link", ""),
            "source": source,
            "ts": time.mktime(ts) if ts else 0,
        })
    return [a for a in out if a["title"]]


def collect(category: str, limit: int) -> list[dict]:
    """피드별 최신순 → 언론사를 번갈아가며(라운드로빈) 섞고, 중복 제목 제거."""
    per_feed, cutoff = [], time.time() - MAX_AGE_HOURS * 3600
    for source, url in CATEGORIES[category]["feeds"]:
        try:
            items = [a for a in fetch_feed(source, url) if a["ts"] == 0 or a["ts"] > cutoff]
            per_feed.append(sorted(items, key=lambda a: -a["ts"]))
            print(f"  [rss] {source}: {len(items)}건")
        except Exception as ex:  # 한 피드 실패는 무시
            print(f"  [rss] {source} 실패: {ex}")
    seen, result = set(), []
    for rank in range(max((len(f) for f in per_feed), default=0)):
        for feed in per_feed:
            if rank < len(feed):
                a = feed[rank]
                key = re.sub(r"[^0-9a-zA-Z가-힣]", "", a["title"])[:20]
                if key not in seen:
                    seen.add(key)
                    result.append(a)
    return result[:limit]
