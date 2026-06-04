# cross-agent-memory-kit

[English](README.md) | **Українська**

**Навіщо це:** AI-агенти для кодування щоразу починають сесію з нуля. Вони забувають рішення, домовленості та глухі кути з вашої попередньої розмови, тож ви знову й знову переповідаєте той самий контекст. Цей набір дає їм постійну памʼять, що поповнюється сама: після кожної сесії він дистилює те, що сталося, у тривкі факти і зберігає їх, тож наступна сесія - на будь-якому агенті, на будь-якій вашій машині - уже все знає.

Працюєте самі - одна памʼять супроводжує вас на всіх пристроях. Ділите один акаунт із **командою чи родиною**? Опційний багатокористувацький режим дає кожній людині приватну памʼять плюс спільне сховище, з жорсткою ізоляцією, тож приватні нотатки лишаються приватними - див. [MULTI-USER.md](MULTI-USER.md).

Відтворювана конфігурація для [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) на машинах з macOS та Linux (на Windows не тестувалося), плюс власний скіл для Claude Code і хук пост-сесійної дистиляції, які його обгортають.

Цей репозиторій має всю необхідну інформацію для AI-агентів. Спрямуйте будь-якого AI-агента (Claude Code, Codex, Gemini, Cursor, Windsurf, Lovable, Kiro, ...) на цю теку, і він матиме все потрібне, щоб відтворити налаштування на новій машині.

Поточна версія налаштувань: `0.2.0-dev` з файлу `VERSION`.

## Що ви отримуєте після відтворення

1. **`mcp-memory-service`**, який працює локально як stdio MCP-сервер. Сховище на SQLite-vec. Зберігає факти, рішення, домовленості, нотатки про помилки та дистиляції сесій між розмовами.
2. **Скіл `/mcp-memory-query`** (або його еквівалент для не-Claude агентів), який навчає агента діставати дані зі служби.
3. **Хук пост-сесійної дистиляції**, який після кожної сесії Claude Code надсилає транскрипт обраній LLM (Claude, Codex, Gemini, OpenRouter, ...) і зберігає видобуті артефакти та факти назад у службу памʼяті.
4. **Трасування LangSmith** для кожного виклику дистиляції, тож ви бачите промпт, відповідь, затримку та вартість на сесію в панелі LangSmith.
5. **Опційна синхронізація між пристроями.** Перемкніть сервер на гібридний бекенд, і одна памʼять стає спільною для всіх ваших машин: Cloudflare (D1 + Vectorize) як джерело істини та локальний кеш SQLite на кожному пристрої. Див. [MULTI-DEVICE-SYNC.md](MULTI-DEVICE-SYNC.md).
6. **Опційний багатокористувацький поділ (спільний акаунт).** Коли один акаунт агента використовують кілька людей - команда в компанії або родина, - дайте кожній людині **приватне** сховище памʼяті плюс **спільне** сховище команди/родини, з жорсткою ізоляцією (окремі бази Cloudflare D1, тож інші фізично не можуть прочитати вашу приватну памʼять). Запустіть `python3 onboard_multiuser.py`. Див. [MULTI-USER.md](MULTI-USER.md).

## Структура репозиторію

```
cross-agent-memory-kit/
├── onboard.py                        # інтерактивний майстер встановлення (почніть звідси)
├── onboard_multiuser.py              # майстер для спільного акаунта (приватне + спільне сховища)
├── .env.example                      # шаблон - скопіюйте в .env і заповніть
├── .env                              # (у gitignore) реальні секрети
├── .gitignore
├── LICENSE
├── README.md                         # англійська версія
├── README.uk.md                      # цей файл
├── MULTI-DEVICE-SYNC.md              # спільна памʼять між пристроями (Cloudflare)
├── MULTI-USER.md                     # один акаунт, багато людей: приватна + спільна памʼять
├── CHANGELOG.md
├── VERSION                           # машиночитна версія репозиторію налаштувань
├── USECASES.md                       # для чого ці налаштування
├── LESSONS_LEARNED.md                # підводні камені, рішення дизайну
├── config/
│   ├── providers.example.yaml        # конфіг провайдерів/моделей для хука
│   └── profiles.example.yaml         # приклад структури сховищ однієї людини (багатокористувацький)
├── hooks/
│   └── distill_session.py            # обгортка SessionEnd для Claude Code
├── distill/
│   ├── engine.py                     # спільний потік дистиляції
│   ├── prompt.md                     # єдине джерело правил памʼяті
│   ├── storage.py                    # запис у БД mcp-memory-service
│   ├── providers.py                  # виклики LLM-провайдерів і конфіг
│   ├── registry.py                   # опційний реєстр слагів проєктів/клієнтів
│   └── adapters/                     # сирий транскрипт -> нормалізований транскрипт
├── wrappers/
│   ├── codex_session_scan.py         # сканер/обгортка для Codex (pull-режим)
│   ├── cursor_session_scan.py        # сканер/обгортка для Cursor (pull-режим)
│   ├── provenance_backfill.py        # аудит/добивання походження (dry-run)
│   └── usage_report.py               # звіт використання токенів із distill_runs
├── launchd/
│   └── memory-distill.plist.template # рендериться під машину інсталяторами вотчерів
├── skills/
│   ├── mcp-memory-query/
│   │   └── SKILL.md                  # скіл діставання (один користувач)
│   └── mcp-memory-multiuser/
│       └── SKILL.md                  # скіл діставання + маршрутизації запису (спільний акаунт)
└── scripts/
    ├── install.sh                    # ідемпотентний низькорівневий інсталятор
    ├── check_version.py              # перевірка VERSION / changelog / тегів
    ├── install_codex_watcher.sh      # встановлює launchd-сканер для Codex
    ├── install_cursor_watcher.sh     # встановлює launchd-сканер для Cursor
    └── setup_multiuser_cloudflare.sh # створює спільні + приватні ресурси Cloudflare D1/Vectorize
```

## Передумови

- macOS або Linux (Windows не тестувався).
- Python 3.10+, доступний як `python3`.
- Один або кілька з цих LLM CLI / API-ключів:
  - CLI `claude` (з входом в Anthropic) - підписочна автентифікація, використовується типово
  - CLI `codex` - підписочна автентифікація
  - CLI `gemini` - підписочна автентифікація
  - CLI `cursor-agent` - підписочна автентифікація
  - `OPENROUTER_API_KEY` - оплата за токени
  - `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` - оплата за токени

Потрібен лише ОДИН налаштований провайдер. Хук обирає його за `config/providers.yaml`.

## Швидкий старт: інтерактивний майстер

Найшвидший шлях - `onboard.py`. Він проведе вас через усе: створює/перевикористовує venv, обирає провайдера дистиляції, за бажанням налаштовує гібридний бекенд Cloudflare для синхронізації між пристроями, записує `.env` і `config/providers.yaml` та друкує точний блок MCP-сервера, який треба вставити в конфіг вашого агента. Він ніколи не перезаписує наявну базу памʼяті.

```bash
git clone <this-repo> cross-agent-memory-kit
cd cross-agent-memory-kit
python3 onboard.py            # інтерактивно; --help для неінтерактивних прапорців
```

Майстер ніколи не редагує конфіги вашого агента сам - він друкує блок JSON/TOML і каже, куди його вставити, тож не може зіпсувати конфіг неправильним припущенням.

## Швидкий старт: вручну

Якщо волієте робити це власноруч:

```bash
git clone <this-repo> cross-agent-memory-kit
cd cross-agent-memory-kit
cp .env.example .env                    # потім відредагуйте .env, додавши ключі
cp config/providers.example.yaml config/providers.yaml   # потім змініть, якщо хочете інший провайдер
bash scripts/install.sh                 # ідемпотентно: створює/перевикористовує venv, друкує блоки конфігу MCP
```

`install.sh` робить таке, ідемпотентно:

1. Створює Python venv у `~/.local/share/mcp-memory-service-venv/`, лише якщо його ще немає.
2. Перевіряє, чи вже успішно імпортуються `mcp-memory-service`, LangSmith, провайдери LangChain, `python-dotenv` та `pyyaml`.
3. Пропускає встановлення залежностей, коли наявний venv справний.
4. Встановлює відсутні залежності, не форсуючи оновлення, коли venv неповний.
5. Друкує блок MCP-сервера для додавання в конфіг кожного AI-агента.
6. **Не** редагує конфіги агентів автоматично, не встановлює скіли, не підключає хуки і не змінює базу памʼяті.

Щоб свідомо оновити Python-пакети, передайте:

```bash
bash scripts/install.sh --upgrade-deps
```

## Наявне встановлення: правило збереження понад усе

Якщо `mcp-memory-service` уже працює через Claude Code чи іншого агента, **не** перевстановлюйте з нуля. Не видаляйте і не перестворюйте:

- `~/.local/share/mcp-memory-service-venv/`
- `~/Library/Application Support/mcp-memory/` на macOS
- `~/.local/share/mcp-memory/` на Linux
- будь-які файли `sqlite_vec.db`, `sqlite_vec.db-wal` чи `sqlite_vec.db-shm`

Для Codex, Cursor, Gemini чи Kiro на машині, де служба вже є, зазвичай потрібно лише:

1. Спрямувати MCP-конфіг агента на наявний venv-Python:

   ```text
   /Users/<you>/.local/share/mcp-memory-service-venv/bin/python -m mcp_memory_service.server
   ```

2. Встановити специфічні для агента інструкції з пошуку або скіл.
3. Перезапустити агента, щоб завантажилися інструменти MCP.

`scripts/install.sh` безпечно запускати для перевірки, бо він перевикористовує наявний справний venv і зберігає виявлений шлях до бази. Та все ж агентам варто реєструвати наявний сервер, а не запускати встановлення пакетів, коли venv і БД уже присутні.

## Налаштування вручну, по кожному AI-агенту

### Claude Code

Конфіг MCP-сервера додається в `~/.claude.json` під `mcpServers`:

```json
{
  "mcpServers": {
    "memory": {
      "type": "stdio",
      "command": "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python",
      "args": ["-m", "mcp_memory_service.server"],
      "env": {}
    }
  }
}
```

Скіл кладеться в `~/.claude/skills/mcp-memory-query/SKILL.md` (скопіюйте з `skills/mcp-memory-query/SKILL.md` цього репозиторію).

Хук SessionEnd додається в `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/cross-agent-memory-kit/hooks/distill_session.py",
            "async": true,
            "timeout": 300
          }
        ]
      }
    ]
  }
}
```

Shebang скрипта-хука вказує на venv-Python (де імпортується `mcp_memory_service`). Це лише обгортка для Claude; правила дистиляції живуть у `distill/prompt.md` і спільному рушії в `distill/`.

### Codex CLI

MCP-сервери реєструються в `~/.codex/config.toml`:

```toml
[mcp_servers.memory]
command = "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python"
args = ["-m", "mcp_memory_service.server"]
```

Для скілів Codex скопіюйте теку скіла напряму:

```bash
mkdir -p ~/.codex/skills/mcp-memory-query
cp skills/mcp-memory-query/SKILL.md ~/.codex/skills/mcp-memory-query/SKILL.md
```

Створюйте окрему копію для Codex у цьому репозиторії (наприклад `skills/codex_mcp-memory-query/SKILL.md`) лише якщо встановлений скіл Codex має відрізнятися від спільного. Станом на 2026-05-06 встановлений у Codex скіл ідентичний `skills/mcp-memory-query/SKILL.md`, тож окрема копія для Codex не потрібна.

Codex наразі не надає хука SessionEnd. Репозиторій надає сканер у pull-режимі, який стежить за файлами JSONL сесій Codex і викликає спільний рушій дистиляції з типовими налаштуваннями провайдера Codex:

```bash
python wrappers/codex_session_scan.py --dry-run --quiet-minutes 0 --lookback-days 2 --limit 2
```

Встановіть launchd-вотчер для macOS:

```bash
bash scripts/install_codex_watcher.sh
```

Інсталятор спершу позначає наявні тихі сесії Codex як `baseline` у `~/.local/state/cross-agent-memory-kit/codex-processed.json`, а потім запускає сканер щодня о 04:00 за локальним часом. Майбутні тихі сесії дистилюються один раз із `DISTILL_PROVIDER=codex-cli` та `DISTILL_MODEL=gpt-5.1-low`. Завдання launchd використовує `--limit 0`, тож щоденний запуск опрацьовує всі необроблені тихі сесії, а не зупиняється після малої партії. Виклики провайдера Codex використовують `codex exec --ephemeral`, тож виклики дистиляції не створюють нових логів сесій Codex, які сканер мав би поглинати.

Логи сканера Codex:

```text
~/.local/state/cross-agent-memory-kit/logs/codex.log
~/.local/state/cross-agent-memory-kit/logs/codex-launchd.out.log
~/.local/state/cross-agent-memory-kit/logs/codex-launchd.err.log
```

### Cursor

MCP-конфіг Cursor живе в `~/.cursor/mcp.json` із тією ж формою, що й блок `mcpServers` для Claude Code.

Для скіла: вставте вміст `SKILL.md` у Cursor Project Rule під `.cursor/rules/mcp-memory-query.mdc`.

Cursor не надає хука SessionEnd. Репозиторій надає сканер у pull-режимі, який стежить за файлами JSONL сесій Cursor і викликає спільний рушій дистиляції з типовими налаштуваннями провайдера Cursor:

```bash
python wrappers/cursor_session_scan.py --dry-run --quiet-minutes 0 --lookback-days 2 --limit 2
```

Встановіть launchd-вотчер для macOS:

```bash
bash scripts/install_cursor_watcher.sh
```

Інсталятор спершу позначає наявні тихі сесії Cursor як `baseline` у `~/.local/state/cross-agent-memory-kit/cursor-processed.json`, а потім запускає сканер щодня о 04:00 за локальним часом. Майбутні тихі сесії дистилюються один раз із `DISTILL_PROVIDER=cursor-cli` та `DISTILL_MODEL=sonnet-4`. Завдання launchd використовує `--limit 0`, тож щоденний запуск опрацьовує всі необроблені тихі сесії.

Логи сканера Cursor:

```text
~/.local/state/cross-agent-memory-kit/logs/cursor.log
~/.local/state/cross-agent-memory-kit/logs/cursor-launchd.out.log
~/.local/state/cross-agent-memory-kit/logs/cursor-launchd.err.log
```

### Windsurf

Windsurf (Cascade) читає MCP-сервери з `~/.codeium/windsurf/mcp_config.json` із тією ж формою `mcpServers`, що й Claude Code. Його також можна відкрити з панелі Cascade: натисніть піктограму MCPs, потім Configure.

```json
{
  "mcpServers": {
    "memory": {
      "command": "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python",
      "args": ["-m", "mcp_memory_service.server"],
      "env": {}
    }
  }
}
```

Для скіла вставте `SKILL.md` у правила Windsurf (глобальні правила або файл під `.windsurf/rules/`). Windsurf не має хука SessionEnd, тож дистилюйте вручну або за розкладом - так само, як для Codex/Cursor.

### Gemini CLI

Gemini CLI використовує `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "memory": {
      "command": "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python",
      "args": ["-m", "mcp_memory_service.server"]
    }
  }
}
```

Еквівалент скіла: вставте `SKILL.md` у `GEMINI.md` у корені проєкту.

Хук: так само як для Codex/Cursor - ручний або запланований виклик.

### Kiro.dev

Kiro читає `~/.kiro/settings/mcp.json`. Та сама форма `mcpServers`, що й у Claude Code. Скіли вставляються в steering-документ Kiro.

### Lovable

Lovable - це хмарний застосунок-білдер, тож він працює інакше, ніж локальні агенти вище: він підключається до MCP-серверів за **URL**, а не запускаючи локальний процес. Конфіг stdio з цього репозиторію тут не діє напряму - Lovable не може дістатися до Python-процесу на вашій машині.

Щоб використати цей сервер памʼяті з Lovable, спершу запустіть mcp-memory-service у віддаленому/HTTP-транспорті, щоб він мав доступний HTTPS-ендпоінт (див. документацію [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) щодо режиму HTTP-сервера). Потім у Lovable відкрийте **Connectors > Chat connectors**, додайте власний MCP-сервер і вкажіть:

- **Server URL:** HTTPS-ендпоінт вашого сервера памʼяті
- **Auth:** OAuth, bearer-токен або API-ключ, як вимагає ваш ендпоінт (або без автентифікації)

Конектори Lovable діють на рівні користувача, і їх будь-коли можна відкликати в Connectors. Хука SessionEnd немає - Lovable працює в хмарі, тож запускайте локальний хук/сканери дистиляції на тій машині, яка реально містить транскрипти ваших сесій.

### Hermes Agent

Hermes Agent має нативний MCP-клієнт і читає MCP-сервери з `~/.hermes/config.yaml` під `mcp_servers`. Щоб перевикористати наявне встановлення служби памʼяті без зміни налаштувань Claude Code, додайте лише блок Hermes нижче:

```yaml
mcp_servers:
  memory:
    command: "/Users/<you>/.local/share/mcp-memory-service-venv/bin/python"
    args: ["-m", "mcp_memory_service.server"]
    env: {}
    timeout: 120
    connect_timeout: 60
```

Для цього сервера краще редагувати YAML напряму, бо аргумент Python `-m` у деяких оболонках/версіях можна сплутати з опцією верхнього рівня Hermes `-m/--model`.

Якщо серверу памʼяті потрібні змінні середовища, наприклад для гібридного бекенду Cloudflare, помістіть їх під `mcp_servers.memory.env` у `~/.hermes/config.yaml`. Hermes типово фільтрує середовище підпроцесів, тож не покладайтеся на автоматичне успадкування секретів з оболонки.

Встановіть скіл пошуку для Hermes окремо від скіла Claude, бо назви інструментів можуть відрізнятися:

```bash
mkdir -p ~/.hermes/skills/mcp/mcp-memory-query
cp skills/mcp-memory-query/SKILL.md ~/.hermes/skills/mcp/mcp-memory-query/SKILL.md
# Потім відредагуйте копію для Hermes, щоб назви інструментів у стилі Claude, як-от
# mcp__memory__memory_search, стали нативними назвами MCP для Hermes, як-от
# mcp_memory_memory_search.
```

Hermes не використовує хук `SessionEnd` від Claude Code. Для дистиляції сесій застосовуйте специфічний для агента сканер/обгортку, якщо така є, запускайте спільний хук вручну з відповідним адаптером транскрипта або додайте обгортку для Hermes пізніше. Не кладіть блок `SessionEnd` від Claude у конфіг Hermes.

Після редагування `~/.hermes/config.yaml` перезапустіть Hermes або виконайте `/reload-mcp`. Перевірте:

```bash
hermes mcp list
hermes mcp test memory
```

Hermes реєструє інструменти за конвенцією назв `mcp_{server}_{tool}`, тож інструменти сервера памʼяті зʼявляються як `mcp_memory_memory_search`, `mcp_memory_memory_store` та `mcp_memory_memory_health` після перезавантаження.

## Мультипровайдерна дистиляція

`config/providers.yaml` (у gitignore, копіюється з `providers.example.yaml`) керує тим, яку LLM викликає пост-сесійний хук.

```yaml
default_provider: claude-cli
providers:
  claude-cli:
    model: claude-haiku-4-5-20251001
  codex-cli:
    model: gpt-5.1-low
  gemini-cli:
    model: gemini-2.5-flash
  openrouter-api:
    model: anthropic/claude-haiku-4.5
  ...
```

Типово виклики хука використовують `default_provider`, наразі `claude-cli` з `claude-haiku-4-5-20251001`. Використовуйте змінні середовища на межі хука/обгортки агента, щоб обрати інший провайдер для цього агента без зміни коду хука:

```bash
DISTILL_PROVIDER=codex-cli DISTILL_MODEL=gpt-5.1-low python hooks/distill_session.py
```

Наприклад, лишіть хук SessionEnd для Claude Code без префіксів, щоб він тримався Haiku. Для Codex обгортка-сканер виставляє `DISTILL_PROVIDER=codex-cli DISTILL_MODEL=gpt-5.1-low`, перш ніж викликати спільний рушій.

## Архітектура дистиляції

Усі агенти поділяють одну політику памʼяті:

```text
Agent wrapper -> transcript adapter -> shared engine -> storage
```

- Обгортки володіють механікою тригерів і станом. Claude - push-режим (`hooks/distill_session.py` отримує одну подію SessionEnd). Codex і Cursor - pull-режим (`wrappers/codex_session_scan.py`, `wrappers/cursor_session_scan.py`) і відстежують оброблені сесії незалежно.
- Адаптери володіють парсингом сирого транскрипта. Вони видають датакласи з `distill/transcript_schema.py`.
- Спільний рушій володіє завантаженням реєстру, рендером промпта, викликами провайдерів та оркестрацією сховища.
- `distill/prompt.md` є джерелом істини політики для правил артефактів, правил фактів, винятків, схеми виводу та орієнтирів типів памʼяті. Не дублюйте ці правила в обгортках окремих агентів.
- Збережені памʼяті несуть нормалізовані метадані походження (`source_agent`, `source_surface`, `source_provider`, `source_session_id`, `ingestion_method`, `distiller_provider`, `distiller_model`) плюс сумісні аліаси (`agent`, `session_id`, `source_path`, `source`). Їх також тегують мітками походження та маршрутизації, як-от `agent:claude`, `agent:codex`, `agent:cursor`, `surface:cli`, `ingestion:codex-scanner` та `distiller:claude-cli`.

Підтримувані провайдери:

| Провайдер | Тип | Автентифікація | Типова модель |
|----------|------|------|---------------|
| `claude-cli` | CLI-підпроцес | підписка CLI `claude` | `claude-haiku-4-5-20251001` |
| `codex-cli` | CLI-підпроцес | підписка CLI `codex` | (власна типова в codex) |
| `gemini-cli` | CLI-підпроцес | підписка CLI `gemini` | `gemini-2.5-flash` |
| `cursor-cli` | CLI-підпроцес | підписка CLI `cursor-agent` | `sonnet-4` |
| `anthropic-api` | LangChain | `ANTHROPIC_API_KEY` | `claude-haiku-4-5` |
| `openai-api` | LangChain | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `gemini-api` | LangChain | `GOOGLE_API_KEY` | `gemini-1.5-flash` |
| `openrouter-api` | LangChain | `OPENROUTER_API_KEY` | `anthropic/claude-haiku-4.5` |

## Трасування LangSmith

Кожен виклик дистиляції обгорнуто в `@traceable("distill.<provider>")` плюс зовнішній `@traceable("distill.session")`. Коли `LANGSMITH_TRACING=true` і в `.env` задано `LANGSMITH_API_KEY`, запуски зʼявляються в проєкті LangSmith із назвою `LANGSMITH_PROJECT` (типово `mcp-memory-service-hook`).

Саме так ви згодом порівнюватимете якість і вартість провайдера/моделі на сесію.

## Облік використання при дистиляції

Кожен запуск дистиляції пише структурований рядок використання у свій лог і рядок у таблицю `distill_runs` SQLite-бази памʼяті. Рядки пишуться для запусків `stored`, `empty`, `skipped` та `failed`, тож облік токенів може включати сесії, що не дали памʼятей.

Таблиця фіксує походження джерела, провайдера/модель дистиляції, кількість токенів, поля кеш-токенів (коли провайдер їх надає), секунди виконання, статус, кількість повернених/збережених памʼятей та кількість символів транскрипта/промпта.

Для питань про токени використовуйте звітний хелпер:

```bash
python wrappers/usage_report.py --range yesterday
python wrappers/usage_report.py --range last-7-days --agent claude
python wrappers/usage_report.py --range this-month --provider codex-cli --output json
```

CLI-провайдери, як-от `claude-cli`, `codex-cli`, `gemini-cli` та `cursor-cli`, зазвичай оплачуються підпискою, тоді як API-провайдери можуть тарифікуватися за токени. Звіт навмисно повертає використання токенів, а не оцінку у валюті.

## Добивання походження

Нові памʼяті з дистиляції сесій зберігають нормалізоване походження надалі. Старіші памʼяті можна аудитувати без жодного переписування:

```bash
python wrappers/provenance_backfill.py
```

Хелпер класифікує очевидні застарілі рядки за наявним `metadata.agent`, тегами `agent:*`, префіксами транскрипта/шляху на кшталт `~/.claude`, `~/.codex`, `~/.cursor` та `metadata.source = session-end-hook`. Він повертає `unknown`, коли походження довести не вдається. Використовуйте `--apply` лише після перегляду підрахунків dry-run.

## Розташування сховища

MCP-сервер пише в:

| ОС | Шлях |
|----|------|
| macOS | `~/Library/Application Support/mcp-memory/sqlite_vec.db` |
| Linux | `~/.local/share/mcp-memory/sqlite_vec.db` |
| Інше | `~/.mcp-memory/sqlite_vec.db` |

Хук пише напряму в ту саму БД, тож інструменти MCP-сервера бачать дані, записані хуком. Перевизначте через `MCP_MEMORY_SQLITE_VEC_PATH`, якщо потрібне інше розташування.

## Перевірка встановлення

Після завершення `scripts/install.sh`:

```bash
# 1. MCP-сервер стартує
/Users/<you>/.local/share/mcp-memory-service-venv/bin/python -m mcp_memory_service.server --help

# 2. Хук проходить перевірку синтаксису
python3 -c "import ast; ast.parse(open('hooks/distill_session.py').read()); print('ok')"

# 3. Хук бачить свої залежності (запуск з venv)
/Users/<you>/.local/share/mcp-memory-service-venv/bin/python -c "
from langsmith import traceable
import mcp_memory_service.storage.sqlite_vec
print('deps ok')
"

# 4. Завершіть сесію Claude Code - перевірте, що в логу зʼявився новий запис
tail -1 ~/.claude/logs/distill-session.log

# 5. Контракт версій узгоджений
python scripts/check_version.py

# 6. Звіт використання токенів може читати БД
python wrappers/usage_report.py --range today
```

## Версіонування та релізи

`VERSION` є машиночитним джерелом істини для версії репозиторію налаштувань. `distill.__version__` читає цей файл під час виконання.

Репозиторій використовує семантичне версіонування:

- Patch: документація, тести або сумісні виправлення інсталятора/хука.
- Minor: доповнення контракту налаштувань, як-от нові обгортки, поля походження, таблиці використання чи зворотно сумісна поведінка скіла.
- Major: несумісні зміни встановлення, схеми памʼяті чи контракту хука.

Чеклист релізу:

1. Перенесіть відповідні записи `CHANGELOG.md` із розділу `Unreleased`.
2. Оновіть `VERSION`.
3. Запустіть `python scripts/check_version.py`.
4. Поставте теги релізних комітів як `vX.Y.Z`.
5. Опишіть кроки міграції для змін схеми памʼяті чи схеми походження.

## Дивіться також

- [MULTI-DEVICE-SYNC.md](MULTI-DEVICE-SYNC.md) - спільна памʼять між пристроями через гібридний бекенд Cloudflare
- [MULTI-USER.md](MULTI-USER.md) - один спільний акаунт, багато людей: приватне сховище на кожну людину плюс спільне сховище
- [USECASES.md](USECASES.md) - для чого ці налаштування на практиці
- [CHANGELOG.md](CHANGELOG.md) - історія змін цих налаштувань
- [LESSONS_LEARNED.md](LESSONS_LEARNED.md) - підводні камені та рішення дизайну
