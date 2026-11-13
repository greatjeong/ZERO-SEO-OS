# Render 장기 운영 배포 준비

2026-11-13 · 본인용 비공개 + React/Python + Render 유료 웹 서비스 + 관리형 PostgreSQL 기준

## 사용자 결정과 현재 증거

사용자는 Cloudways가 테스트 WordPress 호스팅일 뿐이라고 정정한 뒤 Python 유지와 Render 장기 운영 추천을 수락하고 계정 가입·로그인을 완료했다. 제공한 Render 화면에는 서비스가 아직 없었다. 이 Work에 Render 계정 조작 권한이 연결됐다는 증거는 없으며, 브라우저에서 로그인한 사실을 자동 API 접근으로 간주하지 않는다.

서버 추가·DB 생성·실제 배포·카드 등록·유료 과금은 수행하지 않았다. render.yaml은 생성할 구성의 검토 가능한 준비물이며 적용 전 실제 가격·사양 화면을 확인한다. 기존 WordPress·초안 737/738·PC .state는 변경하지 않았다.

## 추가한 코드

- central_store.py: SQLAlchemy Core를 사용해 개발 SQLite와 운영 PostgreSQL을 지원한다. PostgreSQL은 psycopg와 TLS를 사용한다. 유효한 DB URL이 있으면 SQLite로 자동 대체하지 않는다.
- 버전별 workspace 저장, 로그인 제한, 세션·저장본 조회를 공통 저장 계층으로 분리했다. 기존 SQLite schema=1의 데이터·revision은 그대로 읽으며 자동 삭제·형식 교체하지 않는다.
- PostgreSQL 저장·로그인 제한·초기 스키마 생성은 각각 transaction advisory lock으로 직렬화한다. 저장 전 revision 비교와 과거 저장본 보존을 유지한다.
- 원문 DB URL·서비스 비밀번호는 Settings repr, 쿼리 파라미터 로그, API 응답에 노출하지 않는다. 구성·DB 초기화 오류도 비밀 값을 포함하지 않는 메시지로 반환한다.
- Render의 내부 DB 연결 URL은 fromDatabase로 참조하고 sslmode=require를 기본 적용한다. verify-ca/verify-full은 허용하지만 disable/allow/prefer는 거부한다.
- 서비스 출처는 명시적 ZERO_CENTRAL_ORIGIN이 우선이고, 없으면 Render 제공 RENDER_EXTERNAL_URL을 사용한다. 사용자의 요청 Host를 서비스 출처로 신뢰하지 않는다.

## 이번 배포 제안 자원

| 항목 | 준비된 값 | 목적 |
|---|---|---|
| 웹 서비스 | zero-seo-os, Python, starter/0.5c-512mb, 1 instance | React 빌드 파일과 FastAPI를 같은 HTTPS 출처에서 제공 |
| DB | zero-seo-os-db, basic-256mb/0.1c-256mb, PostgreSQL 18 | 장기 데이터·세션·버전별 저장본 |
| 지역 | 둘 다 Singapore | 같은 지역 내부 연결 |
| DB 공간 | 1GB 명시 | 공급자 기본 15GB로 생성되는 것을 피함. 필요 시 증설 |
| DB 외부 접근 | ipAllowList: [] | Render 내부 연결만 사용 |
| 자동 배포 | off | GitHub 변경만으로 운영 서비스가 임의 재배포되지 않음 |
| 로그인 비밀 | ZERO_OWNER_PASSWORD, sync:false | 사용자가 Render 비밀 설정에 입력. 소스·대화에 입력하지 않음 |
| 앱 파일 저장 디스크 | 없음 | 서버 데이터는 관리형 DB로 저장. 임시 로컬 파일을 원본으로 쓰지 않음 |

기본 컴퓨팅 공개 가격은 웹 $7 + DB $6 = $13/월이다. 실제 DB 저장공간 과금/포함량, 세금·초과 대역폭·빌드·AI 사용료는 최종 생성 화면에서 확인한다. 이 표는 무제한 가격 보장이나 결제 승인 기록이 아니다. Render의 starter/basic 이름은 현재 새 plan ID와 매핑되는 호환 이름이다.

## 안전한 초기 로그인 설정

Render Blueprint 설정 시 서비스 전용 비밀번호를 ZERO_OWNER_PASSWORD 비밀 칸에 12~256자로 입력한다. WordPress 앱 비밀번호와 다른 용도다. 원문은 Render 프로세스 환경에서만 읽고 scrypt 해시를 메모리에 생성한다. Git·DB·응답에 원문을 저장하지 않는다. 기본 비밀번호는 없다.

고정된 scrypt 해시를 운영자가 미리 준비한 경우 ZERO_OWNER_PASSWORD_HASH를 사용할 수 있으며 해시가 우선한다. 원문 환경변수 방식은 프로세스 재시작 때 임의 salt가 바뀌어 기존 세션이 만료된다. 다시 로그인하면 DB에 보존된 데이터가 보이며 데이터 삭제를 뜻하지 않는다. 로그인 정보 재입력 없이 모든 재시작을 통과해야 하는 요구가 생기면 안전하게 생성한 고정 해시로 전환한다.

## 검증

- backend 테스트 73개: 기존 기능, 중앙 세션·저장·충돌·보존, PostgreSQL TLS URL 검증, Postgres SQL dialect 컴파일·바인딩, 기존 SQLite 이력 보존, Render 환경·YAML 비밀/외부 접근/과금 자원 설정 검사.
- 기존 실제 PostgreSQL 서버가 이 작업 환경에 없으므로 PostgreSQL 실접속·트랜잭션·관리형 DB 재시작 시험은 아직 하지 않았다. SQLite 회귀와 SQL 컴파일을 실 DB 시험으로 표현하지 않는다.
- PostgreSQL 생성 후 내부 TLS 접속·health의 database=postgresql·로그인·실제 저장/재조회·동시 저장 충돌·재배포 후 유지 여부를 확인한다. 이 확인 전 사용자 원본 이관 완료를 선언하지 않는다.
- 중앙 화면 WordPress 자격·연결·초안 이관은 아직 별도 남은 구현이다. 배포 기반 준비와 전체 제품 완료를 구분한다.

## 다음 화면부터 순서

1. Render 왼쪽 Blueprints 화면에서 새 Blueprint 흐름을 연다. 아직 Apply/생성·결제는 누르지 않는다.
2. GitHub 연결이 필요하면 greatjeong/ZERO-SEO-OS 저장소에 필요한 범위만 사용한다. 전체 저장소 권한을 기본으로 요청하지 않는다.
3. 준비된 render.yaml의 두 자원·지역·사양·금액을 검토한다. 서비스 비밀번호는 Render 비밀 입력 칸에서만 입력한다.
4. 사용자 비용 확인 후 생성·배포를 진행한다. 실패한 생성이 있어도 같은 이름 자원을 반복 추가하지 않고 기존 상태부터 확인한다.
5. 배포 URL에서 본인 로그인과 PostgreSQL 저장·재시작 보존을 확인한다. 개인정보·비밀번호·DB URL이 없는 결과만 공유한다.

이 절차는 계정 가입이나 고정된 제품 구조를 다시 질문하는 것이 아니라 실제 유료 자원을 생성하기 위한 마지막 확인이다. 소개 홈페이지·App·SaaS 세 역할과 Python 유지 기준은 변경하지 않는다.

## 공식 확인 자료

- https://render.com/docs/blueprint-spec — fromDatabase, autoDeployTrigger, DB diskSizeGB, 외부 IP 차단
- https://render.com/docs/postgresql-creating-connecting — 내부 주소 및 TLS require
- https://render.com/docs/python-version — .python-version의 minor 지정 지원
- https://render.com/pricing — 공개 가격. 실제 계정 생성 화면에서 최종 재확인

실행 시 준비된 requirements-central.txt와 frontend 빌드를 사용한다. 개별 PC에 새 설치·파일 교체를 요청할 단계가 아니다.
