# ZERO SEO OS frontend

React + TypeScript + Vite 대시보드입니다. 기존 PC 실행과 데이터 보관 안내는 [프로젝트 README](../README.md)를 참조하세요. 중앙 운영 준비 문서는 [중앙 전환 설계](../docs/중앙운영-전환설계.md)에 있습니다.

## 개발자 검증

frontend에서 실행합니다.

```sh
npm ci
npm test
npm run build
npm run lint
```

중앙 개발 의존성은 프로젝트 최상위에서 `python -m pip install -r backend/requirements-central-dev.txt`로 설치합니다. 서버 회귀는 프로젝트 최상위에서 `python -m unittest discover -s backend -q`로 실행합니다. 테스트는 실제 WordPress 인증정보 없이 모의 외부 요청과 임시 DB를 사용합니다.

## 테스트 종류

| 도구 | 파일 | 검증 범위 |
|---|---|---|
| Vitest + jsdom | tests/*.test.tsx | 화면 상태·등록·복원·모의 API 응답 |
| Playwright | tests/*.spec.ts | 실제 브라우저와 로컬 서버 흐름 |

실제 브라우저 테스트와 DOM 테스트는 파일 탐색을 분리합니다.

```sh
npm run test:e2e -- --list
```

목록은 regression.spec.ts의 E2E 2개를 표시해야 합니다. 목록 성공은 브라우저 실행 성공을 의미하지 않습니다.

E2E 실행은 두 로컬 서버(화면 5173, 연결 8765)가 켜져 있고 Playwright용 Chromium을 사용할 수 있는 개발 환경에서 `npm run test:e2e`로 수행합니다. 시스템 Chromium이 있는 Linux 개발 환경은 ZERO_TEST_CHROMIUM에 실행 파일 경로를 지정할 수 있습니다. 이 Work 환경에서는 Chromium 실행이 OS socket 권한 오류로 차단돼 E2E 전체 검증은 완료되지 않았습니다.

E2E는 임시 브라우저 프로필을 사용하지만 로컬 서버에 샘플 사이트·키워드·작업 저장본을 추가합니다. 개인 운영 DB와 분리된 개발용 서버에서 실행하세요. 실제 WordPress 인증정보를 테스트 서버에 설정하지 않습니다. 제품 데이터와 테스트 데이터를 함께 지우는 초기화 명령은 제공하지 않습니다.

## 현재 연결 방식

대시보드는 127.0.0.1:5173에서 실행되고 API 주소 127.0.0.1:8765를 호출합니다. 이는 로컬 테스트용입니다. 중앙 운영에서는 로그인·사용자별 권한·서버 저장을 갖춘 같은 출처 API로 전환해야 하며, Host/Origin 허용 범위를 넓히는 것만으로 서비스를 공개하지 않습니다.

## 별도 중앙 진입점

Vite 빌드는 기존 index.html과 새 central.html을 함께 만듭니다. central.html은 서비스 로그인 및 서버 데이터 기반 화면이고 기존 App의 localStorage 흐름과 분리됩니다. 중앙 API와 같은 HTTPS 출처에서 실행해야 Secure 쿠키가 작동합니다. 기존 로컬 Vite 실행만으로 중앙 API가 자동 준비되지는 않습니다. 중앙 코드·서버 환경·실제 미구현 범위는 [중앙 기반 구현](../docs/중앙기반-v0.3.0-구현.md)을 참조하세요. 중앙 DOM 회귀는 central.test.tsx에 있습니다.
