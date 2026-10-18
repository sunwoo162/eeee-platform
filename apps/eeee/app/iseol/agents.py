"""Concrete ISEOL agent graph contracts.

The graph is deliberately provider-neutral: a node is an executable role with
an explicit dependency and handoff boundary, not merely a label in a report.
The runtime adapter may use a hosted model, a local model, or a deterministic
worker, but it must return the same evidence-bearing contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AgentStatus = Literal["pending", "ready", "running", "passed", "warn", "blocked", "failed"]


class AgentNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(min_length=1)
    task_id: str = Field(alias="taskId", min_length=1)
    role: str = Field(min_length=1)
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    phase: str = "implementation"
    acceptance_criteria: list[str] = Field(default_factory=list, alias="acceptanceCriteria")
    system_prompt: str = Field(default="", alias="systemPrompt")
    dependencies: list[str] = Field(default_factory=list)
    validators: list[str] = Field(default_factory=list)
    extension_ids: list[str] = Field(default_factory=list, alias="extensionIds")
    side_effect_level: Literal["none", "local_write", "external_write"] = Field(
        default="none", alias="sideEffectLevel"
    )
    allowed_tools: list[str] = Field(default_factory=list, alias="allowedTools")
    execution_policy: Literal["claimlatch_before_handoff"] = Field(
        default="claimlatch_before_handoff", alias="executionPolicy"
    )
    status: AgentStatus = "pending"


class AgentGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal["iseol-agent-graph.v1"] = Field(alias="schemaVersion")
    goal: str = Field(min_length=1)
    agents: list[AgentNode] = Field(min_length=1)
    context: dict[str, object] = Field(default_factory=dict)

    @property
    def task_ids(self) -> list[str]:
        return [agent.task_id for agent in self.agents]

    def by_id(self, agent_id: str) -> AgentNode:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        raise KeyError(f"Agent not found: {agent_id}")


class AgentTeamFactory:
    """Build the default specialist team for a software project."""

    @staticmethod
    def default_graph(goal: str) -> AgentGraph:
        return AgentGraph(
            schemaVersion="iseol-agent-graph.v1",
            goal=goal,
            agents=[
                AgentNode(id="requirements", taskId="requirements", role="requirements", title="Requirements Agent", goal="확정 요구사항과 완료 조건을 만든다.", acceptanceCriteria=["요구사항과 비기능 제약이 명시됨", "검증 가능한 완료 조건이 있음"], systemPrompt="제품 요구사항 분석가로서 모호한 요구를 검증 가능한 조건으로 바꿔라. 요구사항 문서를 workspace에 기록해 다음 에이전트가 확인할 수 있게 하라.", allowedTools=["workspace.read", "workspace.write", "memory.search"]),
                AgentNode(id="research", taskId="research", role="research", title="Product Research Agent", goal="사용자 맥락과 유사 제품의 검증 가능한 기준을 정리한다.", acceptanceCriteria=["대상 사용자와 핵심 시나리오가 명시됨", "참고 근거와 차별화 결정이 기록됨"], systemPrompt="제품 리서처로서 추측을 사실처럼 쓰지 말고 근거·가정·미결정 사항을 분리하라. 조사 결과와 근거를 workspace에 기록해 다음 에이전트가 확인할 수 있게 하라.", dependencies=["requirements"], allowedTools=["workspace.read", "workspace.write", "memory.search"]),
                AgentNode(id="design", taskId="design", role="design", title="Design Agent", goal="디자인 시스템과 화면 구조를 결정한다.", acceptanceCriteria=["화면 상태와 반응형 규칙이 정의됨", "기본 디자인 토큰을 따름"], systemPrompt="제품 디자이너로서 접근성·반응형·상태 화면까지 설계하라.", dependencies=["requirements", "research"], allowedTools=["workspace.read", "workspace.write"]),
                AgentNode(id="architecture", taskId="architecture", role="architecture", title="Architecture Agent", goal="FSD 경계와 확장 가능한 기술 구조를 확정한다.", acceptanceCriteria=["레이어 책임과 의존 방향이 문서화됨", "플러그인·데이터·UI 경계가 분리됨"], systemPrompt="아키텍트로서 기능을 한 파일에 몰아넣지 말고 FSD 또는 동등한 경계를 증거로 남겨라.", dependencies=["requirements", "research"], allowedTools=["workspace.read", "workspace.write"]),
                AgentNode(id="frontend", taskId="frontend", role="frontend", title="Frontend Agent", goal="사용자 인터페이스와 반응형 동작을 구현한다.", acceptanceCriteria=["핵심 사용자 흐름이 동작함", "모바일·데스크톱 레이아웃이 검증됨"], systemPrompt="시니어 프론트엔드 엔지니어로서 유지보수 가능한 FSD 구조와 접근성 UI를 구현하라.", dependencies=["requirements", "design", "architecture"], allowedTools=["workspace.read", "workspace.write", "command.test"]),
                AgentNode(id="backend", taskId="backend", role="backend", title="Backend Agent", goal="도메인 로직과 API를 구현한다.", acceptanceCriteria=["도메인 규칙이 테스트됨", "실패 응답과 입력 검증이 있음"], systemPrompt="시니어 백엔드 엔지니어로서 도메인 경계와 오류 처리를 명확히 구현하라.", dependencies=["requirements", "architecture"], allowedTools=["workspace.read", "workspace.write", "command.test"]),
                AgentNode(id="data", taskId="data", role="data", title="Data Agent", goal="데이터 모델과 영속 저장을 구현한다.", acceptanceCriteria=["데이터 모델과 마이그레이션이 있음", "새로고침 후 데이터가 보존됨"], systemPrompt="데이터 엔지니어로서 데이터 무결성·영속성·마이그레이션을 검증하라.", dependencies=["requirements", "backend", "architecture"], allowedTools=["workspace.read", "workspace.write", "command.test"]),
                AgentNode(id="accessibility", taskId="accessibility", role="accessibility", title="Accessibility Agent", goal="반응형·키보드·스크린리더 사용성을 검증한다.", acceptanceCriteria=["필수 뷰포트가 검증됨", "키보드 포커스와 이름 있는 컨트롤이 있음"], systemPrompt="접근성 전문가로서 시각적 완성도만 보지 말고 실제 입력 장치와 좁은 화면의 실패를 검증하라.", dependencies=["design", "frontend"], allowedTools=["workspace.read", "workspace.write", "command.test"]),
                AgentNode(id="security", taskId="security", role="security", title="Security Agent", goal="입력·비밀·권한·의존성 위험을 독립 점검한다.", acceptanceCriteria=["사용자 입력이 안전하게 처리됨", "비밀과 위험한 명령이 릴리스에 없음"], systemPrompt="보안 리뷰어로서 코드와 실행 증거를 대조하고 위험을 WARN이 아니라 재현 가능한 결과로 기록하라.", dependencies=["backend", "data"], allowedTools=["workspace.read", "workspace.write", "command.test"]),
                AgentNode(id="test", taskId="test", role="test", title="Test Agent", goal="단위·통합·E2E·반응형 검증을 작성하고 실행한다.", acceptanceCriteria=["핵심 흐름의 자동 테스트가 있음", "회귀·반응형 검증 결과가 증거로 남음"], systemPrompt="독립 테스트 엔지니어로서 사용자 시나리오와 실패 경로를 먼저 검증하라.", dependencies=["frontend", "backend", "data"], allowedTools=["workspace.read", "workspace.write", "command.test"]),
                AgentNode(id="review", taskId="review", role="review", title="Review Agent", goal="코드 품질·보안·구조·인코딩을 독립 검토한다.", acceptanceCriteria=["보안·인코딩·구조 검토가 완료됨", "차단 이슈가 해결되거나 명시됨"], systemPrompt="신선한 컨텍스트의 엄격한 코드 리뷰어로서 구현자의 주장과 실제 diff를 대조하라.", dependencies=["frontend", "backend", "data", "security"], allowedTools=["workspace.read", "workspace.write", "command.test"]),
                AgentNode(id="documentation", taskId="documentation", role="documentation", title="Documentation Agent", goal="실행법·결정·트러블슈팅·변경 기록을 남긴다.", acceptanceCriteria=["처음 보는 개발자가 실행 가능함", "왜 그렇게 만들었는지와 실패 대응이 기록됨"], systemPrompt="기술 문서 작성자로서 README만 복사하지 말고 결정·실패·검증 근거를 연결하라.", dependencies=["requirements", "design", "architecture", "review"], allowedTools=["workspace.read", "workspace.write"]),
                AgentNode(id="integration", taskId="integration", role="integration", title="Integration Agent", goal="검증된 결과를 통합하고 릴리스 산출물을 만든다.", acceptanceCriteria=["전체 빌드와 릴리스 산출물이 생성됨", "모든 선행 검증이 PASS임"], systemPrompt="릴리스 엔지니어로서 검증된 산출물만 통합하고 재현 가능한 실행 절차를 남겨라.", dependencies=["test", "review", "accessibility", "security", "documentation"], allowedTools=["workspace.read", "command.test", "workspace.write"]),
            ],
        )
