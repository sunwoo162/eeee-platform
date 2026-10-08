"""Evidence-backed portfolio documents for an existing Project Runtime."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PortfolioGenerationResult:
    status: str
    message: str
    artifacts: list[dict[str, Any]]
    source_paths: list[str]


class PortfolioGenerator:
    """Generate portfolio prose without inventing unverified project claims."""

    SOURCE_FILES = (
        "PROJECT_PROFILE.json",
        "PROJECT_LOG.md",
        "DESIGN.md",
        "QA_REPORT.json",
        "RELEASE_MANIFEST.json",
        "execution-plan.json",
    )
    OUTPUT_FILES = (
        "PORTFOLIO.md",
        "TECHNICAL_RETROSPECTIVE.md",
        "RESUME_SUMMARY.md",
        "INTERVIEW_ANSWERS.md",
    )

    def generate(self, project_id: str, project_revision: str, workspace: Path) -> PortfolioGenerationResult:
        root = Path(workspace).resolve()
        profile_path = root / "PROJECT_PROFILE.json"
        if not profile_path.is_file():
            return PortfolioGenerationResult(
                "blocked",
                "포트폴리오를 만들 근거가 없어. PROJECT_PROFILE.json을 먼저 생성해야 해.",
                [],
                [],
            )
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return PortfolioGenerationResult("blocked", f"프로젝트 프로필을 읽지 못했어: {exc}", [], [])
        if profile.get("projectId") not in {None, project_id}:
            return PortfolioGenerationResult("blocked", "프로젝트 프로필의 projectId가 현재 프로젝트와 달라.", [], [])
        if profile.get("projectRevision") not in {None, project_revision}:
            return PortfolioGenerationResult("blocked", "프로젝트 프로필의 revision이 현재 프로젝트와 달라.", [], [])

        sources: dict[str, str] = {}
        for name in self.SOURCE_FILES:
            path = root / name
            if path.is_file():
                try:
                    sources[name] = path.read_text(encoding="utf-8")
                except OSError:
                    continue
        qa = _json_source(sources.get("QA_REPORT.json"))
        release = _json_source(sources.get("RELEASE_MANIFEST.json"))
        goal = str(profile.get("goal") or "기록된 프로젝트")
        qa_status = str(qa.get("status") or qa.get("qualityStatus") or "검증 상태 미기록")
        claim = qa.get("claimLatch") if isinstance(qa.get("claimLatch"), dict) else {}
        claim_status = str(claim.get("decision") or qa.get("claimLatchDecision") or "검증 상태 미기록")
        evidence_lines = "\n".join(f"- `{name}`" for name in sources)
        troubleshooting = _section(sources.get("PROJECT_LOG.md", ""), "Troubleshooting")
        if not troubleshooting:
            troubleshooting = "기록된 트러블슈팅 섹션이 없습니다. 확인되지 않은 문제 해결 사례는 추가하지 않았습니다."

        documents = {
            "PORTFOLIO.md": (
                f"# {goal} — 포트폴리오\n\n"
                f"- Project ID: `{project_id}`\n- Revision: `{project_revision}`\n"
                f"- QA: **{qa_status}**\n- ClaimLatch: **{claim_status}**\n- Release: **{release.get('status', '미기록')}**\n\n"
                "## 문제와 해결\n\n" + troubleshooting + "\n\n"
                "## 검증된 근거\n\n" + evidence_lines + "\n\n"
                "이 문서는 로컬 프로젝트 기록과 검증 산출물만 바탕으로 생성되었습니다. 기록되지 않은 성능·사용자 수·배포 사실은 주장하지 않습니다.\n"
            ),
            "TECHNICAL_RETROSPECTIVE.md": (
                f"# 기술 회고 — {goal}\n\n"
                f"## 검증 상태\n- QA: **{qa_status}**\n- ClaimLatch: **{claim_status}**\n\n"
                "## 트러블슈팅 기록\n\n" + troubleshooting + "\n\n"
                "## 참고 산출물\n\n" + evidence_lines + "\n"
            ),
            "RESUME_SUMMARY.md": (
                "# 이력서용 요약\n\n"
                f"- **프로젝트:** {goal}\n- **구현/운영 근거:** 로컬 Project Runtime 기록과 릴리스 산출물\n"
                f"- **품질 검증:** QA `{qa_status}`, ClaimLatch `{claim_status}`\n"
                "- **주의:** 실제 기록에 없는 수치와 결과는 기재하지 않음\n"
            ),
            "INTERVIEW_ANSWERS.md": (
                "# 면접 설명용 답변\n\n"
                f"## 무엇을 만들었나요?\n{goal}을 구현한 프로젝트입니다.\n\n"
                "## 어떻게 품질을 확인했나요?\n"
                f"프로젝트에 저장된 QA 결과는 `{qa_status}`, ClaimLatch 판정은 `{claim_status}`입니다. 관련 원문은 아래 근거 파일에서 확인할 수 있습니다.\n\n"
                "## 어떤 문제를 해결했나요?\n\n" + troubleshooting + "\n\n"
                "## 근거 파일\n\n" + evidence_lines + "\n"
            ),
        }
        artifacts: list[dict[str, Any]] = []
        for name, content in documents.items():
            path = root / name
            path.write_text(content, encoding="utf-8", newline="\n")
            artifacts.append({"path": str(path), "kind": "portfolio", "encoding": "utf-8"})
        return PortfolioGenerationResult("completed", "검증된 프로젝트 기록으로 포트폴리오 문서를 생성했어.", artifacts, list(sources))


def _json_source(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _section(value: str, title: str) -> str:
    marker = f"## {title}"
    if marker not in value:
        return ""
    section = value.split(marker, 1)[1]
    return section.split("\n## ", 1)[0].strip(" \n#")
