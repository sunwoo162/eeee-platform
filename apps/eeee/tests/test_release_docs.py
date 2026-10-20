from pathlib import Path


REQUIRED_FILES = ("LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "docs/RELEASE.md")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_release_governance_files_exist():
    for filename in REQUIRED_FILES:
        assert (PACKAGE_ROOT / filename).is_file(), filename


def test_release_docs_describe_install_test_security_and_manual_release():
    content = "\n".join((PACKAGE_ROOT / filename).read_text(encoding="utf-8") for filename in REQUIRED_FILES)
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "MIT License" in content
    assert "python -m pytest" in content or "python -m pytest" in readme
    assert "security" in content.lower()
    assert "manual" in content.lower()
    assert "Gleave" in content or "Gleave" in readme


def test_core_verification_docs_match_current_runtime():
    architecture = (REPOSITORY_ROOT / "docs/architecture.md").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    script = (REPOSITORY_ROOT / "scripts/verify-core-product.ps1").read_text(encoding="utf-8")

    assert "현재 `EEEE` 저장소에는 ClaimLatch를 직접 import하거나 호출하는 통합 계층이 아직 없다." not in architecture
    assert "apps/eeee/app/integrations/claimlatch_client.py" in architecture
    assert "scripts/verify-core-product.ps1" in readme
    assert "pytest" in script
    assert "git diff --check" in script
    assert "UTF-8" in script


def test_encoding_check_is_part_of_repository_verification():
    checker = (REPOSITORY_ROOT / "scripts/check-encoding.py").read_text(encoding="utf-8")

    assert '"git", "ls-files"' in checker
    assert "UTF-8 BOM found" in checker
    assert "replacement/mojibake marker found" in checker
    assert "strict UTF-8" in checker
