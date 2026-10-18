"""Deterministic natural-language project intake for the native ISEOL lane."""

from __future__ import annotations

import re

from app.iseol.contracts import (
    ClarificationQuestion,
    ExternalAction,
    IntakeResult,
    ProjectIntent,
)


_WEB_MARKERS = ("웹", "website", "web app", "webapp", "홈페이지", "사이트")
_MEAL_MARKERS = ("식단", "식사", "메뉴")
_TODO_MARKERS = ("todo", "할 일", "할일", "체크리스트")
_EXTERNAL_MARKERS = {
    "배포": ("deployment", "실제 운영 배포"),
    "깃허브": ("github", "GitHub 저장소 연결"),
    "github": ("github", "GitHub 저장소 연결"),
    "노션": ("notion", "Notion 문서 연결"),
    "notion": ("notion", "Notion 문서 연결"),
    "메일": ("mail", "메일 계정 연결"),
}
_VAGUE_REQUESTS = {"이거 해줘", "저거 해줘", "해줘", "do it", "do that"}


class NaturalLanguageIntake:
    """Extract safe defaults without invoking an LLM or an external connector."""

    @classmethod
    def parse(cls, text: str) -> IntakeResult:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Request text cannot be blank")
        normalized = " ".join(text.split())
        folded = normalized.casefold()
        meal = any(marker.casefold() in folded for marker in _MEAL_MARKERS)
        todo = any(marker.casefold() in folded for marker in _TODO_MARKERS)
        web = any(marker.casefold() in folded for marker in _WEB_MARKERS)
        vague = normalized.casefold() in {item.casefold() for item in _VAGUE_REQUESTS}

        if meal and (web or "만들" in normalized or "앱" in normalized):
            project_type, template_id = "web_app", "meal_planner"
        elif todo and (web or "앱" in normalized or "만들" in normalized):
            project_type, template_id = "todo_app", "todo_app"
        elif web or ("앱" in normalized and "만들" in normalized):
            project_type, template_id = "web_app", "generic_web"
        elif todo:
            project_type, template_id = "todo_app", "todo_app"
        else:
            project_type, template_id = "unknown", None

        external_actions = cls._external_actions(normalized)
        questions: list[ClarificationQuestion] = []
        if vague or project_type == "unknown":
            questions.append(ClarificationQuestion(
                id="project-purpose",
                prompt="무엇을 만들거나 처리하면 될지 한 문장으로 알려줘.",
                reason="프로젝트 유형과 핵심 결과물을 판단할 정보가 부족해.",
            ))

        intent = ProjectIntent(
            rawText=text,
            goal=cls._goal(normalized),
            projectType=project_type,
            templateId=template_id,
            constraints=["local-first", "UTF-8 text", "responsive UI"] if project_type != "unknown" else [],
            assumptions=["local-first", "mobile-first", "외부 플러그인 없이 먼저 실행"] if project_type != "unknown" else [],
            acceptanceCriteria=cls._acceptance_criteria(project_type),
            riskLevel="medium" if external_actions else "low",
            requiresExternalApproval=bool(external_actions),
            externalActions=external_actions,
        )
        return IntakeResult(intent=intent, questions=questions, ready=not questions)

    @staticmethod
    def _goal(normalized: str) -> str:
        goal = re.sub(r"(?:만들어\s*줘|만들어|생성해\s*줘|작성해\s*줘)$", "", normalized).strip()
        return goal or normalized

    @staticmethod
    def _acceptance_criteria(project_type: str) -> list[str]:
        if project_type == "unknown":
            return []
        return [
            "사용자가 요청한 핵심 흐름이 동작함",
            "실행 가능한 결과물과 로컬 실행 방법이 제공됨",
            "테스트·검증 결과와 남은 제한사항이 기록됨",
            "UTF-8·반응형·접근성 기본 검사를 수행함",
        ]

    @staticmethod
    def _external_actions(text: str) -> list[ExternalAction]:
        actions: list[ExternalAction] = []
        seen: set[str] = set()
        folded = text.casefold()
        for marker, (kind, description) in _EXTERNAL_MARKERS.items():
            if marker.casefold() not in folded or kind in seen:
                continue
            seen.add(kind)
            actions.append(ExternalAction(
                id=f"external:{kind}",
                kind=kind,
                description=description,
                status="awaiting_approval",
                requiresApproval=True,
            ))
        return actions
