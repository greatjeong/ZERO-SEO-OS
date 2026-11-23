# Railway 실행 환경 수정 · 2026-11-23

사용자 배포 로그에서 Build 통과 후 uvicorn: command not found 확인. Python 설치와 프런트 빌드를 수행한 자동 감지 이미지의 실행 환경 불일치를 해소하기 위해 Node 빌드 단계와 Python 실행 단계를 명시한 Dockerfile 및 railway.json 추가.

기존 코드·DB·.state·WordPress 기록은 변경하지 않음. 컨테이너에는 로컬 상태/비밀 파일을 복사하지 않음. 필수 환경변수 DATABASE_URL, ZERO_OWNER_PASSWORD(12자 이상), ZERO_CENTRAL_ORIGIN(실제 HTTPS origin)은 Railway에서 설정. WP 키와 SerpApi는 별도 단계. 실제 Docker 빌드는 이 작업 환경에 Docker가 없어 미검증이며 Railway Build/Deploy 로그로 후속 검증 필요. A-02 진행 중 유지, 운영 성공을 주장하지 않음.
