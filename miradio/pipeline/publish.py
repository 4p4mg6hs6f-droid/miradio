"""GitHub Releases 업로드/정리 (REST API). 토큰은 Actions의 GITHUB_TOKEN."""
import os
import time
from pathlib import Path
import requests
from .config import RELEASE_TAG


class ReleaseStore:
    def __init__(self):
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.h = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                  "Accept": "application/vnd.github+json"}
        self.api = f"https://api.github.com/repos/{self.repo}"
        self.release = self._ensure()

    def _ensure(self) -> dict:
        r = requests.get(f"{self.api}/releases/tags/{RELEASE_TAG}", headers=self.h, timeout=30)
        if r.status_code == 404:
            r = requests.post(f"{self.api}/releases", headers=self.h, timeout=30, json={
                "tag_name": RELEASE_TAG, "name": "News audio (auto-generated)",
                "body": "자동 생성 뉴스 오디오 저장소. 수동으로 수정하지 마세요."})
        r.raise_for_status()
        return r.json()

    def upload(self, path: Path, name: str) -> str:
        url = self.release["upload_url"].split("{")[0]
        for attempt in range(3):
            try:
                with open(path, "rb") as f:
                    r = requests.post(url, params={"name": name}, data=f, timeout=300,
                                      headers={**self.h, "Content-Type": "audio/mpeg"})
                r.raise_for_status()
                return r.json()["browser_download_url"]
            except Exception as ex:
                print(f"  [upload] {name} 재시도 {attempt + 1}: {ex}")
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"업로드 실패: {name}")

    def list_assets(self) -> list[dict]:
        out, page = [], 1
        while True:
            r = requests.get(f"{self.api}/releases/{self.release['id']}/assets",
                             headers=self.h, params={"per_page": 100, "page": page}, timeout=30)
            r.raise_for_status()
            if not r.json():
                return out
            out += r.json()
            page += 1

    def cleanup(self, keep_names: set[str]) -> int:
        """manifest가 참조하지 않는 에셋(이전 회차·실패 잔여물) 삭제."""
        n = 0
        for a in self.list_assets():
            if a["name"] not in keep_names:
                requests.delete(f"{self.api}/releases/assets/{a['id']}",
                                headers=self.h, timeout=30).raise_for_status()
                n += 1
        return n
