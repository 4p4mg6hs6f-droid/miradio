# miradio (서버 없는 뉴스 오디오 서비스)

GitHub Actions(생성) + GitHub Releases(mp3 보관) + GitHub Pages(정적 웹앱)만 사용합니다.
Render·Redis·별도 백엔드 서버는 없습니다.

## 유의사항 (꼭 읽어주세요)
- **개인·비상업 용도**를 가정합니다. 상업적 이용·재배포 전에는 각 언론사 이용약관과 RSS 이용 조건, Gemini API·Microsoft 음성 서비스 약관을 따로 확인해야 합니다.
- **edge-tts는 비공식 API**입니다. Microsoft Edge의 읽어주기 기능을 역공학한 것이라 언제든 중단·차단·품질 변경될 수 있고, 공식 SLA가 없습니다. 그래서 TTS를 `pipeline/tts.py`의 `TTSEngine` 인터페이스로 분리했습니다. 문제가 생기면 Azure Speech 등 공식 서비스를 구현한 클래스로 교체하세요.
- **저작권**: RSS의 **제목·요약만** 사용하며 기사 본문 페이지는 요청하지 않습니다. 그래도 AI가 요약을 다시 쓴 낭독문은 2차 저작물 성격이 있을 수 있으므로 외부 공개 시 주의하세요. 앱에는 출처 언론사와 원문 링크를 표시합니다.
- 대본은 AI가 쓰므로 **오류 가능성**이 있습니다(프롬프트로 "RSS에 없는 사실 금지"를 강제하지만 100% 보장은 불가).
- Releases 오디오를 브라우저에서 바로 재생하려면 **저장소가 public**이어야 합니다.
- RSS 주소는 `pipeline/config.py`에 예시로 넣었으며 **검증되지 않았습니다**. 먼저 `--check-feeds`로 점검하세요.

## 숨김 파일 주의 (.github 폴더가 안 올라갈 때)
웹 업로드(드래그 앤 드롭)나 일부 압축 해제는 `.`으로 시작하는 파일·폴더를 빠뜨립니다. 그래서 이 프로젝트는 보이는 이름으로 담았습니다. 올린 뒤 아래처럼 정식 위치에 만드세요.
- **워크플로(필수)**: GitHub 저장소 → Add file → Create new file → 파일명 칸에 `.github/workflows/generate.yml` 입력(슬래시를 치면 폴더가 만들어집니다) → `workflow/generate.yml` 내용을 붙여넣고 커밋. 이 위치가 아니면 Actions가 실행되지 않습니다.
- `gitignore.txt` → `.gitignore`, `env.example` → `.env.example`로 이름 변경 (선택)
- 터미널에서 `git add . && git commit && git push`로 올리면 숨김 파일도 정상 포함됩니다.

## 폴더 구조
```
.
├─ workflow/generate.yml            # cron 3회/일 + 수동 실행 (※ .github/workflows/ 로 옮겨야 동작)
├─ pipeline/
│  ├─ config.py       # 피드·목소리·분량·모델 설정
│  ├─ rss.py          # RSS 수집(제목+요약), 중복 제거, 언론사 섞기
│  ├─ script_gen.py   # Gemini 대본 생성(묶음 호출, 대기, 429 백오프)
│  ├─ tts.py          # TTSEngine 인터페이스 + EdgeTTSEngine, 길이 측정
│  ├─ publish.py      # Releases 업로드/미참조 에셋 삭제
│  ├─ main.py         # 오케스트레이션 + manifest 생성 + CLI
│  └─ requirements.txt
├─ web/ (index.html, app.js, style.css)   # → gh-pages 로 배포
├─ env.example, gitignore.txt       # 숨김파일(.env.example, .gitignore)의 보이는 사본
└─ README.md
```

## 동작 요약
1. 분야별 RSS 수집 → 2. 기사 6개씩 묶어 Gemini 호출(호출 간 8초 대기, 429/5xx 시 10·20·40·80초 백오프) → 목표 약 20,000자(1시간)에 도달하면 중단, 재료가 부족하면 실제 길이로 생성
3. 대본은 분야당 1회만 생성, 남/여 음성으로 각각 기사 단위 mp3 합성 후 mutagen으로 실제 길이 측정
4. 한 분야의 남·여 합성이 **모두 성공한 뒤에만** Releases 업로드 → manifest 갱신
5. gh-pages에 `manifest.json` + 웹앱 푸시 성공 후, manifest가 참조하지 않는 이전 mp3 삭제
6. 일부 분야 실패 시 그 분야는 이전 manifest 항목·에셋 유지, 전부 실패하면 배포하지 않음
7. 프론트는 선택 시간(10/30/60분)에 **가장 가까운 누적 지점**에서 끊어 재생

## 처음부터 배포까지
1. **저장소 생성**: GitHub에서 **public** 저장소를 만들고 이 폴더 내용을 `main`에 올립니다. 그 뒤 위의 '숨김 파일 주의'대로 `.github/workflows/generate.yml`을 만듭니다.
2. **Gemini API 키 발급**: https://aistudio.google.com 에서 무료 키 발급.
3. **Secrets 설정**: Settings → Secrets and variables → Actions
   | 이름 | 종류 | 값 |
   |---|---|---|
   | `GEMINI_API_KEY` | Secret(필수) | 발급받은 키 |
   | `GEMINI_MODEL` | Variable(선택) | 기본 `gemini-3.8-flash` |
   `GITHUB_TOKEN`은 Actions가 자동 제공합니다.
4. **Actions 권한**: Settings → Actions → General → Workflow permissions → *Read and write permissions*.
5. **첫 수동 실행**: Actions 탭 → `generate-news-audio` → *Run workflow*. (처음엔 `categories`에 `it` 하나만 넣어 시험 권장) 첫 실행 때 `gh-pages` 브랜치와 `audio` 릴리스가 자동 생성됩니다.
6. **Pages 설정**: 첫 실행이 끝난 뒤 Settings → Pages → Source: *Deploy from a branch* → Branch `gh-pages` / `/ (root)` → Save. 잠시 후 `https://<계정>.github.io/<저장소>/` 접속.
7. 이후 매일 KST 06:00 / 12:00 / 18:00 자동 갱신(GitHub cron은 수 분~수십 분 지연될 수 있음).

## 로컬 테스트 (1개 분야, 소량 기사)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt
export GEMINI_API_KEY=...            # .env.example 참고 (또는 직접 export)

python -m pipeline.main --check-feeds    # RSS 주소 점검
python -m pipeline.main --local --categories it --max-articles 8 --target-chars 3000
cd build/site && python -m http.server 8000   # http://localhost:8000
```
`--local`은 업로드 없이 `build/site/audio/`에 mp3를 만들고 manifest에는 상대 경로를 씁니다.

## 용량·한도 메모
- 분야 4 × 성별 2 × 1시간 ≈ 약 170MB(edge-tts 기본 비트레이트 기준)가 항상 Releases에 존재합니다. 이전 회차는 자동 삭제됩니다.
- Gemini 무료 티어: 1회 실행에 분야당 약 9~10회, 전체 약 40회 호출 → 하루 약 120회. 모델/요금제별 한도가 바뀔 수 있으니 `GEMINI_INTERVAL_SEC`, `BATCH_SIZE`로 조절하세요.
- 한도에 막히는 분야는 실패 처리되고 이전 데이터가 유지됩니다.

## Gemini 장애(503 등) 우회
대본 생성은 `LLM_CHAIN`(기본 `gemini,groq,openrouter`) 순서로 시도하며, 키를 등록한 제공자만 사용합니다. 전부 실패하면 RSS 제목·요약으로 만든 템플릿 대본으로 계속 진행합니다(품질은 낮고 숫자 읽기는 TTS에 의존).
- Groq: https://console.groq.com 에서 키 발급 → Secret `GROQ_API_KEY`
- OpenRouter: https://openrouter.ai/keys 에서 키 발급 → Secret `OPENROUTER_API_KEY`
- 모델 이름이 바뀌면 Variables의 `GROQ_MODEL`, `OPENROUTER_MODEL`, `GEMINI_MODEL`(쉼표로 여러 개)을 수정
- Gemini를 건너뛰고 싶으면 Variable `LLM_CHAIN`을 `groq,openrouter`처럼 지정

## 오디오 저장 방식 (AUDIO_STORE)
- `pages`(기본): mp3를 `gh-pages/audio/`에 두고 상대 경로로 재생합니다. GitHub Pages는 `audio/mpeg`·Range를 올바르게 제공해 Safari(아이폰 포함)에서도 재생됩니다. 매 실행마다 gh-pages를 새 히스토리로 force-push해 mp3가 히스토리에 쌓이지 않습니다. 사이트 용량은 약 170MB(분야 4 × 성별 2 × 1시간)입니다.
- `release`: GitHub Releases에 보관합니다. Releases 주소는 다운로드용(attachment) 응답이라 **Safari에서 `<audio>` 재생이 안 될 수 있습니다**(Chrome은 대체로 가능). Variable `AUDIO_STORE=release`로 전환할 수 있습니다.
- 기존 `audio` 릴리스는 더 이상 쓰지 않으면 Releases 탭에서 수동 삭제해도 됩니다.
