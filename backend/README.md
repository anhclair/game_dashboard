# Dashboard Backend (Python/FastAPI + SQLite)

간단한 개인용 대시보드/버튼 클릭 백엔드를 위한 최소 구성이에요. `../files` 경로의 CSV/XLSX를 읽어 자동으로 DB를 시드합니다.

## 구성
- FastAPI
- SQLite (파일 `data.db` 생성)
- SQLAlchemy 모델
  - 대시보드: `games`, `characters`, `currencies`, `game_events`, `spendings`
  - 버튼 로그: `items`, `events`
- 데이터 위치: `../files/GameDB.xlsx`, `CharacterDB.csv`, `CurrencyDB.csv`, `EventDB.csv`, `SpendingDB.csv`
- 핵심 계산 규칙
  - Game: `playtime = 오늘 - StartDate + 1 (일 단위)`, `during_play = EndDate 없음`, `stop_play=True`이면 메인 목록에서 제외
  - Currency: `timestamp`는 서버 타임으로 기록, `/currencies/{id}/adjust` 호출 시 **새 행 추가** 후 최신 `timestamp` 기준으로 표시
  - Event: `state`는 StartDate/EndDate와 서버 타임으로 `예정/진행 중/종료` 계산
  - Spending: `next_paying_date = paying_date + expiration_days`, `remain_date = next_paying_date - 오늘`, `is_repaying`은 3/7/15일 임계값으로 `갱신필요/유의/여유`
  - GameDB 컬럼 확장: `UID`, `CouponURL`

## 엔드포인트
- `GET /health` 서버 상태 확인
- `POST /items` 아이템 생성 `{label, gift_code?, state?}`
- `GET /items` 아이템 목록
- `POST /actions/click` 버튼 클릭 처리 `{item_id, action, next_state?, gift_code?}`  
  - 아이템 상태/선물코드 업데이트 + `events`에 로그 남김
- `GET /metrics/weekly` 최근 7일 이벤트 발생 건수 일별 집계
- `GET /games?during_play_only=true|false&include_stopped=true|false` 게임 목록(플레이 중/종료/숨김 필터)
- `POST /games/{game_id}/end` 게임 종료 처리(EndDate=오늘, stop_play=True)
- `GET /games/{game_id}/characters` 캐릭터 목록(소유 여부 `is_have` 포함)
- `GET /games/{game_id}/currencies` 재화 목록 + `late_date`
- `GET /games/{game_id}/currencies/timeseries?title=...&days=7` 재화 타임시리즈(전체/단일 재화, 기본 7일)
- `POST /currencies/{currency_id}/adjust` 재화 수량 덮어쓰기 `{counts}` + 서버 타임으로 **새 행 추가** 및 `timestamp` 갱신
- `GET /games/{game_id}/events` 이벤트 목록 + 계산된 `state`
- `POST /games/{game_id}/events` 이벤트 추가 `{title,type,start_date,end_date?,priority}`
- `GET /games/{game_id}/spendings` 정기 결제/패스 목록 + `next_paying_date`, `remain_date`, `is_repaying`
- `POST /spendings/{spending_id}/renew` 결제일 갱신 `{paying_date?, expiration_days?, paying?}`
- `POST /characters/{character_id}/update` 레벨/등급/돌파/보유 업데이트

## 프런트엔드(PWA) 메모
- 정적 파일: `backend/static` (`index.html`, `styles.css`, `script.js`)
- PWA: `manifest.webmanifest`, `service-worker.js` 등록, `/assets`로 이미지 마운트. 아이콘은 `static/icons/*`, `apple-touch-icon.png`.
- 대시보드 레이아웃: 메인 갤러리(4열, 2.5행 높이 스크롤) → 카드 클릭 시 전체 화면 상세, 상단 왼쪽에 메인으로 돌아가기 버튼.
- 이미지 매핑: `files/image/<GAME_DIR>/{icon,profile}` 사용. JS `IMAGE_FILES` 매핑 참고.
- 권한 모드:
  - 기본 뷰어(버튼 비활성). 상단 우측 톱니 → 암호 입력 후 편집 모드.
  - 기본 암호: `0690` (변경 시 `static/script.js` 내 비교값 수정). 로컬스토리지 `dashboard-can-edit` 플래그 사용.
- 그래프: `/currencies/timeseries?weekly=true&weeks=8` 호출. 주간 구간에서 최대값, 없으면 직전 값으로 채움. 타임스탬프 비어 있어도 직전 값으로 이어짐.
- 시드 파일: `/files` (XLSX/CSV/이미지). 컨테이너 빌드 시 `/files`로 복사하여 자동 시드.

## Fly.io 배포 가이드(HTTPS, 상시 접근)
1) 사전 준비: `flyctl` 설치 후 로그인(`fly auth login`), 가까운 리전을 `fly platform regions`로 확인 후 `fly.toml`의 `primary_region` 수정. 앱 이름(`app`)도 원하는 값으로 변경.
2) 앱 생성(한 번만): `fly apps create <app-name>` (예: `clair-dashboard`), `fly.toml`의 `app`과 일치시킬 것.
3) 볼륨 생성(데이터 보존): `fly volumes create datavol --size 1 --region <리전>`  (리전은 `primary_region`과 동일하게, 예: nrt)  
   - DB 경로는 `DATABASE_URL=sqlite:////data/data.db`로 `/data` 볼륨에 저장.
4) 배포:
   ```bash
   flyctl deploy --remote-only -a <app-name>
   ```
   기본 도커파일(Dockerfile)로 uvicorn을 8080 포트에서 실행, HTTPS는 자동 적용.
5) 접속: `https://<app>.fly.dev/` (도메인 연결 시 CNAME만 설정하면 됨). PWA는 상대 경로라 같은 도메인에서 바로 동작.
6) 백업/재배포 시 볼륨 유지: 동일 리전/볼륨 이름을 사용하면 `data.db`가 그대로 남음.

## 로컬 실행 (Linux 기준)
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

- 프론트엔드: `http://localhost:8000/` 접속 시 기본 대시보드(게임 갤러리/게임별 5섹션) 확인 가능.

## 간단 사용 예시
```bash
# 아이템 생성
curl -X POST http://localhost:8000/items -H "Content-Type: application/json" \
  -d '{"label":"Gift A","gift_code":"ABC123","state":"pending"}'

# 버튼 클릭: 상태 완료로 변경 + 선물코드 업데이트
curl -X POST http://localhost:8000/actions/click -H "Content-Type: application/json" \
  -d '{"item_id":1,"action":"mark_done","next_state":"done","gift_code":"XYZ999"}'

# 주간 그래프 데이터
curl http://localhost:8000/metrics/weekly

# 플레이 중 게임만 조회
curl "http://localhost:8000/games?during_play_only=true"

# 특정 게임의 재화 조정(예: id=3, 10 증가)
curl -X POST http://localhost:8000/currencies/3/adjust -H "Content-Type: application/json" -d '{"delta":10}'
```

## iOS 연동 포인트 (요약)
- 커스텀 스킴으로 `myapp://action?id=1&gift=ABC` 등을 받아서 `POST /actions/click` 호출.
- 대시보드 카드/리스트: `GET /games` (필터는 `during_play_only=true`), 상세 탭은 `characters`, `currencies`, `events`, `spendings` 서브 엔드포인트 사용.
- 재화 변경 버튼은 `POST /currencies/{id}/adjust` 호출 시 `late_date`가 서버 타임으로 자동 업데이트.
- 대시보드 그래프는 `GET /metrics/weekly` 응답의 `buckets` 배열을 그대로 렌더링.
- 필요 시 버튼 목록은 `GET /items`로 가져오거나, 앱 내부에 정의한 후 `item_id`만 API에 전달.

### iOS 샘플 호출 (Swift / async-await)
```swift
struct ClickRequest: Codable {
    let item_id: Int
    let action: String
    let next_state: String?
    let gift_code: String?
}

func sendClick(req: ClickRequest) async throws {
    var request = URLRequest(url: URL(string: "http://localhost:8000/actions/click")!)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.httpBody = try JSONEncoder().encode(req)

    let (_, response) = try await URLSession.shared.data(for: request)
    guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
        throw URLError(.badServerResponse)
    }
}
```
