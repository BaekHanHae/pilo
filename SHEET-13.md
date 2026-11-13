# 지시서 13호 — pilo 검색: 핵심 문서 가중치 (lexical 랭킹)

> 시작 전 확인된 현재 상태 (Muse 검증 2026-11-14, 코드 직접 열람):
> - 랭킹 지점: `pilo_core/workspace.py`의 `Workspace.retrieve()` lexical 분기. 후보 정렬 키는 `(not mandatory, not exact, not lexical, row[4], row[0])`이며, 상위 100개 후보를 그 순서대로 32,768 토큰 예산에 채우고 넘치면 EXCLUDED(status PARTIAL)가 된다. row[4]=파일의 logical_path, row[5]=knowledge_type (파일은 None).
> - 진단 (12호): query 'SQLite'에서 docs/specification.md가 밀려난 층이 바로 이 정렬+예산 층이다. 파일·색인은 정상.
> - 핵심 문서 클래스: 평가가 기대하는 5개 소스(README.md, CONTRIBUTING.md, docs/specification.md, docs/extensions.md, docs/mcp.md)는 전부 **루트 *.md 또는 docs/ 아래 *.md** 이다.
> - 작업 브랜치: feature/pilo-skills-ai-gateway (PR #1). PR 드래프트 유지, 병합 금지.

## 변경 (범위는 여기까지)
1. **canonical 티어 추가**: row[4] 경로가 루트 *.md이거나 docs/ 아래 *.md이면 canonical로 판정하고, 정렬 키에서 mandatory·exact 다음, lexical 앞에 새 티어를 넣는다: `(not mandatory, not exact, not canonical, not lexical, row[4], row[0])`. 후보 포함 조건(mandatory/exact/lexical/FTS 게이트)은 바꾸지 않는다 — canonical은 후보 사이의 **순서만** 바꾼다.
2. **랭커 버전 표기**: ContextSnapshot에 기록되는 `'deterministic-v1'`을 `'deterministic-v2'`로 올린다 (기존 관행).
3. **QueryCache 정합성 확인**: cache_key는 (query, scope, policy, gens, strategy)로 만들어져 코드 버전을 포함하지 않는다. 기존 상태 DB에서 변경 전 후보 순서가 캐시로 계속 나올 수 있는지 확인하고, 그럴 수 있으면 cache_key 재료에 랭커 버전을 포함시키는 것까지를 이번 변경에 넣는다. 기존 무효화 장치가 따로 있으면 그것을 쓰고, 어느 쪽이든 결과를 보고한다.

## 금지
- `tools/evaluate_checkout.py`와 그 단언 수정 (그건 기각된 방향 1이다).
- 파일명('specification.md')·쿼리('SQLite') 하드코딩. 규칙은 경로 클래스만으로 정의한다.
- 코퍼스 제외(.gitignore 등), semantic 랭커(`_semantic_rank`) 변경 — 범위 밖.

## 완료 조건
- PR 브랜치 코퍼스에서 `tools/evaluate_checkout.py` **8/8 통과, 2회 연속**.
- 대조: 패치된 코드로 **main 코퍼스**를 평가해 8/8 (Graphify 케이스 포함)을 목표로 한다. 실패하면 가중치를 임의로 더 키우지 말고, 순위 근거를 보고한다.
- 전체 유닛 테스트 155개 통과 (Python 3.11·3.14), 기존 retrieve 관련 테스트(test_workspace·test_extensions·test_distribution) 회귀 없음.
- CI: PR 런 4개 조합 녹색 (러너 대기로 미실행인 조합은 실패와 구분해 표기).
- 전후 비교 보고: 'SQLite' 쿼리에서 specification.md 청크의 후보 순위·선택 여부 변화, 순서가 달라진 다른 쿼리 목록.

## 보고 형식
(a) 결과 요약 (완료 조건별, 런 URL 포함)
(b) 변경한 파일 목록과 이유 (커밋 단위)
(c) 미확인·남은 의문
