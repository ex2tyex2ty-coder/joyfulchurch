# JOYFUL WORSHIP OPS

조이풀교회 예배 운영 대시보드입니다. 원본 매뉴얼·예배인원 Google Sheets는 읽기 전용으로만 사용하고, 팀 확인 게시판은 별도 Google Sheets에 영구 저장합니다.

## Google Sheets 최신 자료 반영

대시보드 또는 `데이터·백업` 화면에서 **최신 자료 업데이트**를 누르면 다음 두 문서를 읽기 전용으로 가져옵니다.

- 2025 예배팀 매뉴얼
- 2025 예배팀 엔지니어 라인업

공개 보기 문서는 별도 설정 없이 작동합니다. 운영 문서를 비공개로 전환할 때는 Google 서비스 계정을 만들고 두 문서를 그 서비스 계정 이메일에 `뷰어`로 공유한 뒤, Streamlit Secrets에 서비스 계정 JSON을 다음 형식으로 저장합니다.

```toml
[google_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "<private_key 필드 전체>"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

동기화는 참석인원·라인업·원본 매뉴얼을 갱신합니다. 원본 Google Sheets 두 개에는 쓰기 API를 사용하지 않습니다.

## 팀 확인 게시판 영구 저장

게시판은 `GOOGLE_REVIEW_BOARD_SERVICE_ACCOUNT` Streamlit Secret으로 연결한 별도 스프레드시트에 저장합니다.

```toml
GOOGLE_REVIEW_BOARD_SERVICE_ACCOUNT = '''
{
  "type": "service_account",
  "project_id": "...",
  "private_key_id": "...",
  "private_key": "<private_key 필드 전체>",
  "client_email": "...@....iam.gserviceaccount.com",
  "token_uri": "https://oauth2.googleapis.com/token"
}
'''
```

- 게시판 문서만 해당 서비스 계정에 `편집자`로 공유합니다.
- 원본 자료 두 문서에는 이 쓰기 계정을 편집자로 공유하지 않습니다.
- 백업 JSON에는 게시글, 댓글, 변경이력이 포함됩니다.

조이풀교회 예배팀의 행사, 체크리스트, 매뉴얼, 결정 이유, 운영 로그, 참석 통계와 참고자료를 연결해 보존하는 로컬 운영·지식관리 시스템입니다.

예배 준비, 행사 기록, 매뉴얼, 참석 통계를 한곳에서 관리하는 내부 운영 도구입니다.

## 현재 구현된 V1

- 행동 중심 Dashboard
- 행사 생성, 상태, D-Day, 보관
- 팀 확인 게시판 분류·중요도·담당·기한·댓글·상태 관리
- 동일 계열의 이전 행사 자동 연결
- 이전 행사 기준 복제
- 행사별 체크리스트와 중요도 가중 준비도
- 체크리스트 템플릿과 행사일 기준 자동 기한
- 선행 업무 미완료 경고용 의존관계
- 종료 행사 회고
- 이전 문제를 다음 행사 중요업무로 전환
- 매뉴얼 WHAT / HOW / WHY / 현재 기준
- 매뉴얼 Revision History와 CURRENT / SUPERSEDED 상태
- 내용 변경 없는 Last Verified 갱신
- Decision Log와 관련 행사·매뉴얼 연결
- Operation / Technical Log
- 실제 XLSX 참석 데이터 Import와 주일 현장 중심 분석
- 동일 날짜·예배 종류를 하나의 예배 회차로 연결하는 canonical service 구조
- 현장 참석과 온라인 지표 분리, 원본 집계값 보존
- 미입력·명시적 0·취소·송출 없음·추정 집계 상태 구분
- 행 자체가 없는 지난 주일까지 찾는 자료 최신성 점검
- 인원·라인업·특별순서·대표기도·행사의 예배 회차 연결
- 전체 검색
- Archive / Restore
- 최소 Audit Log
- JSON 전체 백업과 테이블별 CSV 백업
- 모바일·PC 반응형 UI
- 주일·금요예배 자동 D-Day와 Google Calendar 교회력 동기화
- 한국어 성경 구절 표기 자동 인식과 설교 문자 일괄 본문 정리

## 성경 검색 연동

`성경 검색`은 외부 성경 서비스에 접속하지 않고 저장된 `bible_text.txt`의 텍스트값만 사용합니다. `창:1:1`, `창세기 1장 1절`, `행 7:2~3`, `사도행전 7장 2~3절` 형식과 여러 구절이 들어간 설교 문자를 인식합니다. `~`, `-`, `–`로 표시된 같은 장의 구절 범위는 각 절로 자동 확장합니다. 설교 문자·구절 목록 TXT도 별도로 불러올 수 있고, UTF-8과 윈도우 한글 메모장 형식을 지원하며 한 번에 최대 100개 구절을 처리합니다.

배포 루트에 `bible_text.txt`가 있으면 앱이 재부팅되어도 이를 기본 성경 본문으로 자동 연결합니다. 화면의 `성경 전체 본문 교체`는 기본 파일을 덮어쓰지 않고 현재 접속에서만 다른 번역본을 사용합니다. 공개 앱에서 번역문을 표시할 때는 해당 번역본의 이용 범위를 운영자가 확인합니다.

## 프로젝트 구조

```text
joyful_worship_ops/
├─ app.py                  # Streamlit UI
├─ bible_lookup.py         # 한국어 성경 표기 인식·로컬 TXT 본문 조회
├─ bible_text.txt          # 기본 성경 전체 본문
├─ config.py               # 경로와 상태 상수
├─ db.py                   # SQLite Schema와 도메인 로직
├─ migration.py            # XLSX 탐색·검증·정규화·Import
├─ data/
│  ├─ source/              # 수정하지 않는 원본 XLSX
│  ├─ joyful_worship_ops.db
│  ├─ import_report.json
│  └─ backups/
├─ docs/
│  ├─ ARCHITECTURE.md
│  └─ DATA_INVENTORY.md
└─ tests/
   ├─ test_scenarios.py
   └─ test_ui_smoke.py
```

## 실행 방법

현재 상위 프로젝트의 `.venv`에 필요한 패키지가 설치되어 있으므로 Windows에서는 다음 파일을 실행하면 됩니다.

```powershell
.\run.bat
```

또는 터미널에서 직접 실행합니다.

```powershell
..\.venv\Scripts\python.exe -m streamlit run app.py --server.port=8766
```

브라우저에서 `http://localhost:8766`을 엽니다.

## Google Calendar 교회력 연동

1. Google Cloud에서 Calendar API를 활성화합니다.
2. Google Calendar 설정 → `특정 사용자와 공유`에서 게시판용 서비스 계정 이메일을 `모든 일정 세부정보 보기`로 추가합니다.
3. Calendar ID를 Streamlit Secrets에 저장하면 재부팅 후에도 설정이 유지됩니다.

```toml
GOOGLE_CALENDAR_ID = "church-calendar@group.calendar.google.com"
```

4. 앱의 `교회력` 메뉴에서 `Google Calendar 읽기·동기화`를 누릅니다.

앱은 `calendar.readonly` 범위만 요청하며 Google Calendar 일정을 작성·수정·삭제하지 않습니다.

독립 환경을 새로 만들려면:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port=8766
```

## 초기 데이터 Import

원본 파일을 `data/source`에 보관한 뒤 실행합니다.

```powershell
python migration.py --reset
```

처리 흐름은 다음과 같습니다.

```text
원본 보존 → Parsing → Validation → Normalization → SQLite → Import Report
```

파일명 자체가 아니라 Sheet 조합으로 Workbook 역할을 판별합니다. 의미를 자동 확정할 수 없는 값은 삭제하지 않고 `unresolved_imports`에 `Needs Review`로 남깁니다.

`--reset`은 현재 DB를 원본 기준으로 다시 생성하므로, 사용자 입력 데이터가 있다면 먼저 화면의 `데이터·백업`에서 백업해야 합니다.

## 테스트

```powershell
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

자동 테스트는 운영 시나리오, 게시판 상태·백업·중복 방지, Google Sheets 동기화 안전성, 전체 메뉴 UI 렌더링을 확인합니다.

## 데이터와 보안

- 원본 XLSX는 덮어쓰거나 삭제하지 않습니다.
- 원본 `나스` 시트의 계정·비밀번호는 DB에 가져오지 않았습니다.
- 해당 비밀번호는 노출된 것으로 간주해 즉시 변경하고, 암호 관리 도구로 이전해야 합니다.
- 개인별 출석을 추적하지 않고 예배별 집계만 사용합니다.
- 대표 인원 지표는 주일 현장 참석입니다. 온라인 값은 집계 정의가 확정되기 전까지 별도 지표로 표시하며, 현장과의 합산값은 중복 가능성이 있는 참고치입니다.
- Google Sheets 원본은 읽기 전용이며, 앱의 동기화 코드는 원본 값을 수정하지 않습니다.
- 현재는 별도 로그인·역할 권한이 없습니다. 공개 URL을 알고 있는 사람은 게시글과 댓글을 등록할 수 있으므로, 팀 내부에만 링크를 공유하세요.
- 게시판 외의 행사·매뉴얼 수정·운영 로그는 Streamlit Cloud의 로컬 SQLite에 저장되어 재부팅·재배포 후 유지가 보장되지 않습니다. 중요한 내용은 백업을 내려받으세요.

## 배포 방법

### 1. 한 대의 PC에서 사용

`run.bat`으로 실행하는 가장 단순한 방식입니다. DB와 백업이 해당 PC에 저장됩니다.

### 2. 교회 내부망에서 공동 사용

항상 켜져 있는 내부 Windows PC나 소형 서버에서 다음과 같이 실행합니다.

```powershell
python -m streamlit run app.py --server.address=0.0.0.0 --server.port=8766
```

같은 사설망에서 `http://서버IP:8766`으로 접속합니다. 운영 시에는 Windows 방화벽을 교회 내부망 범위로만 열고 정기 JSON 백업을 다른 장치에 복사하세요.

### 3. 외부 접속이 필요한 운영 배포

SQLite 파일이 유지되는 단일 VM/서버와 HTTPS 역방향 프록시 구성이 가장 단순합니다. 공용 배포 전에는 로그인과 접근제어를 추가해야 합니다. 여러 사용자의 동시 편집이 늘어나면 SQLite를 Postgres/Supabase로 옮기는 것이 다음 단계입니다.

## 현재 제한과 V2/V3

V2 후보:

- Pending Decision 전용 화면과 Waiting For
- Exception Rules
- 구성원·대표기도·헌금위원 고도화
- Supplies
- Incident 전용 분석
- Evidence Timeline
- 역할별 Dashboard와 Handover
- 로그인 및 간단한 역할 권한

V3 후보:

- Attendance Forecast
- YouTube API
- 자연어 Knowledge Search
- 과거 회고 기반 체크리스트 추천
- 배차 시스템 연동

현재 데이터와 발견사항은 [DATA_INVENTORY.md](docs/DATA_INVENTORY.md), 관계형 구조는 [ARCHITECTURE.md](docs/ARCHITECTURE.md)를 참고하세요.
