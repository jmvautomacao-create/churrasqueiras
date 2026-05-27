# AGENTS.md — agente_churrasqueira

## Entrypoint

`python main.py` → `init_db()` → `WhatsAppBot().iniciar()` (Playwright Chromium, persistent session `data/whatsapp_session/`) → `escutar_mensagens()` (infinite loop).

## Architecture

| File | Role |
|---|---|
| `whatsapp_bot.py` | WhatsApp automation (Playwright), message loop, conversation FSM, dedup |
| `gemini_agent.py` | Google Gemini 2.0 Flash integration; fallback when quota exhausted |
| `database.py` | SQLite CRUD (`database/agente.db`) |
| `config.py` | Products (8), transportadoras (2), seller number, Gemini API key |
| `produtos.py` | Catalog/submenu text helpers |

## Bot Owner

`SEU_NUMERO = "555195036289"` in `config.py`. Bot responds to ALL incoming messages (no test number filter).

## Critical Dedup Chain (main loop, `escutar_mensagens`)

Checks applied in order per chat per cycle:

1. **`ultimo_visto_texto["tel\|texto"]`** (600s) — same message content from same user already processed successfully
2. **`ultimo_envio[nome_key]`** (10s) — bot just sent a message to this chat
3. **`ultimo_envio_texto[nome_key]`** — sidebar text matches last sent message (whitespace-normalized `startswith`)
4. **`ultimo_texto_chat[nome_key]`** — text unchanged from last cycle; if bot sent msg within 30s, clears `nao_lida` flag
5. **`primeiro_ciclo`** — first loop iteration populates `ultimo_texto_chat` without processing anything

After `processar_mensagem`, `ultimo_visto_texto` is set only if `ultimo_envio[nome_key]` was updated (send succeeded).

### Name Normalization (`_n()`)

All dict keys derived from sidebar names (`nome_key`) are normalized via `WhatsAppBot._n()` before access:
- NFKC Unicode normalization (collapses non-breaking spaces, ligatures, etc.)
- Whitespace collapsed to single space, trimmed
- Raw `nome_raw` (from DOM) is kept separate for `_abrir_chat_sidebar` (DOM interaction needs exact match)

This ensures consistent key matching across cycles even when WhatsApp Web returns Unicode variants.

### Skip Logging

Each dedup check logs a `[SKIP]` line at heartbeat intervals (`c % 30 == 0`) showing the reason, e.g.:
```
[210 SKIP] Jean BUSINESS: texto ja processado (45s atras)
[210 SKIP] Jean 1: envio recente (3.2s)
[210 SKIP] Maria: texto igual ao ultimo envio
```

### Periodic Dict Cleanup (`_limpar_dicts_antigos`)

Every 600 cycles (~8min), entries older than 7200s (2h) are removed from dedup dicts. `processando` stale locks (300s) are also cleaned. Throttled to once per hour.

## Gemini Quota (429)

Free tier exhausted daily. Behavior:
- `gerar_resposta()` raises 429 → `resposta_fallback()` returns `menu_interativo()` (full text catalog)
- `ultimo_fallback[telefone]` (3600s) prevents re-sending the full menu; instead sends: "Desculpe, estou temporariamente offline..."
- When fallback IS sent (every 3600s per user), it sends the complete product list in ONE message (no progressive carousel)

## Sidebar Truncation

WhatsApp Web sidebar replaces `\n` with spaces and truncates to ~80 chars. All dedup text comparisons use `re.sub(r'\s+', ' ', ...)` + `startswith` to handle this.

## Key Dicts

| Dict | Key | Value | Purpose |
|---|---|---|---|
| `processando` | nome_key (normalized) | bool | Concurrent processing lock |
| `ultimo_envio` | nome_key (normalized) | timestamp | Last successful send time |
| `ultimo_envio_texto` | nome_key (normalized) | full text | Last sent message content |
| `ultimo_visto_texto` | `"telefone\|texto"` | timestamp | Dedup for same user+text |
| `ultimo_texto_chat` | nome_key (normalized) | text | Last seen sidebar text |
| `ultimo_fallback` | telefone | timestamp | Gemini fallback throttle |
| `apresentacao_menu` | telefone | dict | Menu state (todos_enviados=True means done) |

## Media Structure

`media/churrasqueiras/<midia_dir>/` — each product has `folder.jpg`, optionally `*.jpg` (foto) and `*.mp4` (video).

## Frete Flow

1. Collect name → CPF → endereço (via `_parse_endereco` extracts cidade/estado/cep)
2. Save to `solicitacoes/*.xlsx` (14 fields vertical, `ENDERECO` stripped of cidade/estado/CEP)
3. Send WhatsApp to each TRANSPORTADORA with product + address
4. Parse reply via `extrair_valor_frete` / `extrair_prazo`, relay to client

## System Messages

WhatsApp business messaging notices ("Meta", "serviço seguro", "gerenciar esta conversa") are filtered out in `processar_mensagem`.

## .gitignore

Ignores: `__pycache__/`, `*.pyc`, `data/`, `database/agente.db`, `*.db`, `.env`, `solicitacoes/`, `~$*`.

## Python Version

3.14.4 on Windows. Provides `\d` future-warnings in JS strings inside triple-quoted Python (harmless).

## Auto-push

Every change must be committed and pushed to GitHub (branch `master`).
