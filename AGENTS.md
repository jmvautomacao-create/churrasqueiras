# AGENTS.md — agente_churrasqueira

## Entrypoint

`python main.py` → `init_db()` → `WhatsAppBot().iniciar()` (Playwright Chromium, persistent session `data/whatsapp_session/`) → `escutar_mensagens()` (infinite loop).

## Multi-tarefa (Fila de Atendimento)

O bot atende múltiplos clientes simultaneamente usando uma fila assíncrona:

1. **`escutar_mensagens()`** (loop principal) — detecta novas mensagens e as coloca na `fila_mensagens` (`asyncio.Queue`)
2. **`_worker()`** (task separada) — retira mensagens da fila e chama `processar_mensagem()` uma por vez
3. **`fila_pendentes: set[str]`** — impede que o mesmo telefone seja enfileirado duas vezes
4. **Aviso de posição** — se o cliente já está na fila, recebe "Estou atendendo outros clientes no momento. Sua mensagem está na fila (posição ~N)." (throttle 30s)

O worker é criado em `iniciar()` após login confirmado e cancelado em `parar()`.

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

## Fila de Atendimento

O bot usa uma fila assíncrona (`asyncio.Queue`) para atender múltiplos clientes:

1. `escutar_mensagens()` detecta mensagens novas e as enfileira via `fila_mensagens.put()`
2. `_worker()` retira da fila e chama `processar_mensagem()` sequencialmente
3. `sidebar_lock` (`asyncio.Lock`) serializa acesso à sidebar entre worker e loop principal
4. `fila_pendentes: set[str]` impede enfileiramento duplicado do mesmo telefone
4. Se o cliente já está na fila, recebe aviso de posição (throttle 30s via `ultimo_aviso_fila`)
5. Stales em `fila_pendentes` são limpos após 600s em `_limpar_dicts_antigos`

## Critical Dedup Chain (main loop, `escutar_mensagens`)

Checks applied in order per chat per cycle. **ALL dedup dicts use `telefone` as key** (not `nome_key`), so name changes (e.g. phone number → saved contact) never break dedup:

1. **`ultimo_visto_texto["tel\|texto"]`** (600s) — same message content from same user already processed successfully
2. **`ultimo_envio[telefone]`** (10s) — bot just sent a message to this chat
3. **`ultimo_envio_texto[telefone]`** — sidebar text matches last sent message (whitespace-normalized `startswith`)
4. **`ultimo_texto_chat[telefone]`** — text unchanged from last cycle; if bot sent msg within 30s, clears `nao_lida` flag
5. **`primeiro_ciclo`** — first loop iteration populates `ultimo_texto_chat` without processing anything

After `processar_mensagem`, `ultimo_visto_texto` is set only if `ultimo_envio[telefone]` was updated (send succeeded).

### Processing Lock (`processando`)

Usa `telefone` como chave. É um lock secundário dentro de `processar_mensagem()` — funciona em conjunto com `fila_pendentes` para evitar processamento concorrente do mesmo usuário. A validação do telefone acontece ANTES do lock.

### Name Normalization (`_n()`)

Used for content normalization but NOT as dict key for dedup. Raw `nome_raw` (from DOM) is kept separate for `_abrir_chat_sidebar` (DOM interaction needs exact match).

### Skip Logging

Cada verificação de dedup loga um `[SKIP]` a cada heartbeat (`c % 30 == 0`) com o motivo:
```
[210 SKIP] Jean BUSINESS: texto já processado (45s atrás)
[210 SKIP] Jean 1: envio recente (3.2s)
[210 SKIP] Maria: texto igual ao último envio
```

Heartbeat também mostra o estado da fila: `fila: 2, pendentes: 2`.

## Chat Opening (`_abrir_chat_sidebar`)

Two search strategies:
1. **Name search**: `get_by_title(nome)` + JS NFKC-normalized fallback (5 attempts)
2. **Phone fallback**: if name search fails and `telefone` is provided, matches by stripping non-digits from row titles using `endsWith` (3 attempts)

Both `enviar_texto` and `enviar_midia` always open the correct chat before sending (no `tem_input` reuse). They iterate all known names from `mapa_contatos` before trying phone-only fallback.

## Submenu Continuar (`submenu_continuar`)

When the user responds to "Deseja mais alguma opcao? [1] SIM / [2] NAO":
- `"1"` or `"sim"` → reopens submenu
- `"2"`, `"nao"`, `"não"`, or `"voltar"` → returns to main menu
- **Anything else** → falls through to free conversation (Gemini/fallback), allowing the user to chat naturally

### Periodic Dict Cleanup (`_limpar_dicts_antigos`)

A cada 600 ciclos (~8min), entradas mais antigas que 7200s (2h) são removidas dos dicts de dedup. `processando` stale locks (300s), `fila_pendentes` travados (600s), e `ultimo_aviso_fila` (7200s) também são limpos. Throttled a 1x por hora.

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
| `processando` | telefone | bool | Lock secundário dentro de `processar_mensagem()` |
| `ultimo_envio` | telefone | timestamp | Last successful send time |
| `ultimo_envio_texto` | telefone | full text | Last sent message content |
| `ultimo_visto_texto` | `"telefone\|texto"` | timestamp | Dedup for same user+text |
| `ultimo_texto_chat` | telefone | text | Last seen sidebar text |
| `ultimo_fallback` | telefone | timestamp | Gemini fallback throttle |
| `apresentacao_menu` | telefone | dict | Menu state (todos_enviados=True means done) |
| `fila_pendentes` | telefone | str | Telefones na fila ou em processamento |
| `ultimo_aviso_fila` | telefone | timestamp | Throttle de aviso de posição na fila |

## Freight Monitor Definitivo

O monitor (`_monitorar_fretes`) roda a cada **10s** (não 3s) para reduzir overhead. A cada **60s** por transportadora ele:

1. Adquire `sidebar_lock`, navega para o chat da transportadora, lê a última mensagem (`_ler_msg_anterior_usuario`)
2. **SEMPRE volta ao chat do cliente** imediatamente após ler (mesmo em paths de erro/`continue`)
3. Se não há resposta nova (`resp == texto_antes`), continua sem fazer nada

Timeout de **30 min** sem resposta → marca como `respondido=True`, notifica o cliente.

Log de throttle condicional: 1 linha a cada 30 ciclos (~5 min).

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
