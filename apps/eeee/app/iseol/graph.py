"""Native, intent-driven compilation of the ISEOL project DAG."""

from __future__ import annotations

from collections import deque

from app.iseol.agents import AgentGraph, AgentNode
from app.iseol.contracts import ProjectIntent
from app.iseol.extensions import ExtensionRegistry


class AgentGraphCompiler:
    """Compile only the specialist graph required by one project intent."""

    @classmethod
    def compile(
        cls,
        intent: ProjectIntent,
        extensions: ExtensionRegistry,
        *,
        catalog: list[AgentNode] | None = None,
    ) -> AgentGraph:
        nodes = list(catalog or _core_catalog())
        _validate_catalog(nodes)
        required_capabilities = []
        if intent.template_id and intent.template_id not in {"todo_app", "generic_web"}:
            required_capabilities.append(
                f"project.template.{intent.template_id.replace('_', '-')}"
            )
        selected = extensions.select(required_capabilities)
        selected_ids = [manifest.id for manifest in selected]
        missing = extensions.missing(required_capabilities)
        ordered = _topological_order(nodes)
        if {node.id for node in ordered} < {"review", "integration"}:
            raise ValueError("compiled graph requires review and integration gates")
        phases = list(dict.fromkeys(node.phase for node in ordered))
        context = {
            "canonicalIntent": f"project.create.{intent.project_type}",
            "templateId": intent.template_id,
            "assumptions": list(intent.assumptions),
            "selectedExtensions": selected_ids,
            "missingExtensions": missing,
            "phases": phases,
        }
        return AgentGraph(
            schemaVersion="iseol-agent-graph.v1",
            goal=intent.goal,
            agents=ordered,
            context=context,
        )


def _node(
    id: str,
    role: str,
    phase: str,
    goal: str,
    dependencies: list[str] | None = None,
    *,
    validators: list[str] | None = None,
    side_effect_level: str = "none",
) -> AgentNode:
    return AgentNode(
        id=id,
        taskId=id,
        role=role,
        title=f"{role.title()} Agent",
        goal=goal,
        phase=phase,
        dependencies=dependencies or [],
        validators=validators or [],
        sideEffectLevel=side_effect_level,
        acceptanceCriteria=[f"{role} 산출물이 검증 가능하게 기록됨"],
        systemPrompt=f"{role} 전문 담당자로서 근거와 미결정 사항을 분리하고 산출물을 남겨라.",
        allowedTools=["workspace.read", "workspace.write"],
    )


def _core_catalog() -> list[AgentNode]:
    return [
        _node("intake", "intake", "intake", "자연어 요청과 원문을 보존한다."),
        _node("definition", "definition", "definition", "프로젝트 목표와 범위를 확정한다.", ["intake"]),
        _node("research", "research", "definition", "사용자 맥락과 근거를 정리한다.", ["definition"]),
        _node("requirements", "requirements", "requirements", "요구사항과 완료 조건을 만든다.", ["definition", "research"]),
        _node("content", "content", "content", "콘텐츠와 상태별 문구를 설계한다.", ["requirements"]),
        _node("information_architecture", "information_architecture", "information_architecture", "정보 구조와 탐색 흐름을 정한다.", ["content"]),
        _node("ux", "ux", "ux", "핵심 사용자 여정과 실패 흐름을 설계한다.", ["information_architecture"]),
        _node("ui", "ui", "ui", "화면 구성과 반응형 규칙을 정한다.", ["ux"]),
        _node("architecture", "architecture", "technical_design", "기술 경계와 확장 구조를 설계한다.", ["requirements", "research"]),
        _node("environment", "environment", "environment", "재현 가능한 개발·검증 환경을 준비한다.", ["architecture"]),
        _node(
            "frontend", "frontend", "implementation", "사용자 인터페이스를 구현한다.",
            ["requirements", "ui", "architecture", "environment"],
            validators=["test", "accessibility", "review"],
            side_effect_level="local_write",
        ),
        _node(
            "backend", "backend", "implementation", "도메인 로직과 API를 구현한다.",
            ["requirements", "architecture", "environment"],
            validators=["test", "security", "review"],
            side_effect_level="local_write",
        ),
        _node(
            "data", "data", "implementation", "영속 데이터 모델을 구현한다.",
            ["backend"],
            validators=["test", "security", "review"],
            side_effect_level="local_write",
        ),
        _node("test", "test", "testing", "단위·통합·E2E 검증을 실행한다.", ["frontend", "backend", "data"]),
        _node("accessibility", "accessibility", "testing", "접근성과 반응형 동작을 검증한다.", ["ui", "frontend"]),
        _node("security", "security", "testing", "입력·비밀·권한·의존성을 점검한다.", ["backend", "data"]),
        _node("review", "review", "release", "구조·품질·인코딩과 차단 이슈를 검토한다.", ["frontend", "backend", "data", "test", "accessibility", "security"]),
        _node("documentation", "documentation", "operations", "실행법·결정·제한사항을 기록한다.", ["requirements", "review"]),
        _node("integration", "integration", "release", "검증된 결과를 통합하고 릴리스한다.", ["test", "review", "documentation"]),
    ]


def _validate_catalog(nodes: list[AgentNode]) -> None:
    ids = [node.id for node in nodes]
    task_ids = [node.task_id for node in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate agent id in catalog")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("duplicate task id in catalog")
    known = set(ids)
    for node in nodes:
        unknown = (set(node.dependencies) | set(node.validators)) - known
        if unknown:
            raise ValueError(f"unknown graph reference for {node.id}: {sorted(unknown)}")


def _topological_order(nodes: list[AgentNode]) -> list[AgentNode]:
    by_id = {node.id: node for node in nodes}
    incoming = {node.id: set(node.dependencies) for node in nodes}
    reverse: dict[str, list[str]] = {node.id: [] for node in nodes}
    for node in nodes:
        for dependency in node.dependencies:
            reverse[dependency].append(node.id)
    ready = deque(node.id for node in nodes if not incoming[node.id])
    ordered: list[AgentNode] = []
    while ready:
        current = ready.popleft()
        ordered.append(by_id[current])
        for dependent in reverse[current]:
            incoming[dependent].remove(current)
            if not incoming[dependent]:
                ready.append(dependent)
    if len(ordered) != len(nodes):
        raise ValueError("cycle detected in agent graph")
    return ordered
