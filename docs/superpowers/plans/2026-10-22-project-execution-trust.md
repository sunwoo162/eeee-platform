# 프로젝트 실행 검증 신뢰성 보강 계획

## 목표

브라우저 UI E2E가 실행되지 않은 웹 프로젝트를 독립 QA `PASS` 또는 릴리스 완료로 표시하지 않는다. 로컬 API·정적 검사는 계속 결과를 제공하되, 검증 범위를 사용자에게 정확히 드러내고 브라우저 검증이 끝나기 전에는 최종 릴리스를 차단한다.

## 범위

1. 브라우저 E2E `not_run` 결과를 QA 보고서 `WARN`으로 기록한다.
2. 준비 단계에서는 API·정적 결과를 확인할 수 있도록 WARN 보고서를 반환한다.
3. 브라우저 계약이 없는 템플릿은 `NOT_APPLICABLE`로 명시하고, 실제 미실행(`NOT_RUN`)과 구분한다.
4. 최종화 단계에서는 QA가 PASS이고 browserVerification이 PASS 또는 NOT_APPLICABLE일 때만 릴리스한다.
5. 품질 프로파일과 ClaimLatch가 준비 단계의 명시적 WARN 및 NOT_APPLICABLE을 구분해 평가하도록 한다.
6. 브라우저 미실행·미적용·최종 릴리스 차단을 회귀 테스트로 고정한다.

## 완료 조건

- `browserVerification=NOT_RUN`인 보고서의 `status`가 PASS가 아니다.
- ClaimLatch가 PASS여도 browser E2E 미실행 프로젝트는 릴리스되지 않는다.
- 지원하지 않는 템플릿은 `NOT_APPLICABLE`로 기록되고, 그 사실이 최종 보고서의 제한사항에 남는다.
- 브라우저가 PASS인 기존 정상 경로는 계속 릴리스된다.
- 전체 EEEE 테스트와 인코딩 검사가 통과한다.
