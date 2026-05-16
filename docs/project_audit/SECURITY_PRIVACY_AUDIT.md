# Security / Privacy Audit

Метод: просмотр `.gitignore`, `.env.example`, `app/config.py`, `app/auth/*`, grep по типичным паттернам секретов в `*.py` (без гарантии полного покрытия всех форматов).

## Таблица рисков

| Риск безопасности/приватности | Где найдено | Влияние | Приоритет | Как снизить |
|-------------------------------|-------------|---------|-----------|-------------|
| Debug и project debug endpoints без JWT по умолчанию | `review_assistant_repo/README.md` (секция API explorer & debug) | Утечка содержимого проектов/артефактов при публичном IP | P0 для публичного деплоя | `REQUIRE_AUTH_FOR_DEBUG_ROUTES=true` + Supabase |
| Записи API без обязательной auth по умолчанию | `.env.example`: `REQUIRE_AUTH_FOR_WRITES=false` | Неавторизованная загрузка/ревью | P1 для shared dev / P0 для prod | `REQUIRE_AUTH_FOR_WRITES=true` |
| Service role key в конфиге | `.env.example` комментирует `SUPABASE_SERVICE_ROLE_KEY` | Полный доступ к storage | P1 | Только сервер, секреты в vault |
| LLM API key в environment | `.env.example` `LLM_API_KEY` | Утечка ключа при логировании env / CI | P1 | Секреты вне репо; не печатать |
| CORS выключен по умолчанию | `.env.example` пустой `CORS_ALLOWED_ORIGINS` | CSRF/браузерные риски для SPA — контролируемые при включении | P2 | Явный список origins |
| Тестовый JWT secret в тестах | `tests/test_debug_routes_auth.py` — строка `unit-test-debug-routes-secret` | Низкий — только unit tests | P3 | Норма для тестов |
| Реальные `.env` в git | `.gitignore` исключает `.env`, `.env.*` | Снижает риск коммита секретов | — | Поддерживать |
| Логирование PII | **не найдено** полного аудита всех `logger.*` вызовов | Unknown | P2 | Точечный review логов |
| Rate limits на upload/review | **не найдено** в быстром просмотре `config.py` | DoS / злоупотребление | P1 для prod | Добавить лимиты (post-MVP или сразу) |
| CORS credentials | `CORS_ALLOW_CREDENTIALS` в `.env.example` | Misconfig с `*` | P2 | README уже предупреждает |

**Grep на типичные OpenAI-style ключи в коде:** явных `sk-...` в tracked Python **не найдено** (поверхностная проверка).

---

## Security MVP Minimum

Перед публичным MVP для Review Assistant:

1. Включить аутентификацию для **всех** write-операций (`REQUIRE_AUTH_FOR_WRITES`) и для debug (`REQUIRE_AUTH_FOR_DEBUG_ROUTES`), если API доступен вне доверенной сети.
2. Настроить Supabase JWT (`SUPABASE_JWT_SECRET` или `SUPABASE_JWKS_URL`) согласно `app/auth/supabase_jwt.py`.
3. Не коммитить реальные `.env`; ротировать ключи, если когда-либо утекли.
4. Задокументировать хранение учебных работ (retention) — **вне текущего репозитория** (политика организации).
5. Минимальные лимиты размера загрузки уже есть (`MAX_UPLOAD_BYTES` в `.env.example`) — проверить соответствие инфраструктуре reverse proxy.

---

## Вывод | Доказательство | Уровень уверенности

| Вывод | Доказательство | Уровень |
|--------|----------------|---------|
| Секреты в tracked файлах не обнаружены поверхностным grep | Ручной grep + `.gitignore` | Medium (не полный secret scan) |
| Debug routes — главный конфигурируемый риск | README + `.env.example` | High |
