"""TTS 엔진 인터페이스. 다른 엔진으로 바꾸려면 TTSEngine만 상속해 구현하면 된다."""
import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from mutagen.mp3 import MP3


class TTSEngine(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice: str, out: Path) -> None:
        """text를 voice 음성으로 mp3 파일(out)에 저장."""


class EdgeTTSEngine(TTSEngine):
    """edge-tts (비공식 API: 언제든 중단·차단될 수 있음)."""

    async def synthesize(self, text: str, voice: str, out: Path) -> None:
        import edge_tts
        for attempt in range(4):
            try:
                await edge_tts.Communicate(text, voice).save(str(out))
                if out.exists() and out.stat().st_size > 1000:
                    return
            except Exception as ex:
                print(f"  [tts] 재시도 {attempt + 1}: {ex}")
            await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"TTS 실패: {out.name}")


def duration_sec(path: Path) -> float:
    return round(MP3(str(path)).info.length, 1)  # 실제 재생 길이 측정


async def synth_all(engine: TTSEngine, texts: list[str], voice: str,
                    paths: list[Path], concurrency: int = 3) -> list[float]:
    sem = asyncio.Semaphore(concurrency)

    async def one(t, p):
        async with sem:
            await engine.synthesize(t, voice, p)
        return duration_sec(p)

    return list(await asyncio.gather(*(one(t, p) for t, p in zip(texts, paths))))
