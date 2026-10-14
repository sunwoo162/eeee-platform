from app.desktop.session import DesktopSession


class FakeDesktopClient:
    def __init__(self):
        self.project_ids = []
        self.routed = []

    def get_desktop_state(self, project_id=None):
        self.project_ids.append(project_id)
        return {"status": "ok", "projectId": project_id, "claimLatch": {"status": "advisory"}}

    def route_assistant(self, text, workspace=None):
        self.routed.append((text, workspace))
        return {"status": "ready", "project_id": "project-1", "message": "created"}

    def issue_pairing_code(self):
        return {"code": "123456", "expiresAt": "later"}


class BackgroundDesktopClient(FakeDesktopClient):
    def __init__(self):
        super().__init__()
        self.job = {"jobId": "assistant-job-1", "status": "running", "result": None}

    def route_assistant(self, text, workspace=None):
        self.routed.append((text, workspace))
        return {"status": "accepted", "jobId": "assistant-job-1", "message": "started"}

    def get_assistant_job(self, job_id):
        assert job_id == "assistant-job-1"
        return self.job


class SynchronousProjectResponseClient(FakeDesktopClient):
    def route_assistant(self, text, workspace=None):
        return {
            "status": "blocked",
            "project_id": "project-1",
            "message": "프로젝트 설정이 더 필요해.",
        }


class MissingProfileClient(FakeDesktopClient):
    def get_desktop_state(self, project_id=None):
        raise RuntimeError("Project profile not found")


def test_session_refreshes_selected_project_and_keeps_last_snapshot():
    client = FakeDesktopClient()
    session = DesktopSession(client)

    snapshot = session.refresh("project-1")

    assert snapshot["projectId"] == "project-1"
    assert session.project_id == "project-1"
    assert session.snapshot is snapshot


def test_session_routes_through_eeee_then_refreshes_the_created_project():
    client = FakeDesktopClient()
    session = DesktopSession(client)

    snapshot = session.route("Build a web app", "C:/work")

    assert client.routed == [("Build a web app", "C:/work")]
    assert client.project_ids == ["project-1"]
    assert snapshot["assistantRoute"]["status"] == "ready"
    assert session.project_id == "project-1"


def test_session_pairing_code_does_not_store_or_return_an_access_token():
    session = DesktopSession(FakeDesktopClient())

    pairing = session.issue_pairing_code()

    assert pairing == {"code": "123456", "expiresAt": "later"}


def test_session_keeps_accepted_background_job_visible_until_it_finishes():
    client = BackgroundDesktopClient()
    session = DesktopSession(client)

    accepted = session.route("Todo 앱 만들어줘")
    assert accepted["state"] == "working"
    assert accepted["assistantJobId"] == "assistant-job-1"

    client.job = {
        "jobId": "assistant-job-1",
        "status": "completed",
        "result": {"project_id": "project-1", "message": "완료"},
    }
    finished = session.refresh()

    assert finished["state"] == "completed"
    assert finished["projectId"] == "project-1"
    assert finished["message"] == "완료"


def test_session_projects_scheduled_and_running_job_states_for_quick_chat():
    client = BackgroundDesktopClient()
    session = DesktopSession(client)
    session.route("Todo 앱 만들어줘")

    client.job = {"jobId": "assistant-job-1", "status": "scheduled", "result": None}
    scheduled = session.refresh()
    assert scheduled["state"] == "scheduled"
    assert "예약" in scheduled["message"]

    client.job = {"jobId": "assistant-job-1", "status": "running", "result": None}
    running = session.refresh()
    assert running["state"] == "working"
    assert "진행" in running["message"]


def test_session_does_not_present_blocked_background_result_as_completed():
    client = BackgroundDesktopClient()
    session = DesktopSession(client)
    session.route("로그인 기능이 있는 Todo 웹앱 만들어줘")

    client.job = {
        "jobId": "assistant-job-1",
        "status": "completed",
        "result": {
            "status": "awaiting_configuration",
            "project_id": "project-1",
            "message": "로컬 검증은 끝났고 외부 연결 설정이 필요해.",
        },
    }
    finished = session.refresh()

    assert finished["state"] == "blocked"
    assert "외부 연결" in finished["message"]


def test_session_keeps_synchronous_project_blocked_response_visible():
    session = DesktopSession(SynchronousProjectResponseClient())

    snapshot = session.route("프로젝트 설정 확인")

    assert snapshot["state"] == "blocked"
    assert snapshot["message"] == "프로젝트 설정이 더 필요해."


def test_session_keeps_synchronous_configuration_response_blocked():
    client = SynchronousProjectResponseClient()
    client.route_assistant = lambda text, workspace=None: {
        "status": "awaiting_configuration",
        "project_id": "project-1",
        "message": "외부 연결 설정이 필요해.",
    }
    session = DesktopSession(client)

    snapshot = session.route("로그인 Todo 프로젝트")

    assert snapshot["state"] == "blocked"
    assert snapshot["message"] == "외부 연결 설정이 필요해."


def test_session_keeps_assistant_response_when_status_refresh_loses_project_profile():
    session = DesktopSession(MissingProfileClient())

    snapshot = session.route("안녕")

    assert snapshot["assistantRoute"]["status"] == "ready"
    assert snapshot["message"] == "created"
