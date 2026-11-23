# Railway 환경변수 진단 · 2026-11-23

사용자 스크린샷에서 앱 DB 참조식과 DB 원본 변수 모두 존재함을 확인. 단 반복 실행 로그는 from_env에서 DATABASE_URL 누락/빈 값으로 중단. 참조식 재입력은 원인 해결 근거가 없어 중단함.

Railway 공식 변수 문서는 실행 시 환경변수 주입과 staged changes 배포 필요성을 설명함. Docker ARG는 빌드 시 사용에만 필요하며 runtime DB 비밀을 이미지에 넣지 않음. 원인을 아직 확정하지 못함.

시작 시 ZERO_RUNTIME_CONFIG 로그를 추가. 고정된 7개 키의 absent/empty/unresolved_reference/present 상태만 출력하고 값·전체 환경·DB 주소·비밀번호는 출력하지 않음. 사용자 설정·실제 DB 데이터·WordPress는 변경하지 않음. 실제 배포 로그로 이후 판별 필요. A-02 진행 중.
