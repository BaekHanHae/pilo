# PILO

**AI 코딩 작업을 위한 로컬 프로젝트 문맥·근거 보존·복구 도구입니다.**

[English](README.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

PILO는 AI 코딩 도구가 프로젝트 자료를 찾고, 실제로 읽은 내용을 기록하도록 돕습니다. 프로젝트별 권한, 변경되지 않는 문맥 Snapshot, 선택적인 로컬 분석을 하나의 Python 앱으로 제공합니다.

**현재 상태:** 0.3.1 공개 전 시험 버전입니다. 로컬 자동 테스트를 수행했으며, 모든 환경의 안정성이나 검색 정확성을 보장하지 않습니다. GitHub 공개 CI는 아직 실행하지 않았습니다.

## 무엇을 할 수 있나요?

- 허용된 UTF-8 프로젝트 파일을 색인하고 키워드로 검색합니다.
- 검색 문맥과 출처 해시를 Snapshot으로 보존하고 읽을 때 권한을 다시 확인합니다.
- 로컬 STDIO 방식으로 MCP 클라이언트에 연결합니다.
- 선택적으로 Ollama 의미 검색·AI 분석, Graphify Python 관계 분석을 사용합니다.
- 검토된 코드 작업과 깨끗한 Git 상태의 Checkpoint·복구를 운영자 API로 사용합니다. 기본 MCP 연결에서는 프로젝트를 변경하는 작업을 허용하지 않습니다.

예를 들어 저장소를 색인한 뒤 checkpoint 관련 자료를 검색하고, 나중에 같은 Snapshot을 읽어 당시 근거를 확인할 수 있습니다.

## 빠른 시작

Python 3.11 이상, Git, JSON 함수와 FTS5 trigram을 지원하는 SQLite 3.37 이상이 필요합니다. macOS 또는 Linux를 대상으로 하며, 로컬 검증은 macOS에서 수행했습니다. Linux CI는 준비 상태이고 Windows는 현재 지원하지 않습니다.

압축을 푼 소스 폴더에서 실행하세요.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/pilo init --directory .pilo
.venv/bin/pilo --config .pilo/database_config.json add-project --key sample --name Sample --root examples/sample-project
.venv/bin/pilo --config .pilo/database_config.json search --project sample --query checkpoint
```

마지막 명령은 검색 내용·Snapshot ID·출처 경로·완료 상태를 반환합니다. 결과가 없거나 예산 때문에 일부만 포함되면 이를 표시합니다. 초기화는 기존 설치를 덮어쓰지 않습니다.

자신의 프로젝트에는 `add-project`의 경로와 프로젝트 키를 바꾸세요. 이 명령은 로컬 운영자의 명시적인 등록·색인 작업입니다. 전용 읽기 계정을 설정하고, 임시 색인 계정은 작업 후 비활성화합니다.

## 코딩 도구에 연결하기

실행 파일의 절대 경로로 `pilo --config /absolute/path/to/.pilo/database_config.json serve`를 실행하도록 로컬 STDIO MCP를 설정합니다. 기본 연결은 프로젝트 목록·상세·문맥 검색·Snapshot 읽기만 제공합니다. 설정 예시는 영어 [MCP 명세](docs/mcp.md)에 있습니다. 클라우드 클라이언트에서 로컬 프로세스에 접근할 수 있다고 가정하지 않습니다.

## 선택 기능과 범위

- **의미 검색:** Ollama 임베딩과 cosine 순위. 검색 가능한 단위 512개까지이며 호출할 때 계산합니다.
- **AI 분석:** 보존된 Snapshot을 로컬 모델로 분석합니다. 답변 구조·출처 검사를 하더라도 사실 정확성은 별도 검토가 필요합니다.
- **관계 분석:** Graphify로 Python 구조를 분석합니다. 파일 100개·소스 2 MB까지 지원합니다.
- **복구:** 깨끗한 Git 상태를 기준으로 하며 Git 객체와 보존된 콘텐츠가 필요합니다.

기본 설치에는 모델·클라우드 계정·API 키·Graphify가 필요하지 않습니다. 추가 설정은 영어 [확장 안내](docs/extensions.md)를 확인하세요.

## 문서와 라이선스

공식 명세는 **영어로만 유지**합니다. 한국어·일본어 README는 소개와 사용 안내입니다. [명세](docs/specification.md), [로드맵](docs/roadmap.md), [검증 범위](docs/verification.md)를 참고하세요.

PILO 자체 코드·문서는 [MIT](LICENSE)입니다. 외부 의존성에는 별도 라이선스가 적용됩니다. Graphify의 Apache-2.0 등은 [외부 라이선스 고지](THIRD_PARTY_NOTICES.md)에 정리합니다. 모델 가중치·개인 데이터·비공개 대화 원문은 배포하지 않습니다.
