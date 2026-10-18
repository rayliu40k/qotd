# Project boundaries

- Notion is the only persistent business source; never introduce a local business database.
- Codex performs DOCX parsing, semantic matching, source import, quote initialization and maintenance.
- Python implements daily random selection/publication only. No init/sync/migrate commands or AI API calls.
- For book initialization, follow the `initialize-daily-quote-book` skill and read qotd.toml before maintaining live Notion content.
- Use the exact six-block reading layout documented in that skill. No reflections, adjacent paragraphs, extra UI, or homepage database links.
- Preserve original book notes and existing daily snapshots. Reuse matching quote pages; do not silently duplicate or overwrite user data.
- Do not create test dates in real Notion. Use fake data for rotation and failure tests.
- Store credentials only in .env/environment; never print them or include them in artifacts. Keep .env mode 600.
- Single publishing machine only; no schedule is installed during this pilot. Scheduling requires the user's later request.
- Run pytest and ruff for relevant changes. Keep initialization scripts outside the application source.
