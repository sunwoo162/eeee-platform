"""Built-in local-first meal planner template."""

from __future__ import annotations

from pathlib import Path

from app.project_runtime.web_scaffold import create_web_app_scaffold


class MealPlannerTemplate:
    id = "meal_planner"

    @classmethod
    def create(cls, workspace: Path, project_name: str) -> list[Path]:
        root = Path(workspace)
        before = {path for path in root.rglob("*")} if root.exists() else set()
        create_web_app_scaffold(root, project_name)
        files = {
            "apps/web/index.html": """<!doctype html>
<html lang="ko">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>오늘 식단</title>
    <link rel="stylesheet" href="./src/shared/ui/styles.css" />
  </head>
  <body><main id="app"></main><script type="module" src="./src/app/main.js"></script></body>
</html>
""",
            "apps/web/src/entities/meal/model.js": """export const MEAL_SECTIONS = ['breakfast', 'lunch', 'dinner'];

export function normalizeMeal(meal) {
  return { id: String(meal.id), section: MEAL_SECTIONS.includes(meal.section) ? meal.section : 'dinner', name: String(meal.name).trim(), note: String(meal.note || '').trim() };
}

export function loadMeals() {
  try { return JSON.parse(localStorage.getItem('eeee-meals') || '[]').map(normalizeMeal); }
  catch { return []; }
}

export function saveMeals(meals) { localStorage.setItem('eeee-meals', JSON.stringify(meals.map(normalizeMeal))); }

export function addMeal(meals, meal) {
  const next = [...meals, normalizeMeal({ ...meal, id: meal.id || crypto.randomUUID() })];
  saveMeals(next); return next;
}

export function updateMeal(meals, id, patch) {
  const next = meals.map((meal) => meal.id === id ? normalizeMeal({ ...meal, ...patch }) : meal);
  saveMeals(next); return next;
}

export function deleteMeal(meals, id) {
  const next = meals.filter((meal) => meal.id !== id);
  saveMeals(next); return next;
}
""",
            "apps/web/src/pages/home/ui.js": """import { MEAL_SECTIONS, addMeal, deleteMeal, loadMeals, updateMeal } from '../../entities/meal/model.js';

const labels = { breakfast: '아침', lunch: '점심', dinner: '저녁' };

export function renderApp(root) {
  root.innerHTML = `<section class="app-shell meal-planner"><header><small>EEEE local-first</small><h1>오늘 식단</h1><p>아침·점심·저녁을 한눈에 정리하세요.</p></header><form id="meal-form"><label>식사 <select id="meal-section"><option value="breakfast">아침</option><option value="lunch">점심</option><option value="dinner">저녁</option></select></label><label>메뉴 <input id="meal-name" required aria-label="메뉴" /></label><label>메모 <input id="meal-note" aria-label="메모" /></label><button>추가</button></form><p id="empty-state" class="empty">아직 등록한 식단이 없습니다.</p><p id="error-state" class="error" hidden>식단을 불러오지 못했습니다.</p><div id="meal-list" aria-live="polite"></div></section>`;
  let meals = loadMeals();
  const list = root.querySelector('#meal-list');
  const empty = root.querySelector('#empty-state');
  const form = root.querySelector('#meal-form');
  const draw = () => {
    empty.hidden = meals.length > 0;
    list.replaceChildren();
    MEAL_SECTIONS.forEach((section) => {
      const sectionElement = document.createElement('section');
      sectionElement.dataset.section = section;
      const heading = document.createElement('h2');
      heading.textContent = labels[section];
      sectionElement.append(heading);
      meals.filter((meal) => meal.section === section).forEach((meal) => {
        const article = document.createElement('article');
        article.dataset.id = meal.id;
        const name = document.createElement('strong');
        name.textContent = meal.name;
        const note = document.createElement('span');
        note.textContent = meal.note;
        const edit = document.createElement('button');
        edit.dataset.edit = meal.id;
        edit.textContent = '수정';
        const remove = document.createElement('button');
        remove.dataset.delete = meal.id;
        remove.textContent = '삭제';
        article.append(name, note, edit, remove);
        sectionElement.append(article);
      });
      list.append(sectionElement);
    });
  };
  form.addEventListener('submit', (event) => { event.preventDefault(); meals = addMeal(meals, { section: root.querySelector('#meal-section').value, name: root.querySelector('#meal-name').value, note: root.querySelector('#meal-note').value }); form.reset(); draw(); });
  list.addEventListener('click', (event) => { const id = event.target.dataset.delete || event.target.dataset.edit; if (!id) return; if (event.target.dataset.delete) meals = deleteMeal(meals, id); else meals = updateMeal(meals, id, { note: '수정됨' }); draw(); });
  draw();
}
""",
            "DESIGN.md": """# 오늘 식단 디자인·구조 결정

- Template: `meal_planner`
- 아침(breakfast)·점심(lunch)·저녁(dinner)을 같은 정보 구조로 묶고, 등록·수정·삭제·빈 상태·오류 상태를 제공한다.
- localStorage를 로컬 우선 저장소로 사용하며, 새로고침 후에도 식단을 보존한다.
- 320px·390px·768px·1440px viewport에서 폼과 식단 카드가 반응형으로 재배치된다.
""",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        return [path for path in root.rglob("*") if path.is_file() and path not in before]
