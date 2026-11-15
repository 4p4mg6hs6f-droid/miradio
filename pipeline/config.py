"""설정값 모음. 환경변수로 덮어쓸 수 있는 값은 os.getenv 사용."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"          # 로컬/CI 임시 산출물 (git 제외)

# ── RSS 피드 ─────────────────────────────────────────────────────────────
# ⚠ 언론사가 RSS 주소를 바꾸거나 막을 수 있습니다.
#   `python -m pipeline.main --check-feeds` 로 먼저 점검하고, 죽은 주소는 교체하세요.
#   실패한 피드는 건너뛰고 나머지로 진행합니다.
# ※ 언론사마다 RSS 이용 조건이 다릅니다. 경향신문은 RSS를 개인 구독용으로 한정하고 공중 배포를
#   금지한다고 안내하고 있어 제외했습니다. 새 언론사를 추가하기 전에 약관을 확인하세요.
CATEGORIES = {
    "politics": {"label": "정치", "feeds": [
        ("연합뉴스", "https://www.yna.co.kr/rss/politics.xml"),
        ("한겨레", "https://www.hani.co.kr/rss/politics/"),
        ("JTBC", "https://fs.jtbc.co.kr/RSS/politics.xml"),
    ]},
    "economy": {"label": "경제", "feeds": [
        ("연합뉴스", "https://www.yna.co.kr/rss/economy.xml"),
        ("한겨레", "https://www.hani.co.kr/rss/economy/"),
        ("JTBC", "https://fs.jtbc.co.kr/RSS/economy.xml"),
    ]},
    "society": {"label": "사회", "feeds": [
        ("연합뉴스", "https://www.yna.co.kr/rss/society.xml"),
        ("한겨레", "https://www.hani.co.kr/rss/society/"),
        ("JTBC", "https://fs.jtbc.co.kr/RSS/society.xml"),
    ]},
    "it": {"label": "IT", "feeds": [
        ("ZDNet Korea", "https://feeds.feedburner.com/zdkorea"),
        ("전자신문", "https://rss.etnews.com/Section902.xml"),
        ("한겨레", "https://www.hani.co.kr/rss/science/"),
    ]},
}

VOICES = {"male": "ko-KR-InJoonNeural", "female": "ko-KR-SunHiNeural"}

# ── 대본 분량 ────────────────────────────────────────────────────────────
CHARS_PER_MIN = 330
TARGET_CHARS = int(os.getenv("TARGET_CHARS", CHARS_PER_MIN * 60))  # 1시간 ≈ 20,000자
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 6))        # Gemini 1회 호출당 기사 수 (5~8)
MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", 80))
MAX_AGE_HOURS = 36                                  # 오래된 기사 제외

# ── Gemini ───────────────────────────────────────────────────────────────
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_INTERVAL_SEC = float(os.getenv("GEMINI_INTERVAL_SEC", 8))  # 무료 티어 분당 호출 제한 대비
GEMINI_MAX_RETRIES = int(os.getenv("LLM_RETRIES", 1))  # 제공자당 시도 횟수: 1이면 실패 즉시 다음 제공자로
DEADLINE_MIN = int(os.getenv("RUN_DEADLINE_MIN", 80))   # 이 시간이 지나면 남은 분야를 건너뛰고 완료분만 배포

# ── GitHub Releases ──────────────────────────────────────────────────────
RELEASE_TAG = os.getenv("RELEASE_TAG", "audio")
# mp3 보관 위치: "pages"(기본, gh-pages/audio — Safari 포함 재생 호환) | "release"(GitHub Releases)
AUDIO_STORE = os.getenv("AUDIO_STORE", "pages")
