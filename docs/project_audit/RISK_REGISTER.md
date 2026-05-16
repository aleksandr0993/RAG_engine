# Risk Register

Оценки вероятности/влияния — **экспертная интерпретация** на основе структуры репозитория (commit `c2d90a4`).

| Риск | Категория | Вероятность | Влияние | Где видно | Как снизить |
|------|-----------|-------------|---------|-----------|-------------|
| CI не запускается на push в основной репозиторий | infrastructure / developer experience | High | High | `.github` только в `review_assistant_repo/` | Перенести workflow в корень с `working-directory` |
| Новый разработчик не понимает границ пакетов | documentation | High | Medium | Нет корневого README | Корневой README + диаграмма |
| Debug API без JWT в проде | auth/security | Medium | Critical | `README.md`: debug по умолчанию без JWT | Включить `REQUIRE_AUTH_FOR_DEBUG_ROUTES` + Supabase |
| LLM ключи в env — риск утечки при логах | auth/security | Medium | High | `.env.example` перечисляет `LLM_API_KEY` | Политика секретов, не логировать env |
| DataLens / Playwright хрупкость при смене UI | frontend / integrations | Medium | Medium | `README.md` limitations, capture код | Feature flag, fallback |
| Отсутствие lockfile frontend | maintainability | Medium | Medium | Нет tracked `package-lock.json` | Закоммитить lockfile |
| `**/data/` в .gitignore скрывает шаблоны homework | documentation / developer experience | High | Medium | Корневой `.gitignore`; README homework ссылается на `data/` | Исключения или отдельный путь |
| Один коммит в git — нет истории инцидентов | maintainability | Low | Medium | `git log` | Вести CHANGELOG + нормальные коммиты дальше |
| RL/SB3 — тяжёлые зависимости и поверхность атаки | architecture | Low | Medium | optional deps | Держать выключенным для MVP |
| Нет Sentry/monitoring в проде | reliability | Medium | Medium | не найдено в deps | Добавить post-MVP |
| Юридический/Privacy: персональные данные студентов | legal/privacy | Unknown | Critical | Проект работает с учебными работами | DPIA, retention — **требует уточнения** вне репозитория |

---

## Top 5 Risks

1. **CI в нестандартном месте** — регрессии не видны на уровне монорепо.
2. **Debug без auth по умолчанию** — утечка данных проектов при публичном деплое.
3. **Нет корневого onboarding** — замедление команды.
4. **Homework data path vs gitignore** — сломанный quickstart для ML-пакета.
5. **Отсутствие lockfile для frontend** — «works on my machine» для UI.

---

## Вывод | Доказательство | Уровень уверенности

| Вывод | Доказательство | Уровень |
|--------|----------------|---------|
| Top-1 риск — CI расположение | `Glob` → единственный workflow под `review_assistant_repo/.github/` | Medium–High |
| Auth для debug опциональна | `review_assistant_repo/README.md` API (explorer & debug) | High |
