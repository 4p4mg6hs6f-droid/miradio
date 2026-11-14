"""파이프라인 진입점.

  python -m pipeline.main                         # 전체(CI용)
  python -m pipeline.main --local --categories it --max-articles 8 --target-chars 3000
  python -m pipeline.main --check-feeds           # RSS 주소 점검
  python -m pipeline.main --cleanup               # manifest 미참조 에셋 삭제
"""
import argparse
import asyncio
import json
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .config import BUILD, CATEGORIES, MAX_ARTICLES, ROOT, TARGET_CHARS, VOICES
from .rss import collect, fetch_feed
from .script_gen import build_script
from .tts import EdgeTTSEngine, synth_all


def process_category(cat, args, store, stamp, engine, site: Path) -> dict:
    label = CATEGORIES[cat]["label"]
    articles = collect(cat, args.max_articles)
    if not articles:
        raise RuntimeError("수집된 기사 없음")
    items = build_script(label, articles, args.target_chars)           # 성별 공통, 1회만 생성

    # 청크 0 = 인트로, 이후 기사 1건 = 청크 1개. 10/30분은 프론트에서 앞부분만 사용.
    meta = [{"title": f"{label} 뉴스 브리핑", "source": "", "link": ""}] + [
        {k: i[k] for k in ("title", "source", "link")} for i in items]
    texts = [f"{label} 뉴스입니다. 지금부터 주요 소식을 전해드리겠습니다."] + [i["text"] for i in items]

    work = BUILD / "audio" / cat
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    names = {g: [f"{cat}-{g}-{stamp}-{n:03d}.mp3" for n in range(len(texts))] for g in VOICES}
    durs = {}
    for g, voice in VOICES.items():                                    # 전부 합성 성공 후에만 업로드
        for attempt in (1, 2):                                         # 전부 실패하면 한 번만 더 시도
            print(f"  [tts] {g} {len(texts)}청크 (시도 {attempt}/2)")
            durs[g] = asyncio.run(synth_all(engine, texts, voice, [work / n for n in names[g]]))
            if any(d is not None for d in durs[g]):
                break
            time.sleep(10)
        else:
            raise RuntimeError(f"TTS 전부 실패({g}): 이 분야는 건너뜀")
        if None in durs[g]:
            print(f"  [tts] ⚠ {g}: {durs[g].count(None)}청크 실패 → 제외하고 진행")

    voices = {}
    for g in VOICES:
        chunks = []
        for m, name, d in zip(meta, names[g], durs[g]):
            if d is None:                                              # 실패 청크 제외
                continue
            if store:
                url = store.upload(work / name, name)
            else:                                                      # 로컬: site/audio/ 로 복사
                (site / "audio").mkdir(parents=True, exist_ok=True)
                shutil.copy(work / name, site / "audio" / name)
                url = f"audio/{name}"
            chunks.append({**m, "audio": url, "duration": d})
        voices[g] = {"total_sec": round(sum(d for d in durs[g] if d), 1), "chunks": chunks}
    return {"label": label, "updated_at": datetime.now(timezone.utc).isoformat(), "voices": voices}


def referenced_names(manifest: dict) -> set[str]:
    return {Path(urlparse(ch["audio"]).path).name
            for c in manifest.get("categories", {}).values()
            for v in c["voices"].values() for ch in v["chunks"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--categories", default="", help="쉼표 구분. 비우면 전체")
    p.add_argument("--max-articles", type=int, default=MAX_ARTICLES)
    p.add_argument("--target-chars", type=int, default=TARGET_CHARS)
    p.add_argument("--local", action="store_true", help="업로드 없이 build/site 에 결과 생성")
    p.add_argument("--site-dir", default="")
    p.add_argument("--check-feeds", action="store_true")
    p.add_argument("--list-models", action="store_true", help="키별 사용 가능 모델 출력")
    p.add_argument("--cleanup", action="store_true")
    args = p.parse_args()

    if args.list_models:
        from .script_gen import list_models
        return list_models()

    if args.check_feeds:
        for cat, c in CATEGORIES.items():
            for src, url in c["feeds"]:
                try:
                    print(f"OK   {cat:9} {src}: {len(fetch_feed(src, url))}건")
                except Exception as ex:
                    print(f"FAIL {cat:9} {src}: {ex}")
        return

    site = Path(args.site_dir or (BUILD / "site" if args.local else ROOT / "site"))
    site.mkdir(parents=True, exist_ok=True)
    mpath = site / "manifest.json"
    manifest = json.loads(mpath.read_text("utf-8")) if mpath.exists() else {"version": 1, "categories": {}}

    store = None
    if not args.local:
        from .publish import ReleaseStore
        store = ReleaseStore()

    if args.cleanup:
        print(f"삭제된 에셋: {store.cleanup(referenced_names(manifest))}개")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    cats = [c for c in (args.categories.split(",") if args.categories else CATEGORIES) if c in CATEGORIES]
    engine, ok, failed = EdgeTTSEngine(), [], []
    for cat in cats:
        print(f"== {cat} ==")
        try:
            manifest["categories"][cat] = process_category(cat, args, store, stamp, engine, site)
            ok.append(cat)
        except Exception:                      # 실패 분야는 이전 manifest 항목 유지
            traceback.print_exc()
            failed.append(cat)
            print(f"::warning::{cat} 실패 — 이전 데이터 유지")

    if not ok:
        sys.exit("모든 분야 실패: manifest를 갱신하지 않습니다.")
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    print(f"완료: 성공={ok} 실패={failed}")

    if args.local:                              # 로컬 미리보기용으로 프론트도 복사
        for f in (ROOT / "web").iterdir():
            shutil.copy(f, site / f.name)
        print(f"미리보기: cd {site} && python -m http.server 8000")


if __name__ == "__main__":
    main()
