# Gleave 개발 방향성 점검 01 — Chat-scoped Workspace

기준: 2026-10-27
결론: **목표와 일치. P0 백엔드 구현 수준. 전체 제품 완성 아님.**

## 사용자 목표 대조
| 핵심 요구 | 현재 결과 | 다음 단계 |
| --- | --- | --- |
| 하나의 ChatGPT형 UI | 기존 EEEE 대화 API 보존 | 새 데스크톱 채팅 UI |
| 개인/팀 > 프로젝트 > 채팅 | SQLite v6 데이터/REST 구현 | 사이드바/드래그앤드롭 |
| 폴더의 다른 채팅에서도 같은 기억 | 같은 프로젝트의 승인 메모리/자신의 최근 타 채팅 참조 | relevance retrieval/출처 UI |
| 프로젝트 간 기억 격리 | 링크 이동·기억 scope 검사와 테스트 | 기존 레거시 memory scope 데이터 migration |
| GPT·Claude·Codex 수동/Auto | 아직 미구현 | Provider Hub 및 per-turn mode |
| Codex 실작업, 터미널, 미리보기 | 기존 ISEOL 기반만 보존 | 권한/실행/검증 E2E |
| 자체 LLM 사용자 승인 학습 | 기존 독립 학습 엔진 보존 | 평가·승인 데이터 연동 |

## 검증
- git worktree feat/unified-chat 사용; 원래 gleave-merge-clean / eeee-platform / eeee-personal-llm 변경 안 함.
- WorkspaceStore unit + API + ConversationContextBuilder 관련 테스트 81개 통과.
- 원본 채팅은 ConversationStore에서 그대로 저장/재생. 폴더 연결과 curated memory는 추가 테이블.
- 현 단계에서는 팀 멤버 초대 API 없음. X-EEEE-User-Id는 로컬 스코프이지 네트워크에서 인증된 신원이 아님.
- 승인되지 않은 타 채팅 발화는 참고 자료일 뿐 확정된 프로젝트 사실이 아님.
- 실제 외부 AI 연결, Windows 패키징, 전체 테스트/CI는 아직 수행하지 않음.

## 다음 스프린트의 거절 기준
- 채팅 UI가 모델마다 별도 대화로 분리된다면 목표와 불일치.
- 모델을 전환할 때 프로젝트 ID/공용 기억이 사라진다면 목표와 불일치.
- 팀 폴더에 개인 전역 기억 또는 타 구성원 비공유 원문이 들어가면 차단.
- 개발 작업의 실제 성공 여부를 AI 텍스트로만 선언한다면 차단.
- 학습/데이터 수집이 사용자 승인이나 타사 출력의 이용 제한을 우회하면 차단.

## P1 수용 조건
1. Gleave 한 창에서 일반 채팅·프로젝트 이동·하위 채팅 목록 표시.
2. HTTP/SSE 응답을 requestId 기반으로 정확히 보여주고 실패·취소 복구.
3. 폴더 이동 직후 다음 요청의 프로젝트 기억 범위가 바뀌고 다른 프로젝트 기억 없음.
4. 한 채팅의 user-selected model override UI는 고정 계약으로 설계하되 미연결 제공자를 완료로 표시하지 않음.
