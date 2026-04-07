# Industry Briefing Dashboard

매일 아침 자동으로 금융 업계 동향을 수집하고, 대시보드 + 팟캐스트 오디오를 생성합니다.

## 세팅

### 1. Secrets 등록 (Settings → Secrets → Actions)
| Secret | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `GOOGLE_TTS_API_KEY` | console.cloud.google.com |

### 2. GitHub Pages 활성화
Settings → Pages → Source: **Deploy from branch** → Branch: **main** → Folder: **/docs**

### 3. 첫 실행
Actions → Daily Industry Briefing → Run workflow

### 4. 대시보드 접속
`https://[username].github.io/[repo-name]`

## 커스터마이징
`briefing.py` 상단의 `INSTITUTIONS` 리스트 수정
