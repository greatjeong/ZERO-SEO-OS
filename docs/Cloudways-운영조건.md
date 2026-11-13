# 본인용 비공개·Cloudways 선택과 운영 조건 확인

2026-11-13 · 사용자 선택 기록 및 사전 조사. 계정의 실제 서버 점검·지원 답변·배포 완료가 아님.

## 확정된 사용자 선택

- 첫 중앙 버전은 사용자 본인만 사용하는 비공개 서비스로 시작한다.
- 호스팅 제공자는 Cloudways를 사용하기를 원한다.
- 특정 서버·애플리케이션·상품·서비스 주소·API 실행 방식·DB 제품은 아직 정해지지 않았다.
- 기존 WordPress 사이트를 변경하거나 새 유료 서버를 생성하는 작업은 실행하지 않았다.

이 선택은 중앙 API의 언어 변경이나 Python 별도 호스팅 비용을 자동 승인한 것으로 해석하지 않는다. 기존 Python 코어·로컬 검증 결과는 보존한다. 기술 주 단계는 A-02 진행 중이다.

## 공식 안내 조사

1. Cloudways 지원 앱 목록은 WordPress, WooCommerce, Magento, Laravel, Custom PHP 및 PHP 기반 앱을 중심으로 안내한다.
   - https://support.cloudways.com/en/articles/5134108-which-web-applications-can-be-hosted-on-cloudways
2. Cloudways DigitalOcean 관리형 호스팅 FAQ에는 Python 기반 애플리케이션을 지원하지 않는다는 안내가 있다. 해당 FAQ의 일부 버전 예시는 오래된 내용이므로 이 한 페이지를 모든 현재 상품의 한계로 단정하지 않는다.
   - https://www.cloudways.com/en/digital-ocean-cloud-hosting.php
3. 관리형 서버의 root 권한은 제공하지 않는다. 일반 VPS처럼 임의 systemd·Nginx 설정을 수정할 수 있다고 가정하지 않는다.
   - https://support.cloudways.com/en/articles/5134090-why-can-t-i-have-root-access-to-my-server
4. 공식 Supervisord 문서는 Laravel/Custom PHP 앱의 Laravel queue 운영을 설명한다. Python 웹 서버를 플랫폼 UI에서 관리할 수 있다는 근거로 확대 해석하지 않는다.
   - https://support.cloudways.com/en/articles/5127434-how-to-configure-laravel-supervisord-on-cloudways
5. 현재 Cloudways 메인 페이지에는 별도 Node.js 호스팅 안내도 존재한다. 따라서 제공자의 이름만으로 사용자의 현재 상품·허용 런타임을 확정할 수 없다. Node 지원을 Python 지원으로 해석하지 않는다.
   - https://www.cloudways.com/en/
6. 전용 Cloudways 연결 플러그인은 이번 검색 결과에서 찾지 못했다. GitHub 연결이 Cloudways 서버 접근 권한을 제공하지는 않는다.

결론: Cloudways를 쓰고 싶다는 사용자 선택은 확정됐지만 기존 Python API의 운영 가능성은 미확인이다. SSH에서 python 명령이 실행되는 것과 HTTPS API를 상시·재부팅 후·플랫폼 지원 범위 내에서 운영하는 것은 다르다.

## 다음 확인 — 한 화면부터

사용자가 Cloudways의 서버 목록/선택 서버 화면을 제공하면 상품 종류와 기존 서버 사용 의도를 확인한다. 비밀번호·API 키·DB 자격·Master Credentials는 보여주거나 채팅에 붙여넣을 필요가 없다. 이 화면만으로 세부 Python 운영 권한을 검증 완료로 표시하지 않는다.

그 다음 필요 범위는 애플리케이션 단위의 접근과 지원 여부다. 서버 전체 Master 권한부터 요청하지 않는다. 계정 접근이 없으면 공식 지원에 확인할 구체 질문을 준비하되 사용자를 대신해 메시지를 보내지는 않는다.

필수 운영 조건:

- 지원되는 Python 버전·가상환경·패키지 설치 범위가 있는가.
- Python API 프로세스가 터미널 종료·서버 재시작 후에도 지원되는 방식으로 실행되는가.
- 같은 HTTPS 서비스 주소에서 /api를 안전하게 라우팅할 수 있는가. 커스텀 포트를 공개하는 것으로 대신하지 않는다.
- 서버 비밀 저장·키 관리와 DB·백업을 운영할 권한이 있는가.
- 기존 사이트와 별도 애플리케이션·권한으로 격리할 수 있는가.
- 운영상 지원 범위·비용·제약은 무엇인가.

## 지원 결과에 따른 선택지 — 구현 전 합의 필요

| 선택지 | 유지되는 것 | 추가 결정·작업 |
|---|---|---|
| Cloudways가 해당 상품에서 Python 상주 API를 공식 지원 | React·Python 코어 대부분 | 지원되는 프로세스 관리·HTTPS 라우팅·DB·비밀 저장 확인 |
| Cloudways에서 PHP/Laravel API로 중앙 운영 | React UI와 기존 기능·데이터 계약 | Python API를 PHP로 이식하는 주요 아키텍처 변경. 사용자 합의 및 전체 연결 회귀 필요 |
| Cloudways는 웹 서비스, Python API는 별도 지원 환경 | Python 코어 재사용 | 별도 운영 환경·비용·서버 간 인증·라우팅 합의 필요 |

어느 선택지도 아직 실행하지 않았다. 제공자 선택만으로 언어 재작성 또는 추가 유료 자원 사용을 확정하지 않는다. 서비스 주소 역시 아직 예시만 있으며 DNS·SSL·새 앱 생성은 수행하지 않았다.
