# 지시서 12호 — pilo evaluate_checkout 실패 진단 (수정 금지, 진단 전용)

> 시작 전 확인된 현재 상태 (Muse 검증 2026-11-14):
> - `tools/evaluate_checkout.py`는 **이 repo 자체를 색인**해 8개 어휘 쿼리를 돌리고, 각 쿼리의 검색 내용(상한 32768 토큰)에 기대 파일 표기 `[경로]`가 들어 있는지를 단언한다. 쿼리 쌍: checkpoint→README.md / Snapshot·permission·SQLite→docs/specification.md / Graphify·semantic→docs/extensions.md / pilo_get_context→docs/mcp.md / readme→CONTRIBUTING.md.
> - `docs/specification.md`는 **main(4,103 바이트)과 PR 브랜치 양쪽에 존재한다.** 파일 부재가 아니다.
> - 실패 런 43459423395에서 코덱스가 확인한 실패는 쿼리 'SQLite' → docs/specification.md 누락. 10호 진단 때는 main과 커밋 7b753ad 복사본 모두 로컬에서 이 평가를 **통과**했다 — 상태 의존 또는 환경 의존이다.
> - PR 브랜치: feature/pilo-skills-ai-gateway, HEAD 47bf9d1. PR은 드래프트 유지.

## 진단 순서
1. **실패 런 로그에서 AssertionError의 JSON을 확보**한다 — 8개 중 어떤 케이스가, 어떤 항목(has_source / nonempty / snapshot_equal / status)으로 실패했는지. specification.md를 기대하는 3개(Snapshot·permission·SQLite) 전부인지, 'SQLite'만인지가 첫 갈림길이다. 대기 중이던 macOS 3.11 조합의 최종 결과도 확인한다.
2. **로컬 재현**: PR 브랜치 HEAD에서 `python tools/evaluate_checkout.py`를 그대로 실행하고, 케이스별 표를 만든다. 같은 실행을 한 번 더 해 결정성이 있는지도 본다. 대조군으로 main에서도 실행한다.
3. 재현되면 **층을 분리**한다:
   - (i) 색인 층: specification.md가 색인됐는가 (indexed_files 수, 색인 내 해당 파일 청크 유무).
   - (ii) 내용 층: PR 브랜치의 specification.md가 main과 어떻게 다른가 — 특히 'SQLite' 언급이 줄거나 사라졌는가 (diff).
   - (iii) 순위 층: 'SQLite' 쿼리가 실제로 무엇을 반환했는가, specification.md 청크는 몇 위인가. 진단 목적으로 토큰 상한을 올렸을 때 나타나는지 확인만 한다 (도구 수정 아님).
4. 로컬에서 재현이 안 되면 **환경 축**을 본다: fresh checkout과의 차이(파일 열거 순서, .gitignore, 로컬에만 있는 생성 파일), Python/SQLite 버전 차이.

## 금지
- 파일 변경 일절 금지 (도구·단언·운영 코드·문서·픽스처 전부). 보고는 이 세션 답변으로만 한다.
- 추측을 원인으로 단정하지 않는다. 원인 후보마다 확신도와, 확정하려면 어떤 증거가 필요한지를 붙인다.

## 보고 형식
(a) 결과 요약 — 실패 케이스 전체 목록과 층 판정(색인/내용/순위/환경)
(b) 근거 — 로그 인용, 로컬 실행 표(main vs PR, 2회), diff 요약
(c) 미확인 사항과 수정 방향 후보 (실행하지 않음)
