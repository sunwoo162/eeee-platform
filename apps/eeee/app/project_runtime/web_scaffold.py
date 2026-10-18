from __future__ import annotations

import json
from pathlib import Path


def create_web_app_scaffold(workspace: str | Path, project_name: str) -> list[Path]:
    """Create a credential-free full-stack web project boundary."""

    root = Path(workspace)
    files = {
        "README.md": f"""# {project_name}

Gleave가 생성한 배포 준비형 웹앱 프로젝트입니다. 로컬 demo auth로 즉시 실행할 수 있으며, production OAuth와 데이터베이스는 환경변수 설정 후 연결합니다.

## 로컬 실행

```bash
python apps/api/server.py
```

브라우저에서 `http://127.0.0.1:8787`을 엽니다.

## 구조

- `apps/web`: FSD 기반 프론트엔드
- `apps/api`: 로컬 API와 저장소 경계
- `packages/auth`: demo/production 인증 계약
- `packages/db`: SQLite/production DB 교체 지점
- `DEPLOYMENT.md`: 배포 전 설정과 검증 절차
""",
        "DESIGN.md": """# 웹앱 디자인·구조 결정

- Stayfolio 계열의 카드와 넓은 여백을 사용하되, 작업 생성·완료·수정·삭제 상태를 우선한다.
- 한국어를 기본으로 하고, 320px·390px·768px·1440px에서 정보 순서가 유지되도록 한다.
- `apps/web/src`는 app/pages/entities/shared 경계를 유지하고, API 호출은 shared API 모듈을 통과한다.
- Demo 로그인은 실제 OAuth 성공으로 표시하지 않으며 production credential이 없으면 `awaiting_configuration`으로 남긴다.
""",
        "PROJECT_LOG.md": """# 프로젝트 작업 기록

## 결정

- 로컬에서 외부 credential 없이 실행 가능한 demo auth와 SQLite를 기본으로 선택했다.
- production OAuth·DB는 connector 설정과 독립 QA가 끝나기 전까지 완료로 표시하지 않는다.

## 트러블슈팅

- 인증과 데이터 연결이 없는 상태를 로그인 성공으로 위장하지 않도록 health/session 응답에 모드를 남긴다.
- 사용자 입력은 API에서 검증하고 화면에서는 `textContent`로 렌더링한다.
""",
        "tests/e2e/web-flow.md": """# Web E2E 시나리오

1. health와 demo session을 확인한다.
2. Todo 생성·조회·완료·수정·삭제를 확인한다.
3. 검색·필터·통계를 확인한다.
4. 새로고침 후 SQLite 데이터가 유지되는지 확인한다.
5. Google OAuth가 설정되지 않은 상태는 `awaiting_configuration`으로 표시되는지 확인한다.
6. 320px, 390px, 768px, 1440px에서 읽기 순서와 키보드 포커스를 확인한다.
""",
        "tests/integration/api-contract.md": """# API 통합 계약

- `GET /api/health`는 실행 모드와 인증 설정 상태를 반환한다.
- 로그인 전 Todo API는 `401 login_required`를 반환한다.
- 빈 제목은 `400 title_required`로 거부한다.
- Todo CRUD 후 통계가 동일한 데이터로 갱신된다.
""",
        ".env.example": """# Local mode is safe without provider credentials.
APP_ENV=local
API_HOST=127.0.0.1
API_PORT=8787
DATABASE_URL=sqlite:///./data/app.sqlite3
AUTH_MODE=demo
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
SESSION_SECRET=replace-in-production
PUBLIC_APP_URL=http://127.0.0.1:8787
""",
        ".gitignore": """.env
data/
__pycache__/
*.py[cod]
""",
        "Dockerfile": """FROM python:3.12-slim

WORKDIR /app
COPY . .
EXPOSE 8787
ENV API_HOST=0.0.0.0 API_PORT=8787 AUTH_MODE=demo
CMD ["python", "apps/api/server.py"]
""",
        "docker-compose.yml": """services:
  app:
    build: .
    ports:
      - "8787:8787"
    env_file: .env
    volumes:
      - app-data:/app/data
volumes:
  app-data:
""",
        "DEPLOYMENT.md": f"""# {project_name} 배포 체크리스트

## 현재 상태

- 로컬 demo auth: 즉시 사용 가능
- 로컬 API와 SQLite 경계: 구현 대상
- Google OAuth: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` 설정 전까지 `awaiting_configuration`
- 공개 배포: 호스팅 연결 전까지 배포하지 않음

## 배포 전

1. `AUTH_MODE=production`과 OAuth callback URL을 설정합니다.
2. `SESSION_SECRET`을 새 값으로 설정하고 저장소에 커밋하지 않습니다.
3. production `DATABASE_URL`을 설정합니다.
4. `python -m pytest`와 브라우저 E2E를 실행합니다.
5. ClaimLatch release gate가 같은 project/revision에 대해 PASS인지 확인합니다.
6. 장애 시 직전 `RELEASE_MANIFEST.json`과 Git revision을 기준으로 rollback하고 결과를 `PROJECT_LOG.md`에 기록합니다.

EEEE는 외부 credential이 설정되지 않은 상태를 배포 완료로 보고하지 않습니다.
""",
        "apps/web/index.html": """<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Gleave Web App</title>
    <link rel="stylesheet" href="./src/shared/ui/styles.css" />
  </head>
  <body><main id="app"></main><script type="module" src="./src/app/main.js"></script></body>
</html>
""",
        "apps/web/src/app/main.js": """import { renderApp } from '../pages/home/ui.js';

renderApp(document.querySelector('#app'));
""",
        "apps/web/src/entities/todo/model.js": """export function normalizeTodo(todo) {
  return { id: String(todo.id), title: String(todo.title), completed: Boolean(todo.completed), priority: todo.priority || 'medium' };
}
""",
        "apps/web/src/shared/lib/api.js": """const API_BASE = window.GLEAVE_API_BASE || '';

export async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, { headers: { 'content-type': 'application/json', ...(options.headers || {}) }, ...options });
  if (!response.ok) throw new Error(`API request failed: ${response.status}`);
  return response.json();
}
""",
        "apps/web/src/pages/home/ui.js": """import { request } from '../../shared/lib/api.js';

export function renderApp(root) {
  root.innerHTML = `<section class="app-shell"><header><span class="logo">G</span><div><small>Gleave workspace</small><h1>나의 작업</h1></div><button id="login">Google로 로그인</button></header><div id="auth-status" class="notice">로컬 demo 모드로 준비 중...</div><section class="welcome"><strong>오늘의 우선순위를 정리해보세요.</strong><span>작은 작업부터 완료하면 진행률이 쌓입니다.</span></section><section class="stats" aria-label="진행률"><div><small>전체</small><strong id="stat-total">0</strong></div><div><small>진행 중</small><strong id="stat-active">0</strong></div><div><small>완료</small><strong id="stat-completed">0</strong></div><div><small>완료율</small><strong id="stat-rate">0%</strong></div></section><form id="todo-form"><input id="todo-title" required placeholder="새 작업을 입력하세요" aria-label="새 작업"><input id="todo-due" type="date" aria-label="마감일"><select id="todo-priority" aria-label="우선순위"><option value="medium">보통</option><option value="high">높음</option><option value="low">낮음</option></select><input id="todo-tags" placeholder="태그 (쉼표로 구분)" aria-label="태그"><button>추가</button></form><div class="toolbar"><input id="todo-search" placeholder="작업 검색" aria-label="작업 검색"><select id="todo-filter" aria-label="작업 필터"><option value="all">전체</option><option value="active">진행 중</option><option value="completed">완료</option></select></div><p id="empty-state" class="empty" hidden>아직 작업이 없습니다. 첫 작업을 추가해보세요.</p><ul id="todo-list" aria-live="polite"></ul></section>`;
  const list = root.querySelector('#todo-list'); const status = root.querySelector('#auth-status'); const form = root.querySelector('#todo-form'); const empty = root.querySelector('#empty-state');
  const state = { search: '', filter: 'all' };
  const paintStats = (stats) => { root.querySelector('#stat-total').textContent = stats.total; root.querySelector('#stat-active').textContent = stats.active; root.querySelector('#stat-completed').textContent = stats.completed; root.querySelector('#stat-rate').textContent = `${stats.rate}%`; };
  const paint = (todos) => { list.replaceChildren(); empty.hidden = todos.length > 0; todos.forEach((todo) => { const item = document.createElement('li'); item.dataset.id = todo.id; const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = todo.completed; checkbox.setAttribute('aria-label', `${todo.title} 완료`); checkbox.addEventListener('change', () => request(`/api/todos/${todo.id}`, { method: 'PATCH', body: JSON.stringify({ completed: checkbox.checked }) }).then(load)); const body = document.createElement('div'); body.className = 'todo-body'; const text = document.createElement('strong'); text.textContent = todo.title; if (todo.completed) text.className = 'done'; const meta = document.createElement('small'); meta.textContent = `${todo.priority} · ${todo.dueDate || '마감일 없음'} · ${(todo.tags || []).join(', ') || '태그 없음'}`; body.append(text, meta); const edit = document.createElement('button'); edit.className = 'quiet'; edit.textContent = '수정'; edit.setAttribute('aria-label', `${todo.title} 수정`); edit.addEventListener('click', () => { const title = window.prompt('작업 이름', todo.title); if (title && title.trim()) request(`/api/todos/${todo.id}`, { method: 'PATCH', body: JSON.stringify({ title: title.trim() }) }).then(load); }); const remove = document.createElement('button'); remove.className = 'danger quiet'; remove.textContent = '삭제'; remove.setAttribute('aria-label', `${todo.title} 삭제`); remove.addEventListener('click', () => { if (window.confirm('이 작업을 삭제할까요?')) request(`/api/todos/${todo.id}`, { method: 'DELETE' }).then(load); }); item.append(checkbox, body, edit, remove); list.append(item); }); };
  const load = () => request('/api/session').then((session) => { status.textContent = `${session.mode === 'demo' ? 'Demo 로그인' : 'Google 로그인'} · ${session.user.email}`; return Promise.all([request(`/api/todos?search=${encodeURIComponent(state.search)}&status=${state.filter}`), request('/api/todos/stats')]); }).then(([todos, stats]) => { paint(todos); paintStats(stats); }).catch((error) => { status.textContent = `연결 대기 중: ${error.message}`; });
  root.querySelector('#login').addEventListener('click', () => request('/api/session', { method: 'POST', body: JSON.stringify({ mode: 'demo' }) }).then(load));
  form.addEventListener('submit', (event) => { event.preventDefault(); const title = root.querySelector('#todo-title'); const dueDate = root.querySelector('#todo-due'); const priority = root.querySelector('#todo-priority'); const tags = root.querySelector('#todo-tags'); request('/api/todos', { method: 'POST', body: JSON.stringify({ title: title.value, dueDate: dueDate.value, priority: priority.value, tags: tags.value.split(',').map((tag) => tag.trim()).filter(Boolean) }) }).then(() => { form.reset(); load(); }); });
  root.querySelector('#todo-search').addEventListener('input', (event) => { state.search = event.target.value; load(); }); root.querySelector('#todo-filter').addEventListener('change', (event) => { state.filter = event.target.value; load(); }); load();
}
""",
        "apps/web/src/shared/ui/styles.css": """:root { font-family: Inter, Pretendard, system-ui, sans-serif; color: #172033; background: #f5f7fb; } * { box-sizing: border-box; } body { margin: 0; min-width: 320px; } .app-shell { width: min(920px, calc(100% - 32px)); margin: 48px auto; padding: 32px; border: 1px solid #e4e8f0; border-radius: 24px; background: #fff; box-shadow: 0 18px 55px #25304a12; } header { display: flex; align-items: center; gap: 14px; margin-bottom: 20px; } header small, .todo-body small { color: #7d8799; } h1 { margin: 5px 0 0; font-size: 34px; letter-spacing: -.06em; } .logo { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 14px; color: white; background: #172033; font-weight: 800; font-size: 22px; } header #login { margin-left: auto; border: 0; border-radius: 10px; padding: 11px 14px; color: #172033; background: #e9ebff; cursor: pointer; } .notice, .welcome { margin-bottom: 18px; padding: 12px 14px; border-radius: 10px; color: #407a58; background: #eaf8ef; font-size: 13px; } .welcome { display: grid; gap: 4px; color: #36415a; background: #f3f5ff; } .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; } .stats div { padding: 14px; border: 1px solid #e4e8f0; border-radius: 13px; } .stats small, .stats strong { display: block; } .stats small { color: #7d8799; } .stats strong { margin-top: 6px; font-size: 22px; } form, .toolbar { display: flex; gap: 9px; margin-bottom: 12px; } input, select, form button { border: 1px solid #dfe4ee; border-radius: 10px; padding: 13px; font: inherit; } form input:first-child { flex: 1; min-width: 0; } form button { border: 0; color: white; background: #172033; cursor: pointer; } .toolbar input { flex: 1; } ul { display: grid; gap: 10px; padding: 0; list-style: none; } li { display: flex; align-items: center; gap: 12px; padding: 15px; border: 1px solid #e4e8f0; border-radius: 13px; } li input { accent-color: #69c996; } .todo-body { display: grid; gap: 4px; flex: 1; min-width: 0; } .done { color: #929bad; text-decoration: line-through; } .quiet { border: 0; border-radius: 8px; padding: 8px 10px; color: #46516b; background: #f0f2f7; cursor: pointer; } .danger { color: #a94f5c; } .empty { padding: 28px; color: #7d8799; text-align: center; border: 1px dashed #dfe4ee; border-radius: 13px; } button:focus-visible, input:focus-visible, select:focus-visible { outline: 3px solid #b9c8ff; outline-offset: 2px; } @media (max-width: 680px) { .app-shell { margin: 16px auto; padding: 20px; } header { align-items: flex-start; flex-wrap: wrap; } header #login { margin-left: 56px; } form { display: grid; grid-template-columns: 1fr 1fr; } form input:first-child, form input:nth-child(4), form button { grid-column: 1 / -1; } .toolbar { display: grid; grid-template-columns: 1fr 120px; } li { align-items: flex-start; flex-wrap: wrap; } .todo-body { min-width: calc(100% - 42px); } } @media (max-width: 420px) { .stats { grid-template-columns: repeat(2, 1fr); } .toolbar { grid-template-columns: 1fr; } }
""",
        "apps/api/server.py": """from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import TodoStore

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / 'apps' / 'web'
store = TodoStore(Path(os.getenv('DATABASE_PATH', ROOT / 'data' / 'app.sqlite3')))
session = None


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, payload=None, content_type='application/json'):
        if status == 204:
            self.send_response(status); self.end_headers(); return
        data = payload if isinstance(payload, bytes) else (json.dumps(payload, ensure_ascii=False).encode() if content_type == 'application/json' else payload.encode())
        self.send_response(status); self.send_header('content-type', f'{content_type}; charset=utf-8'); self.send_header('content-length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get('content-length', 0)); return json.loads(self.rfile.read(length) or '{}')

    def _require_session(self):
        if not session:
            self._send(401, {'error': 'login_required'}); return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/health': return self._send(200, {'status': 'ok', 'auth': 'demo' if os.getenv('AUTH_MODE', 'demo') == 'demo' else 'awaiting_configuration'})
        if path == '/api/session': return self._send(200, session) if session else self._send(401, {'error': 'login_required'})
        if path == '/api/todos/stats':
            if not self._require_session(): return
            return self._send(200, store.stats())
        if path == '/api/todos':
            if not self._require_session(): return
            query = parse_qs(urlsplit(self.path).query)
            return self._send(200, store.list(search=query.get('search', [''])[0], status=query.get('status', ['all'])[0]))
        if path.startswith('/'):
            relative = 'index.html' if path == '/' else path.removeprefix('/')
            candidate = (WEB_ROOT / relative).resolve()
            if WEB_ROOT.resolve() in candidate.parents and candidate.is_file():
                content_type = 'text/html' if candidate.suffix == '.html' else 'text/javascript' if candidate.suffix == '.js' else 'text/css'
                return self._send(200, candidate.read_bytes(), content_type)
        return self._send(404, {'error': 'not_found'})

    def do_POST(self):
        global session
        path = urlsplit(self.path).path
        if path == '/api/session':
            body = self._body(); mode = body.get('mode', 'demo')
            if mode == 'google' and not os.getenv('GOOGLE_CLIENT_ID'):
                return self._send(409, {'error': 'awaiting_configuration', 'reason': 'Google OAuth credentials are not configured'})
            session = {'mode': mode, 'user': {'email': 'local@example.test'}}; return self._send(200, session)
        if path == '/api/todos':
            if not self._require_session(): return
            try: return self._send(201, store.create(self._body()))
            except ValueError as error: return self._send(400, {'error': str(error)})
        return self._send(404, {'error': 'not_found'})

    def do_PATCH(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/todos/') and self._require_session():
            try: return self._send(200, store.update(path.rsplit('/', 1)[-1], self._body()))
            except KeyError: return self._send(404, {'error': 'todo_not_found'})
        return self._send(404, {'error': 'not_found'})

    def do_DELETE(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/todos/') and self._require_session():
            if store.delete(path.rsplit('/', 1)[-1]): return self._send(204)
            return self._send(404, {'error': 'todo_not_found'})
        return self._send(404, {'error': 'not_found'})


if __name__ == '__main__':
    host = os.getenv('API_HOST', '127.0.0.1'); port = int(os.getenv('API_PORT', '8787'))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
""",
        "apps/api/store.py": """from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path


class TodoStore:
    def __init__(self, path: Path):
        self.path = path; self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS todos (id TEXT PRIMARY KEY, title TEXT NOT NULL, priority TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, due_date TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '')")
            columns = {row[1] for row in db.execute('PRAGMA table_info(todos)')}
            for name in ('due_date', 'tags'):
                if name not in columns: db.execute(f"ALTER TABLE todos ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _row(row):
        return {'id': row[0], 'title': row[1], 'priority': row[2], 'completed': bool(row[3]), 'dueDate': row[4], 'tags': [tag for tag in row[5].split(',') if tag]}

    def list(self, *, search='', status='all'):
        clauses, values = [], []
        if search: clauses.append('LOWER(title) LIKE ?'); values.append(f'%{search.lower()}%')
        if status == 'active': clauses.append('completed = 0')
        if status == 'completed': clauses.append('completed = 1')
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        with sqlite3.connect(self.path) as db: return [self._row(row) for row in db.execute(f'SELECT id,title,priority,completed,due_date,tags FROM todos{where} ORDER BY rowid DESC', values)]

    def stats(self):
        with sqlite3.connect(self.path) as db: total, completed = db.execute('SELECT COUNT(*), COALESCE(SUM(completed), 0) FROM todos').fetchone()
        return {'total': total, 'completed': completed, 'active': total - completed, 'rate': round((completed / total) * 100) if total else 0}

    def create(self, body):
        title = str(body.get('title', '')).strip()
        if not title: raise ValueError('title_required')
        priority = body.get('priority', 'medium') if body.get('priority') in {'low', 'medium', 'high'} else 'medium'
        due_date = str(body.get('dueDate', '')).strip()
        tags = [str(tag).strip() for tag in body.get('tags', []) if str(tag).strip()]
        todo = {'id': uuid.uuid4().hex, 'title': title, 'priority': priority, 'completed': False, 'dueDate': due_date, 'tags': tags}
        with sqlite3.connect(self.path) as db: db.execute('INSERT INTO todos VALUES (?,?,?,?,?,?)', (todo['id'], title, priority, 0, due_date, ','.join(tags)))
        return todo

    def update(self, todo_id, body):
        current = next((item for item in self.list() if item['id'] == todo_id), None)
        if current is None: raise KeyError(todo_id)
        updated = {**current, **body}
        tags = updated.get('tags', [])
        with sqlite3.connect(self.path) as db: db.execute('UPDATE todos SET title=?, priority=?, completed=?, due_date=?, tags=? WHERE id=?', (str(updated['title']).strip(), updated.get('priority', 'medium'), int(bool(updated.get('completed'))), str(updated.get('dueDate', '')), ','.join(str(tag).strip() for tag in tags if str(tag).strip()), todo_id))
        return next(item for item in self.list() if item['id'] == todo_id)

    def delete(self, todo_id):
        with sqlite3.connect(self.path) as db: cursor = db.execute('DELETE FROM todos WHERE id=?', (todo_id,))
        return cursor.rowcount == 1
""",
        "packages/auth/README.md": """# Authentication contract

Local execution uses a clearly labeled demo session so the app can be tested without credentials. Production Google OAuth is not considered configured until `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, callback URL, and session secret exist. EEEE must report `awaiting_configuration` instead of claiming production login works.
""",
        "packages/db/README.md": """# Database contract

Local mode uses SQLite through `apps/api/store.py`. Production deployments replace `DATABASE_PATH` with a managed `DATABASE_URL` through a connector-specific adapter and must rerun migration and E2E checks.
""",
    }
    created: list[Path] = []
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(content, encoding='utf-8', newline='\n')
            created.append(path)
    return created
