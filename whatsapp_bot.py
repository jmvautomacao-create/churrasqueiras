import asyncio
import json
import time
import re
import unicodedata
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

from config import PRODUTOS, SEU_NUMERO, TRANSPORTADORAS, BASE_DIR, PASTA_SOLICITACOES
from database import (
    cliente_por_telefone, criar_cliente, criar_conversa, salvar_mensagem,
    atualizar_etapa_conversa, atualizar_produto_interesse, criar_cotacao,
    atualizar_cotacao, criar_venda, get_historico_conversa, get_conversa_ativa,
    atualizar_cliente,
)
from gemini_agent import gerar_resposta, resposta_fallback, extrair_comando, limpar_resposta
from produtos import valor_produto, produto_por_id, detalhar


def safe(texto):
    if not isinstance(texto, str):
        texto = str(texto)
    return texto.encode('ascii', errors='replace').decode('ascii')


class WhatsAppBot:
    @staticmethod
    def _n(nome: str) -> str:
        nome = unicodedata.normalize('NFKC', nome)
        nome = re.sub(r'\s+', ' ', nome).strip()
        return nome

    def __init__(self):
        self.page = None
        self.context = None
        self.playwright = None
        self.logado = False
        self.processando: dict[str, bool] = {}
        self.ultimo_processamento: dict[str, float] = {}
        self.ultimo_texto_chat: dict[str, str] = {}
        self.ultimo_visto_texto: dict[str, float] = {}
        self.ultimo_envio: dict[str, float] = {}
        self.ultimo_envio_texto: dict[str, str] = {}
        self.mapa_contatos = {}
        self.ultimo_mapa = 0
        self.apresentacao_menu: dict[str, dict] = {}
        self.apresentacao_submenu: dict[str, dict] = {}
        self.continuar_submenu: dict[str, dict] = {}
        self.primeiro_ciclo = True
        self.ultimo_fallback: dict[str, float] = {}
        self.ultima_limpeza = 0.0
        self.chats_com_resposta: set[str] = set()

    async def iniciar(self):
        self.playwright = await async_playwright().start()
        user_data_dir = str(BASE_DIR / "data" / "whatsapp_session")

        sessao_dir = Path(user_data_dir)
        sessao_dir.mkdir(parents=True, exist_ok=True)
        print(f"Sessao: {user_data_dir}")

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=False,
        )
        self.page = await self.context.new_page()
        await self.page.goto("https://web.whatsapp.com")
        print("Aguardando login. Se ja estiver logado, isso leva segundos.")

        for i in range(120):
            await asyncio.sleep(2)
            try:
                url_atual = self.page.url
                titulo = await self.page.title()
                print(f"  [{i*2}s] {safe(titulo[:40])} | {safe(url_atual[:50])}")

                if "web.whatsapp.com" not in url_atual:
                    print("  -> Redirecionado, reabrindo web.whatsapp.com...")
                    await self.page.goto("https://web.whatsapp.com")
                    await asyncio.sleep(2)
                    continue

                panel = await self.page.query_selector('[data-testid="conversation-panel-main"]')
                if panel:
                    print("Login confirmado!")
                    self.logado = True
                    await asyncio.sleep(2)
                    return True

                side = await self.page.query_selector('#side')
                if side:
                    print("Sidebar detectada - logado!")
                    self.logado = True
                    await asyncio.sleep(2)
                    return True
            except Exception as e:
                print(f"  -> Erro: {safe(e)}")
                await asyncio.sleep(2)

        print("Tempo limite excedido.")
        return False

    async def avaliar(self, codigo: str, *args):
        try:
            return await self.page.evaluate(codigo, *args)
        except Exception as e:
            msg = str(e).lower()
            if "context" in msg or "navigation" in msg or "target closed" in msg:
                print(f"  -> Pagina perdida durante evaluate: {safe(str(e)[:60])}")
                await self._recuperar_pagina()
            raise

    async def _recuperar_pagina(self):
        print("  -> Recuperando pagina...")
        await asyncio.sleep(2)
        try:
            if not self.page or self.page.is_closed():
                self.page = await self.context.new_page()
            await self.page.goto("https://web.whatsapp.com", wait_until="load", timeout=30000)
        except Exception as e:
            print(f"  -> Erro na recuperacao: {safe(str(e)[:60])}, tentando nova pagina...")
            try:
                self.page = await self.context.new_page()
                await self.page.goto("https://web.whatsapp.com", wait_until="load", timeout=30000)
            except:
                pass
        for i in range(15):
            try:
                if await self.page.query_selector('#side'):
                    print("  -> Login confirmado apos recuperacao.")
                    await asyncio.sleep(2)
                    return
            except:
                pass
            await asyncio.sleep(1)
        print("  -> Pagina carregada (pode precisar de QR code).")
        await asyncio.sleep(2)

    async def _garantir_pagina_principal(self):
        try:
            url = self.page.url
            if "web.whatsapp.com" not in url:
                print("  -> Fora do WhatsApp, navegando...")
                await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(3)
        except:
            pass

    async def _iniciar_apresentacao_menu(self, telefone: str, conv_id: int, nome_sidebar: str = "") -> bool:
        from produtos import menu_interativo
        texto = menu_interativo()
        ok = await self.enviar_para_cliente(telefone, texto, nome_sidebar)
        if not ok:
            return False
        salvar_mensagem(conv_id, "agente", texto)
        self.apresentacao_menu[telefone] = {
            "conv_id": conv_id,
            "apresentados": [p["id"] for p in PRODUTOS],
            "todos_enviados": True,
        }
        atualizar_etapa_conversa(conv_id, "apresentacao_menu")
        return True

    async def _avancar_apresentacao_menu(self, telefone: str, conv_id: int, estado: dict):
        pass

    async def _iniciar_apresentacao_submenu(self, telefone: str, conv_id: int, produto: dict):
        from produtos import submenu_produto
        texto = submenu_produto(produto)
        await self.enviar_para_cliente(telefone, texto)
        salvar_mensagem(conv_id, "agente", texto)
        self.apresentacao_submenu[telefone] = {
            "conv_id": conv_id,
            "produto_id": produto["id"],
            "apresentados": [1, 2, 3, 4, 5, 6],
            "todos_enviados": True,
        }
        atualizar_etapa_conversa(conv_id, "apresentacao_submenu")

    async def _avancar_apresentacao_submenu(self, telefone: str, conv_id: int, estado: dict):
        pass

    async def _executar_opcao_submenu(self, telefone: str, conv_id: int, produto_id: int, opt: int, nome_sidebar: str = ""):
        produto = produto_por_id(produto_id)
        if not produto:
            return
        if opt == 1:
            await self._enviar_folder(conv_id, telefone, produto)
        elif opt == 2:
            resp = valor_produto(produto)
            await self.enviar_para_cliente(telefone, resp)
            salvar_mensagem(conv_id, "agente", resp)
        elif opt == 3:
            await self._enviar_foto(conv_id, telefone, produto)
        elif opt == 4:
            await self._enviar_video(conv_id, telefone, produto)
        elif opt == 5:
            atualizar_produto_interesse(conv_id, produto["id"])
            atualizar_etapa_conversa(conv_id, "frete_nome")
            await self.enviar_para_cliente(telefone,
                f"Para solicitar o frete da {produto['nome']}, preciso de alguns dados.\n\n"
                f"Primeiro, informe seu NOME completo:")
            salvar_mensagem(conv_id, "agente", "Solicitando dados para frete - informe o nome:")
            return
        elif opt == 6:
            self.apresentacao_submenu.pop(telefone, None)
            await self.enviar_para_cliente(telefone, "Voltando ao Menu Principal...", nome_sidebar)
            ok = await self._iniciar_apresentacao_menu(telefone, conv_id, nome_sidebar)
            if ok:
                print(f"  -> Menu reiniciado para {safe(telefone)}", flush=True)
            return
        chaves = [k for k in self.ultimo_visto_texto if k.startswith(f"{telefone}|")]
        for k in chaves:
            self.ultimo_visto_texto.pop(k, None)
        self.continuar_submenu[telefone] = {"conv_id": conv_id, "produto_id": produto_id, "nome_sidebar": nome_sidebar}
        atualizar_etapa_conversa(conv_id, "submenu_continuar")
        await self.enviar_para_cliente(telefone,
            "Selecione uma Opcao abaixo:\n[1] Continuar neste produto\n[2] Voltar ao Menu Principal",
            nome_sidebar)

    async def _atualizar_mapa_contatos(self):
        agora = time.time()
        if agora - self.ultimo_mapa < 30:
            return
        try:
            raw = await self.avaliar("""
                async (selfNum) => {
                    const db = await new Promise(r => {
                        const req = indexedDB.open('model-storage');
                        req.onsuccess = () => r(req.result);
                    });
                    const out = {};

                    // 1. Contact store: extrai telefone apenas de JIDs com dominio c.us ou s.whatsapp.net
                    {
                        const tx = db.transaction('contact', 'readonly');
                        const store = tx.objectStore('contact');
                        const all = await new Promise(r => {
                            const req = store.getAll();
                            req.onsuccess = () => r(req.result);
                        });
                        for (const c of all) {
                            const name = c.name || c.pushname || '';
                            if (!name || !c.id) continue;
                            const parts = c.id.split('@');
                            const domain = parts[1] || '';
                            const phone = parts[0];
                            if ((domain === 'c.us' || domain === 's.whatsapp.net') && /^\\d+$/.test(phone) && phone !== selfNum) {
                                out[name] = phone;
                            }
                        }
                    }

                    // 2. Message store: lid -> phone, cruzar com contact names
                    {
                        const lidPhone = {};
                        const tx = db.transaction('message', 'readonly');
                        const store = tx.objectStore('message');
                        const all = await new Promise(r => {
                            const req = store.getAll();
                            req.onsuccess = () => r(req.result);
                        });
                        for (const m of all) {
                            if (!m.id) continue;
                            const parts = m.id.split('_');
                            if (parts.length < 2) continue;
                            const lid = parts[1];
                            if (lidPhone[lid]) continue;
                            let phone = '';
                            if (m.from && typeof m.from === 'string') {
                                const match = m.from.match(/^(\\d+)@/);
                                if (match && match[1] !== selfNum) phone = match[1];
                            }
                            if (!phone && m.to) {
                                const toUser = typeof m.to === 'object' ? (m.to.user || '') :
                                               (typeof m.to === 'string' ? m.to.split('@')[0] : '');
                                if (/^\\d+$/.test(toUser) && toUser !== selfNum) phone = toUser;
                            }
                            if (phone) lidPhone[lid] = phone;
                        }
                        const tx2 = db.transaction('contact', 'readonly');
                        const store2 = tx2.objectStore('contact');
                        const all2 = await new Promise(r => {
                            const req = store2.getAll();
                            req.onsuccess = () => r(req.result);
                        });
                        for (const c of all2) {
                            const name = c.name || c.pushname || '';
                            if (!name || !c.id) continue;
                            const phone = lidPhone[c.id];
                            if (phone && !out[name]) out[name] = phone;
                        }
                    }

                    return JSON.stringify(out);
                }
            """, SEU_NUMERO)
            self.mapa_contatos = json.loads(raw)
            self.ultimo_mapa = agora
            print(f"  [mapa] {len(self.mapa_contatos)} contatos mapeados")
        except Exception as e:
            print(f"  [mapa] erro: {safe(str(e)[:80])}")

    async def _limpar_dicts_antigos(self):
        agora = time.time()
        if agora - self.ultima_limpeza < 3600:
            return
        self.ultima_limpeza = agora
        limite = 7200
        for k in list(self.ultimo_visto_texto):
            if agora - self.ultimo_visto_texto[k] > limite:
                del self.ultimo_visto_texto[k]
        for k in list(self.ultimo_envio):
            if agora - self.ultimo_envio[k] > limite:
                del self.ultimo_envio[k]
        for k in list(self.ultimo_envio_texto):
            if agora - self.ultimo_envio.get(k, 0) > limite:
                del self.ultimo_envio_texto[k]
        for k in list(self.ultimo_texto_chat):
            if agora - self.ultimo_envio.get(k, 0) > limite:
                del self.ultimo_texto_chat[k]
        for k in list(self.ultimo_fallback):
            if agora - self.ultimo_fallback[k] > limite:
                del self.ultimo_fallback[k]
        for k in list(self.ultimo_processamento):
            if agora - self.ultimo_processamento[k] > limite:
                del self.ultimo_processamento[k]
        for k in list(self.processando):
            if agora - self.ultimo_processamento.get(k, 0) > 300:
                del self.processando[k]
        print(f"  -> Dicts limpos (retidos {limite//3600}h)", flush=True)

    async def detectar_chats(self):
        await self._garantir_pagina_principal()
        await self._atualizar_mapa_contatos()
        mapa_str = json.dumps(self.mapa_contatos)
        codigo = """
            (mapaStr) => {
                const mapa = JSON.parse(mapaStr);
                const achados = [];
                const side = document.querySelector('#side') ||
                             document.querySelector('[role="tabpanel"]');
                if (!side) {
                    const rows = document.querySelectorAll('[role="row"]');
                    if (rows.length > 0) {
                        rows.forEach((row, i) => {
                            if (i > 30) return;
                            const el = row.querySelector('[title]');
                            const nome = el ? el.getAttribute('title') : '';
                            if (nome && nome.length < 30 && nome !== 'Filtrar conversas' && !nome.startsWith('Filt')) {
                                const spans = row.querySelectorAll('span[dir]');
                                let texto = '';
                                const titulo = el ? el.getAttribute('title') : '';
                                for (const sp of spans) {
                                    if (sp.getAttribute('title') !== titulo && sp.textContent.trim()) {
                                        texto = sp.textContent.trim();
                                    }
                                }
                                if (texto.startsWith('default-')) return;
                                const badge = row.querySelector('[data-testid="icon-unread-count"]') ||
                                             row.querySelector('[aria-label*="nao lida"]') ||
                                             row.querySelector('[aria-label*="unread"]');
                                let telefone = nome.replace(/\\D/g, '');
                                if (!telefone || telefone.length < 10) {
                                    telefone = mapa[nome] || '';
                                }
                                if (!texto && !telefone) return;
                                achados.push({nome, texto, nao_lida: !!badge, telefone});
                            }
                        });
                        return JSON.stringify(achados);
                    }
                    return '[]';
                }

                const chats = side.querySelectorAll(':scope [role="row"]');
                chats.forEach(chat => {
                    const el = chat.querySelector('[title]');
                    const nome = el ? el.getAttribute('title') : '';
                    if (!nome || nome.length > 30 || nome === 'Filtrar conversas' || nome.startsWith('Filt')) return;

                    const spans = chat.querySelectorAll('span[dir]');
                    let texto = '';
                    const titulo = el ? el.getAttribute('title') : '';
                    for (const sp of spans) {
                        if (sp.getAttribute('title') !== titulo && sp.textContent.trim()) {
                            texto = sp.textContent.trim();
                        }
                    }
                    if (texto.startsWith('default-')) return;

                    const badge = chat.querySelector('[data-testid="icon-unread-count"]') ||
                                 chat.querySelector('[aria-label*="nao lida"]') ||
                                 chat.querySelector('[aria-label*="unread"]');

                    let telefone = nome.replace(/\\D/g, '');
                    if (!telefone || telefone.length < 10) {
                        telefone = mapa[nome] || '';
                    }

                    if (!texto && !telefone) return;

                    achados.push({nome, texto, nao_lida: !!badge, telefone});
                });
                return JSON.stringify(achados);
            }
        """
        return await self.avaliar(codigo, mapa_str)

    async def escutar_mensagens(self):
        print("\n" + "="*50)
        print("Ouvindo mensagens... Ctrl+C para parar.")
        print("="*50 + "\n")

        c = 0
        erros_consecutivos = 0
        while True:
            try:
                c += 1
                raw = await self.detectar_chats()
                chats = json.loads(raw)
                erros_consecutivos = 0

                if c % 10 == 0:
                    print(f"  [{c}] heartbeat - {len(chats)} chats, {len(self.apresentacao_menu)} menu, {len(self.apresentacao_submenu)} submenu")

                vistos_ciclo = set()
                for chat in chats:
                    nome_raw = chat.get("nome", "")
                    nome_key = self._n(nome_raw) if nome_raw else ""
                    texto = chat.get("texto", "")
                    nao_lida = chat.get("nao_lida", False)
                    telefone = chat.get("telefone", "")

                    if not nome_raw or nome_raw == "DEBUG" or nome_raw.startswith("Filt"):
                        continue

                    # Dedup intra-ciclo: chats duplicados (ex: role="row" aninhado)
                    if nome_key in vistos_ciclo:
                        continue
                    vistos_ciclo.add(nome_key)

                    if not telefone or len(telefone) < 12:
                        continue

                    if c % 30 == 0 or nao_lida:
                        marca = f" [tel:{telefone}]" if telefone else ""
                        print(f"  [{c}] {safe(nome_raw)}{marca}: {'[NAO LIDA] ' if nao_lida else ''}{safe(texto[:60])}")

                    # Dedup: sem texto nao processar repetido
                    agora = time.time()
                    if not texto:
                        ultimo = self.ultimo_processamento.get(telefone, 0)
                        if agora - ultimo < 120:
                            if c % 30 == 0:
                                print(f"  [{c} SKIP] {safe(nome_raw)}: sem texto, processado ha {agora-ultimo:.0f}s")
                            continue

                    # Dedup: mesma mensagem do usuario ja processada com sucesso
                    if texto:
                        chave = f"{telefone}|{self._n(texto)}"
                        ult_visto = self.ultimo_visto_texto.get(chave, 0)
                        if agora - ult_visto < 600:
                            if c % 30 == 0:
                                print(f"  [{c} SKIP] {safe(nome_raw)}: texto ja processado ({agora-ult_visto:.0f}s atras)")
                            continue

                    # Pula se o bot acabou de enviar mensagem pra este chat
                    if self.ultimo_envio.get(telefone, 0) > agora - 10:
                        if c % 30 == 0:
                            env_ha = agora - self.ultimo_envio.get(telefone, 0)
                            print(f"  [{c} SKIP] {safe(nome_raw)}: envio recente ({env_ha:.1f}s)")
                        continue
                    ultimo_env = self.ultimo_envio_texto.get(telefone, "")
                    if texto and ultimo_env:
                        texto_norm = re.sub(r'\s+', ' ', texto).strip()
                        envio_norm = re.sub(r'\s+', ' ', ultimo_env).strip()
                        if envio_norm.startswith(texto_norm) or texto_norm.startswith(envio_norm):
                            if c % 30 == 0:
                                print(f"  [{c} SKIP] {safe(nome_raw)}: texto igual ao ultimo envio")
                            continue

                    # Fallback: detectar por mudanca de texto (msgs sem badge)
                    ultimo_texto = self.ultimo_texto_chat.get(telefone, "")
                    if texto and texto != ultimo_texto:
                        self.ultimo_texto_chat[telefone] = texto
                        if not nao_lida:
                            nao_lida = True
                    elif texto and texto == ultimo_texto and nao_lida:
                        ult_env = self.ultimo_envio.get(telefone, 0)
                        if ult_env > 0 and agora - ult_env < 30:
                            nao_lida = False
                        elif ult_env == 0 and telefone in self.chats_com_resposta:
                            if c % 30 == 0:
                                print(f"  [{c} SKIP] {safe(nome_raw)}: conversa antiga sem nova mensagem")
                            nao_lida = False

                    # Primeiro ciclo: popula ultimo_texto_chat e descobre chats com resposta previa
                    if self.primeiro_ciclo:
                        if telefone not in self.chats_com_resposta and not texto:
                            pass  # sem texto na sidebar, sem info
                        elif telefone not in self.chats_com_resposta:
                            conversa = get_conversa_ativa(telefone)
                            if conversa:
                                h = get_historico_conversa(conversa["conversa_id"], limite=1)
                                if any(m["origem"] == "agente" for m in h):
                                    self.chats_com_resposta.add(telefone)
                        continue

                    if nao_lida:
                        self.ultimo_processamento[telefone] = agora
                        print(f"\n>>> NOVA MENSAGEM: {safe(nome_raw)}: {safe(texto)}", flush=True)
                        if texto:
                            antes = self.ultimo_envio.get(telefone, 0)
                        await self.processar_mensagem(nome_key, texto, telefone, nome_raw)
                        if texto:
                            depois = self.ultimo_envio.get(telefone, 0)
                            if depois > antes:
                                self.ultimo_visto_texto[f"{telefone}|{self._n(texto)}"] = time.time()
                        continue

                self.primeiro_ciclo = False

                # Auto-advance removido: menu e submenu sao enviados completos em uma unica mensagem

                if c % 600 == 0:
                    await self._limpar_dicts_antigos()

                await asyncio.sleep(0.8)

            except asyncio.CancelledError:
                break
            except json.JSONDecodeError:
                print(f"  [DEBUG] JSON invalido: {safe(raw)[:100]}")
                erros_consecutivos += 1
                await asyncio.sleep(5)
            except Exception as e:
                msg = str(e).lower()
                if "context" in msg or "navigation" in msg or "target closed" in msg:
                    print(f"  [NAV] Pagina perdida, tentando recuperar...")
                    await self._recuperar_pagina()
                    erros_consecutivos = 0
                else:
                    print(f"[ERRO] {safe(e)}")
                    import traceback
                    traceback.print_exc()
                    erros_consecutivos += 1
                await asyncio.sleep(5)

            if erros_consecutivos > 10:
                print("[AVISO] Muitos erros consecutivos. Reiniciando pagina...")
                await self._recuperar_pagina()
                erros_consecutivos = 0

    async def _enviar_com_evaluate(self, acao_js: str, max_tentativas: int = 30):
        for _ in range(max_tentativas):
            try:
                ok = await self.avaliar(acao_js)
                if ok:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    SELETOR_INPUT = '#main [contenteditable="true"]'

    async def _aguardar_input(self, timeout=4):
        for _ in range(timeout * 2):
            el = await self.page.query_selector(self.SELETOR_INPUT)
            if el:
                return el
            await asyncio.sleep(0.25)
        return None

    async def _digitar(self, texto: str):
        caixa = await self._aguardar_input(4)
        if not caixa:
            print("  [DIG] Input nao encontrado")
            return False
        try:
            await caixa.fill(texto)
            return True
        except Exception:
            try:
                await caixa.evaluate("el => { el.focus(); el.innerHTML = ''; }")
                await self.page.keyboard.type(texto, delay=20)
                return True
            except Exception as e:
                print(f"  [DIG] Falha ao digitar: {safe(str(e)[:60])}")
                return False

    async def _clicar_enviar(self, max_tentativas=15, usar_enter=False):
        for i in range(max_tentativas):
            if usar_enter:
                try:
                    await self.page.keyboard.press("Enter")
                    await asyncio.sleep(0.2)
                    ok = await self.avaliar("""
                        () => {
                            const spans = document.querySelectorAll('span[data-icon="send"]');
                            for (const sp of spans) {
                                if (sp.offsetParent !== null) return false;
                            }
                            return true;
                        }
                    """)
                    if ok:
                        return True
                except:
                    pass

            ok = await self.avaliar("""
                () => {
                    const botoes = document.querySelectorAll('button');
                    for (const btn of botoes) {
                        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                        if ((label.includes('enviar') || label.includes('send')) && btn.offsetParent !== null) {
                            btn.click();
                            return true;
                        }
                    }
                    const spans = document.querySelectorAll('span[data-icon="send"]');
                    for (const sp of spans) {
                        const pai = sp.closest('button') || sp.parentElement;
                        if (pai && pai.offsetParent !== null) { pai.click(); return true; }
                        if (sp.offsetParent !== null) { sp.click(); return true; }
                    }
                    const divs = document.querySelectorAll('div[role="button"]');
                    for (const d of divs) {
                        const label = (d.getAttribute('aria-label') || '').toLowerCase();
                        if ((label.includes('enviar') || label.includes('send')) && d.offsetParent !== null) {
                            d.click(); return true;
                        }
                    }
                    return false;
                }
            """)
            if ok:
                return True
            await asyncio.sleep(0.25)
        return False

    async def _abrir_chat_sidebar(self, nome: str = "", telefone: str = "") -> bool:
        try:
            await self.page.wait_for_selector('#side', timeout=10000)
            if nome:
                for _ in range(5):
                    try:
                        el = self.page.get_by_title(nome).first
                        if await el.count() > 0 and await el.is_visible():
                            await el.click()
                            await asyncio.sleep(0.4)
                            panel = await self.page.query_selector('[data-testid="conversation-panel-main"]')
                            if panel:
                                return True
                    except Exception:
                        pass
                    alvo = json.dumps(nome)
                    ok = await self.avaliar(f"""
                        () => {{
                            const norm = s => s.normalize('NFKC').replace(/[\\s\\u00a0\\u200b\\u200c\\u200d\\ufeff]+/g, ' ').trim();
                            const rows = document.querySelectorAll('#side [role="row"]');
                            const alvo = {alvo};
                            const alvo_norm = norm(alvo);
                            for (const row of rows) {{
                                const el = row.querySelector('[title]');
                                if (el && norm(el.getAttribute('title')) === alvo_norm) {{
                                    row.click();
                                    return true;
                                }}
                            }}
                            return false;
                        }}
                    """)
                    if ok:
                        await asyncio.sleep(0.4)
                        return True
                    await asyncio.sleep(0.5)
            if telefone:
                for _ in range(3):
                    ok = await self.avaliar(f"""
                        () => {{
                            const tel = {json.dumps(telefone)};
                            const rows = document.querySelectorAll('#side [role="row"]');
                            for (const row of rows) {{
                                const titleEl = row.querySelector('[title]');
                                if (!titleEl) continue;
                                const titleTel = (titleEl.getAttribute('title') || '').replace(/\\D/g, '');
                                if (titleTel.endsWith(tel) || tel.endsWith(titleTel)) {{
                                    row.click();
                                    return true;
                                }}
                            }}
                            return false;
                        }}
                    """)
                    if ok:
                        await asyncio.sleep(0.4)
                        return True
                    await asyncio.sleep(0.5)
            return False
        except Exception as e:
            print(f"  [sidebar erro] {safe(str(e)[:80])}", flush=True)
            return False
    async def enviar_texto(self, numero: str, texto: str, nome_sidebar: str = "") -> bool:
        try:
            # Always open the correct chat first (prevents sending to wrong contact when
            # a previous chat's input field is still visible)
            if not nome_sidebar:
                nome_sidebar = next((n for n, t in self.mapa_contatos.items() if t == numero), "")
            nomes = [nome_sidebar] if nome_sidebar else []
            nomes += [n for n, t in self.mapa_contatos.items() if t == numero]
            chat_aberto = False
            for nome in nomes:
                if not nome:
                    continue
                if await self._abrir_chat_sidebar(nome, numero):
                    chat_aberto = True
                    break
            if not chat_aberto:
                print(f"  -> Nao foi possivel abrir chat para {numero}", flush=True)
                return False

            tem_input = await self.page.wait_for_selector(self.SELETOR_INPUT, timeout=5000)
            if not tem_input:
                print(f"  -> Input nao disponivel para {numero}", flush=True)
                return False

            ok_dig = await self._digitar(texto)
            if not ok_dig:
                print(f"  -> Input nao disponivel para {numero}", flush=True)
                return False
            if await self._clicar_enviar():
                print(f"  -> Enviado para {numero}", flush=True)
                primeira_linha = texto.split("\n")[0][:80]
                self.ultimo_texto_chat[numero] = primeira_linha
                self.ultimo_envio[numero] = time.time()
                self.ultimo_envio_texto[numero] = texto
                if primeira_linha:
                    self.ultimo_visto_texto[f"{numero}|{self._n(primeira_linha)}"] = time.time()
                return True

            print(f"  -> Falha ao enviar para {numero}", flush=True)
            return False
        except Exception as e:
            print(f"[ERRO ENVIO] {safe(e)}", flush=True)
            return False

    async def _clicar_anexar(self):
        return await self.avaliar("""
            () => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const label = (b.getAttribute('aria-label') || '').toLowerCase();
                    if ((label.includes('anexar') || label.includes('attach')) && b.offsetParent !== null) {
                        b.click(); return true;
                    }
                }
                const divs = document.querySelectorAll('[data-testid="attach-file"]');
                for (const d of divs) { if (d.offsetParent !== null) { d.click(); return true; } }
                return false;
            }
        """)

    async def _enviar_midia_como_foto(self, caminho: str):
        # Estrategia A: tenta foto ampliavel via file chooser
        await self._clicar_anexar()
        await asyncio.sleep(0.5)
        tem_pv = await self.avaliar("""
            () => {
                const el = document.querySelector('[data-testid="photo-video"]');
                return !!el && el.offsetParent !== null;
            }
        """)
        if tem_pv:
            for _ in range(2):
                try:
                    async with self.page.expect_file_chooser(timeout=5000) as fc_info:
                        await self.avaliar("""
                            () => { document.querySelector('[data-testid="photo-video"]').click(); }
                        """)
                        await asyncio.sleep(0.3)
                    fc = await fc_info.value
                    await fc.set_files(str(caminho))
                    await asyncio.sleep(3)
                    return True
                except Exception:
                    await asyncio.sleep(1)

        # Estrategia B: input[accept*=image] diretamente
        try:
            img_inp = self.page.locator('input[accept*="image"]').first
            if await img_inp.count() > 0:
                await img_inp.set_input_files(str(caminho))
                await asyncio.sleep(3)
                return True
        except Exception:
            pass

        return False

    async def _enviar_midia_como_documento(self, caminho: str):
        try:
            async with self.page.expect_file_chooser(timeout=5000) as fc_info:
                await self._clicar_anexar()
                await asyncio.sleep(0.5)
                tem_doc = await self.avaliar("""
                    () => { const el = document.querySelector('[data-testid="attach-document"]'); return !!el && el.offsetParent !== null; }
                """)
                if not tem_doc:
                    return False
                await self.avaliar("""
                    () => { const el = document.querySelector('[data-testid="attach-document"]'); if (el) el.click(); }
                """)
                await asyncio.sleep(0.3)
            fc = await fc_info.value
            await fc.set_files(str(caminho))
            await asyncio.sleep(3)
            return True
        except Exception:
            pass
        return False

    async def enviar_midia(self, numero: str, caminho: str, legenda: str = ""):
        try:
            # Always open the correct chat first
            chat_aberto = False
            nomes = list(dict.fromkeys(n for n, t in self.mapa_contatos.items() if t == numero))
            for nome in nomes:
                if not nome:
                    continue
                if await self._abrir_chat_sidebar(nome, numero):
                    chat_aberto = True
                    break
            if not chat_aberto:
                # Tentar fallback apenas por telefone
                if not await self._abrir_chat_sidebar(telefone=numero):
                    print(f"  -> Nao foi possivel abrir chat para midia {numero}", flush=True)
                    return
            await asyncio.sleep(0.5)

            tem_input = await self.page.query_selector(self.SELETOR_INPUT)
            if not tem_input:
                print(f"  -> Input nao disponivel para midia {numero}", flush=True)
                return

            is_img = Path(caminho).suffix.lower() in (".jpg", ".jpeg", ".png")
            ok = False

            if is_img:
                ok = await self._enviar_midia_como_foto(caminho)
                if not ok:
                    print("  -> Fallback: enviando como documento")
                    await self.page.locator('input[type="file"]').first.set_input_files(str(caminho))
                    await asyncio.sleep(3)
                    ok = True
            else:
                ok = await self._enviar_midia_como_documento(caminho)
                if not ok:
                    await self.page.locator('input[type="file"]').first.set_input_files(str(caminho))
                    await asyncio.sleep(3)
                    ok = True

            if legenda:
                cap = await self.page.query_selector('[data-testid="caption-input"]')
                if cap:
                    try:
                        await cap.fill("")
                        await cap.type(legenda, delay=20)
                    except:
                        await cap.evaluate("el => el.focus()")
                        await self.page.keyboard.type(legenda)
                await asyncio.sleep(0.5)

            if await self._clicar_enviar(15, usar_enter=True):
                print(f"  -> Midia enviada: {Path(caminho).name}")
                nome_midia = next((n for n, t in self.mapa_contatos.items() if t == numero), None)
                if nome_midia:
                    self.ultimo_texto_chat[self._n(nome_midia)] = f"📷 {Path(caminho).name}"
                await asyncio.sleep(1)
                return
            print(f"  -> Falha ao enviar midia: {Path(caminho).name}")
        except Exception as e:
            print(f"[ERRO MIDIA] {safe(e)}")

    async def enviar_para_cliente(self, numero: str, texto: str, nome_sidebar: str = "") -> bool:
        return await self.enviar_texto(numero, texto, nome_sidebar)

    async def enviar_midia_para_cliente(self, numero: str, caminho: str, legenda: str = ""):
        await self.enviar_midia(numero, caminho, legenda)

    async def solicitar_frete_transportadora(self, transportadora: dict, produto, cliente_info: dict):
        msg = (
            f"Ola {transportadora['nome']}, solicitacao de cotacao de frete:\n"
            f"Produto: {produto['nome']}\n"
            f"Dimensoes: {produto['medidas']}  Peso: {produto['peso']}\n"
            f"Endereco: {cliente_info.get('endereco', 'N/I')} - "
            f"{cliente_info.get('cidade', 'N/I')}/{cliente_info.get('estado', 'N/I')} "
            f"CEP: {cliente_info.get('cep', 'N/I')}\n"
            f"Favor informar valor do frete e prazo."
        )
        await self.enviar_texto(transportadora["numero"], msg)
        return transportadora["nome"]

    async def aguardar_resposta_transportadora(self, transportadora_nome: str, timeout: int = 120) -> str | None:
        inicio = time.time()
        while time.time() - inicio < timeout:
            await asyncio.sleep(5)
            raw = await self.detectar_chats()
            chats = json.loads(raw)
            for chat in chats:
                if transportadora_nome.lower() not in chat["nome"].lower():
                    continue
                if not chat["nao_lida"]:
                    continue
                chave = f"{chat['nome']}|{chat['texto']}"
                if chave not in self.vistos:
                    self.vistos.add(chave)
                    return chat["texto"]
        return None

    async def _enviar_folder(self, conv_id: int, telefone: str, produto: dict):
        md = BASE_DIR / "media" / "churrasqueiras" / produto["midia_dir"]
        folder = md / "folder.jpg"
        if folder.exists():
            await self.enviar_midia_para_cliente(telefone, folder, produto["nome"])
            salvar_mensagem(conv_id, "agente", "[folder.jpg]", "foto")
        else:
            await self.enviar_para_cliente(telefone, "Folder nao disponivel para este produto.")
            salvar_mensagem(conv_id, "agente", "Folder nao disponivel.")

    async def _enviar_foto(self, conv_id: int, telefone: str, produto: dict):
        md = BASE_DIR / "media" / "churrasqueiras" / produto["midia_dir"]
        fotos = sorted([f for f in md.glob("*") if f.suffix.lower() in (".jpg", ".jpeg", ".png")])
        if fotos:
            await self.enviar_midia_para_cliente(telefone, fotos[0], produto["nome"])
            salvar_mensagem(conv_id, "agente", f"[foto: {fotos[0].name}]", "foto")
        else:
            await self.enviar_para_cliente(telefone, "Foto nao disponivel para este produto.")

    async def _enviar_video(self, conv_id: int, telefone: str, produto: dict):
        md = BASE_DIR / "media" / "churrasqueiras" / produto["midia_dir"]
        videos = [f for f in md.glob("*") if f.suffix.lower() in (".mp4", ".mov")]
        if videos:
            await self.enviar_midia_para_cliente(telefone, videos[0], produto["nome"])
            salvar_mensagem(conv_id, "agente", f"[video: {videos[0].name}]", "video")
        else:
            await self.enviar_para_cliente(telefone, "Video nao disponivel para este produto.")

    def _parse_endereco(self, endereco: str) -> dict:
        info = {"endereco": endereco}
        cep_match = re.search(r"(\d{5}-?\d{3})", endereco)
        if cep_match:
            info["cep"] = cep_match.group(1)
        else:
            ultimos_digitos = re.findall(r"\d+", endereco)
            for seq in reversed(ultimos_digitos):
                if len(seq) >= 5:
                    info["cep"] = seq
                    break

        ufs = {"SP","RJ","MG","RS","PR","SC","BA","DF","GO","MT","MS",
               "ES","CE","RN","PE","PB","AL","SE","PI","MA","PA","AM",
               "AC","RO","RR","AP","TO"}

        # Method 1: comma-separated (cidade/UF separados por virgula)
        partes_virgula = [p.strip() for p in endereco.replace("\n", ",").split(",") if p.strip()]
        if len(partes_virgula) >= 3:
            for i, parte in enumerate(partes_virgula):
                palavras = parte.split()
                for p in palavras:
                    if p.upper() in ufs:
                        info["estado"] = p.upper()
                        if i > 0:
                            info["cidade"] = partes_virgula[i - 1]
                        break
                if "estado" in info:
                    break

        # Method 2: space-separated fallback (sem virgulas)
        if "estado" not in info:
            partes = endereco.replace(",", " ").split()
            for i, p in enumerate(partes):
                if p.upper() in ufs:
                    info["estado"] = p.upper()
                    palavras_cidade = []
                    for j in range(i - 1, -1, -1):
                        if not any(c.isdigit() for c in partes[j]):
                            palavras_cidade.insert(0, partes[j])
                        else:
                            break
                    if palavras_cidade:
                        info["cidade"] = " ".join(palavras_cidade)
                    break
        return info

    def _limpar_endereco(self, endereco: str, cidade: str, estado: str, cep: str) -> str:
        clean = endereco
        if cep:
            clean = re.sub(rf"\s*,?\s*{re.escape(cep)}\s*", "", clean)
        if estado:
            clean = re.sub(rf"\s*,?\s*{re.escape(estado)}\s*,?\s*$", "", clean)
        if cidade:
            clean = re.sub(rf"\s*,?\s*{re.escape(cidade)}\s*,?\s*$", "", clean)
        clean = re.sub(r"\s*,\s*", ",", clean)
        clean = re.sub(r",+", ",", clean)
        return clean.strip().strip(",").strip()

    def _salvar_solicitacao_frete(self, telefone, nome, cpf, endereco, cidade, estado, cep):
        from openpyxl import Workbook
        pasta = PASTA_SOLICITACOES
        pasta.mkdir(exist_ok=True)
        agora = datetime.now()
        nome_limpo = re.sub(r"[^\w]", "", nome)[:20] or "cliente"
        nome_arquivo = f"Solicitacao_Frete_{nome_limpo}_{agora.strftime('%d-%m-%Y')}_{agora.strftime('%H%M')}.xlsx"
        caminho = pasta / nome_arquivo
        cabecalhos = ["CAMPO", "VALOR"]
        endereco_limpo = self._limpar_endereco(endereco, cidade, estado, cep)
        conversa = get_conversa_ativa(telefone)
        produto_id = (conversa or {}).get("produto_interesse_id")
        produto = produto_por_id(produto_id) if produto_id else None
        dados = [
            ("DATA/HORA", agora.strftime("%d/%m/%Y %H:%M")),
            ("NOME", nome),
            ("WHATSAPP", telefone),
            ("CPF/CNPJ", cpf),
            ("ENDERECO", endereco_limpo),
            ("CIDADE", cidade),
            ("ESTADO", estado),
            ("CEP", cep),
            ("PRODUTO", produto["nome"] if produto else "N/I"),
            ("PRECO", f"R$ {produto['preco']:.2f}" if produto else "N/I"),
            ("MEDIDAS", produto["medidas"] if produto else "N/I"),
            ("PESO", produto["peso"] if produto else "N/I"),
            ("VALOR DO FRETE", ""),
            ("STATUS", "Pendente"),
        ]
        wb = Workbook()
        ws = wb.active
        ws.append(cabecalhos)
        for campo, valor in dados:
            ws.append([campo, valor])
        wb.save(caminho)
        print(f"  -> Solicitacao salva: {nome_arquivo}", flush=True)

    async def _ler_msg_anterior_usuario(self):
        raw = await self.avaliar("""
            () => {
                const painel = document.querySelector('#main [data-testid="conversation-panel-messages"]');
                if (!painel) return '';
                const msgs = painel.querySelectorAll(':scope .message-in');
                const usuarios = [];
                for (const el of msgs) {
                    const textEl = el.querySelector('span[dir="ltr"], span[dir="auto"]');
                    if (textEl && textEl.textContent.trim()) usuarios.push(textEl.textContent.trim());
                }
                if (usuarios.length === 0) return '';
                return usuarios[usuarios.length - 1];
            }
        """)
        return raw.strip()

    async def _executar_frete(self, conv_id: int, cliente_id: int, telefone: str):
        cliente = cliente_por_telefone(telefone)
        if not cliente:
            await self.enviar_para_cliente(telefone, "Erro ao recuperar seus dados.")
            return
        conversa = get_conversa_ativa(telefone)
        produto_id = (conversa or {}).get("produto_interesse_id")
        if not produto_id:
            await self.enviar_para_cliente(telefone, "Produto nao identificado. Escolha um produto primeiro.")
            return
        produto = produto_por_id(produto_id)
        if not produto:
            await self.enviar_para_cliente(telefone, "Produto nao encontrado.")
            return

        ci = {
            "endereco": cliente.get("endereco", ""),
            "cidade": cliente.get("cidade", ""),
            "cep": cliente.get("cep", ""),
            "estado": cliente.get("estado", ""),
        }
        await self.enviar_para_cliente(telefone, "Consultando frete...")
        for t in TRANSPORTADORAS:
            cot_id = criar_cotacao(conv_id, t["nome"])
            await self.solicitar_frete_transportadora(t, produto, ci)
            resp = await self.aguardar_resposta_transportadora(t["nome"], 180)
            if resp:
                v = self.extrair_valor_frete(resp)
                pz = self.extrair_prazo(resp)
                atualizar_cotacao(cot_id, valor_frete=v, prazo=pz, status="recebida")
                await self.enviar_para_cliente(telefone,
                    f"Frete {t['nome']}: R$ {v:.2f} ({pz or 'a confirmar'})\n"
                    f"Total: R$ {produto['preco'] + v:.2f}\nDeseja confirmar?")
            else:
                atualizar_cotacao(cot_id, status="sem_resposta")
                await self.enviar_para_cliente(telefone,
                    f"Nao recebi retorno da {t['nome']} ainda. Assim que responder, aviso.")

    async def processar_mensagem(self, remetente: str, msg_texto: str, telefone: str = "", nome_sidebar: str = ""):
        try:
            if not telefone:
                telefone = re.sub(r'\D', '', remetente)
                if not telefone.startswith("55"):
                    telefone = "55" + telefone
                if len(telefone) < 12:
                    telefone = "55" + re.sub(r'\D', '', remetente)

            if len(telefone) < 12:
                print(f"  -> Telefone invalido p/ {safe(remetente)}: {telefone}", flush=True)
                return

            if telefone in self.processando:
                return
            self.processando[telefone] = True

            # Ignora mensagens de sistema do WhatsApp
            if msg_texto and ("Meta" in msg_texto or "servi" in msg_texto.lower() or "gerenciar esta conversa" in msg_texto.lower()):
                print(f"  -> Msg de sistema ignorada: {safe(msg_texto[:60])}", flush=True)
                self.processando.pop(telefone, None)
                return

            cliente_id = criar_cliente(telefone, nome=remetente)
            conversa = get_conversa_ativa(telefone)
            if not conversa:
                conv_id = criar_conversa(cliente_id)
            else:
                conv_id = conversa["conversa_id"]

            if msg_texto:
                salvar_mensagem(conv_id, "cliente", msg_texto)
            historico = get_historico_conversa(conv_id, limite=30)

            # So inicia apresentacao se ainda nao houver resposta do bot
            tem_resposta = any(m["origem"] == "agente" for m in historico)
            if not tem_resposta:
                ok = await self._iniciar_apresentacao_menu(telefone, conv_id, nome_sidebar)
                self.processando.pop(telefone, None)
                if ok:
                    print(f"  -> Apresentacao iniciada para {safe(remetente)}", flush=True)
                else:
                    print(f"  -> Falha ao enviar menu para {safe(remetente)}", flush=True)
                return

            # Msg sem texto detectavel: reinicia apresentacao
            if not msg_texto:
                print(f"  -> Msg sem texto, reiniciando menu para {safe(remetente)}", flush=True)
                ok = await self._iniciar_apresentacao_menu(telefone, conv_id, nome_sidebar)
                self.processando.pop(telefone, None)
                if ok:
                    print(f"  -> Apresentacao reiniciada para {safe(remetente)}", flush=True)
                else:
                    print(f"  -> Falha ao reiniciar menu para {safe(remetente)}", flush=True)
                return

            etapa = (conversa or {}).get("etapa", "")

            # --- FLUXO DE FRETE: coleta de dados ---
            if etapa == "frete_nome":
                nome = msg_texto.strip()
                # Fallback: se o chat tiver uma msg anterior do usuario (sidebar perdeu), usa ela
                msg_anterior = await self._ler_msg_anterior_usuario()
                if msg_anterior and msg_anterior != nome:
                    print(f"  [frete] sidebar perdeu '{safe(nome)}', usando msg anterior: '{safe(msg_anterior)}'", flush=True)
                    nome = msg_anterior
                atualizar_cliente(cliente_id, nome=nome)
                atualizar_etapa_conversa(conv_id, "frete_cpf")
                print(f"  [frete] nome salvo: {safe(nome)} -> etapa frete_cpf", flush=True)
                await self.enviar_para_cliente(telefone, "Obrigado! Agora informe seu CPF ou CNPJ:")
                salvar_mensagem(conv_id, "agente", "Obrigado! Agora informe seu CPF ou CNPJ:")
                return

            if etapa == "frete_cpf":
                cpf = msg_texto.strip()
                msg_anterior = await self._ler_msg_anterior_usuario()
                if msg_anterior and msg_anterior != cpf:
                    print(f"  [frete] sidebar perdeu '{safe(cpf)}', usando msg anterior: '{safe(msg_anterior)}'", flush=True)
                    cpf = msg_anterior
                atualizar_cliente(cliente_id, cpf=cpf)
                atualizar_etapa_conversa(conv_id, "frete_endereco")
                print(f"  [frete] cpf salvo: {safe(cpf)} -> etapa frete_endereco", flush=True)
                await self.enviar_para_cliente(telefone, "Perfeito! Agora informe seu endereco completo com CEP (Rua, numero, bairro, cidade, estado, CEP):")
                salvar_mensagem(conv_id, "agente", "Perfeito! Informe o endereco completo com CEP:")
                return

            if etapa.startswith("frete_endereco"):
                endereco = msg_texto.strip()
                msg_anterior = await self._ler_msg_anterior_usuario()
                if msg_anterior and msg_anterior != endereco:
                    print(f"  [frete] sidebar perdeu '{safe(endereco)}', usando msg anterior: '{safe(msg_anterior)}'", flush=True)
                    endereco = msg_anterior
                cliente_info = self._parse_endereco(endereco)
                atualizar_cliente(cliente_id, **{k: v for k, v in cliente_info.items() if v})
                atualizar_etapa_conversa(conv_id, "menu_principal")
                cliente_completo = cliente_por_telefone(telefone)
                nome_cliente = cliente_completo.get("nome", "") if cliente_completo else ""
                print(f"  [frete] endereco salvo -> enviando confirmacao + xlsx", flush=True)
                await self.enviar_para_cliente(telefone,
                    f"Obrigado, {nome_cliente}! Sua solicitacao de frete foi recebida com sucesso.\n"
                    f"Em breve entraremos em contato com o orcamento.\n"
                    f"Por favor, aguarde nosso retorno.")
                self._salvar_solicitacao_frete(
                    telefone,
                    nome_cliente,
                    cliente_completo.get("cpf", "") if cliente_completo else "",
                    endereco,
                    cliente_info.get("cidade", ""),
                    cliente_info.get("estado", ""),
                    cliente_info.get("cep", ""),
                )
                return

            # --- APRESENTACAO PROGRESSIVA DO MENU ---
            if etapa == "apresentacao_menu":
                estado = self.apresentacao_menu.get(telefone)
                if not estado:
                    self.apresentacao_menu.pop(telefone, None)
                    atualizar_etapa_conversa(conv_id, "menu_principal")
                    self.processando.pop(telefone, None)
                    return
                if msg_texto.strip().isdigit():
                    n = int(msg_texto.strip())
                    if n in estado["apresentados"]:
                        self.apresentacao_menu.pop(telefone, None)
                        produto = produto_por_id(n)
                        if produto:
                            atualizar_produto_interesse(conv_id, produto["id"])
                            self.processando.pop(telefone, None)
                            await self._iniciar_apresentacao_submenu(telefone, conv_id, produto)
                            return
                    else:
                        await self.enviar_para_cliente(telefone, f"Opção {n} ainda não foi apresentada. Aguarde as próximas opções.")
                        return
                # nao-digit: cai na conversa livre (Gemini/fallback)

            # --- APRESENTACAO PROGRESSIVA DO SUBMENU ---
            if etapa == "apresentacao_submenu":
                estado = self.apresentacao_submenu.get(telefone)
                if not estado:
                    self.apresentacao_submenu.pop(telefone, None)
                    atualizar_etapa_conversa(conv_id, "menu_principal")
                    self.processando.pop(telefone, None)
                    return
                if msg_texto.strip().isdigit():
                    n = int(msg_texto.strip())
                    if n in estado["apresentados"]:
                        self.apresentacao_submenu.pop(telefone, None)
                        self.processando.pop(telefone, None)
                        await self._executar_opcao_submenu(telefone, conv_id, estado["produto_id"], n, nome_sidebar)
                        return
                    else:
                        await self.enviar_para_cliente(telefone, f"Opção {n} ainda não foi apresentada. Aguarde...")
                        return
                # nao-digit: cai na conversa livre (Gemini/fallback)

            # --- SUBMENU: perguntar se deseja continuar ---
            if etapa == "submenu_continuar":
                opt = self._n(msg_texto.strip().lower())
                # Ignore long text (bot's own messages), only short user responses
                if len(opt.split()) > 3:
                    return
                ctx = self.continuar_submenu.pop(telefone, None)
                if not ctx:
                    atualizar_etapa_conversa(conv_id, "menu_principal")
                    return
                if opt in ("1", "sim"):
                    produto = produto_por_id(ctx["produto_id"])
                    if produto:
                        self.processando.pop(telefone, None)
                        await self._iniciar_apresentacao_submenu(telefone, conv_id, produto)
                    return
                if opt in ("2", "nao", "não", "voltar"):
                    self.apresentacao_submenu.pop(telefone, None)
                    await self.enviar_para_cliente(telefone, "Voltando ao Menu Principal...", ctx.get("nome_sidebar", ""))
                    ok = await self._iniciar_apresentacao_menu(telefone, conv_id, ctx.get("nome_sidebar", ""))
                    if ok:
                        print(f"  -> Menu reiniciado para {safe(telefone)}", flush=True)
                    return
                # Unknown input: cai na conversa livre (Gemini/fallback)
                atualizar_etapa_conversa(conv_id, "menu_principal")

            # --- SUBMENU: se estiver visualizando um produto ---
            if etapa.startswith("submenu_"):
                produto_id = int(etapa.split("_")[1])
                produto = produto_por_id(produto_id)
                if produto:
                    opt = msg_texto.strip().lower()
                    opt_map = {"1": "folder", "folder": "folder",
                               "2": "valor", "valor": "valor", "preco": "valor", "preço": "valor",
                               "3": "foto", "foto": "foto", "fotografia": "foto",
                               "4": "video", "video": "video", "vídeo": "video",
                               "5": "frete", "frete": "frete", "cotacao": "frete", "cotaçao": "frete"}
                    acao = opt_map.get(opt)

                    if acao in ("folder", "valor", "foto", "video"):
                        if acao == "folder":
                            await self._enviar_folder(conv_id, telefone, produto)
                        elif acao == "valor":
                            resp = valor_produto(produto)
                            await self.enviar_para_cliente(telefone, resp)
                            salvar_mensagem(conv_id, "agente", resp)
                        elif acao == "foto":
                            await self._enviar_foto(conv_id, telefone, produto)
                        elif acao == "video":
                            await self._enviar_video(conv_id, telefone, produto)
                        self.processando.pop(telefone, None)
                        self.continuar_submenu[telefone] = {"conv_id": conv_id, "produto_id": produto_id, "nome_sidebar": nome_sidebar}
                        atualizar_etapa_conversa(conv_id, "submenu_continuar")
                        await self.enviar_para_cliente(telefone,
                            "Deseja mais alguma opcao?\n[1] SIM - Continuar neste produto\n[2] NAO - Voltar ao Menu Principal",
                            nome_sidebar)
                        return

                    if acao == "frete":
                        atualizar_etapa_conversa(conv_id, "frete_nome")
                        atualizar_produto_interesse(conv_id, produto["id"])
                        await self.enviar_para_cliente(telefone,
                            f"Para solicitar o frete da {produto['nome']}, preciso de alguns dados.\n\n"
                            f"Primeiro, informe seu NOME completo:")
                        salvar_mensagem(conv_id, "agente", "Solicitando dados para frete - informe o nome:")
                        return

            # --- SELECAO DE PRODUTO: numero 1-8 -> submenu progressivo ---
            if msg_texto.strip().isdigit():
                produto = produto_por_id(int(msg_texto.strip()))
                if produto:
                    atualizar_produto_interesse(conv_id, produto["id"])
                    self.processando.pop(telefone, None)
                    await self._iniciar_apresentacao_submenu(telefone, conv_id, produto)
                    return

            # --- CONVERSA LIVRE: usa Gemini ou fallback ---
            try:
                resposta = await asyncio.to_thread(gerar_resposta, historico)
            except Exception as e:
                print(f"[GEMINI] {safe(e)}")
                agora_fb = time.time()
                ult_fb = self.ultimo_fallback.get(telefone, 0)
                if agora_fb - ult_fb > 3600:
                    resposta = resposta_fallback(historico)
                    self.ultimo_fallback[telefone] = agora_fb
                else:
                    resposta = "Desculpe, estou temporariamente offline. Tente novamente mais tarde."

            comando = extrair_comando(resposta)
            resposta_limpa = limpar_resposta(resposta)

            if resposta_limpa:
                await self.enviar_para_cliente(telefone, resposta_limpa, nome_sidebar)
                salvar_mensagem(conv_id, "agente", resposta_limpa)
            if comando:
                await self.executar_comando(comando, conv_id, cliente_id, telefone, remetente)

        except Exception as e:
            print(f"[ERRO processar] {safe(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.processando.pop(telefone, None)

    async def executar_comando(self, comando: dict, conv_id, cliente_id, telefone, remetente):
        acao = comando["acao"]
        if acao == "enviar_midia":
            produto = next((p for p in PRODUTOS if p["id"] == comando["produto_id"]), None)
            if produto:
                if comando["tipo"] == "foto":
                    await self._enviar_foto(conv_id, telefone, produto)
                elif comando["tipo"] == "video":
                    await self._enviar_video(conv_id, telefone, produto)
                elif comando["tipo"] == "folder":
                    await self._enviar_folder(conv_id, telefone, produto)
                atualizar_produto_interesse(conv_id, produto["id"])

        elif acao == "solicitar_frete":
            await self._executar_frete(conv_id, cliente_id, telefone)

        elif acao == "venda_confirmada":
            produto = next((p for p in PRODUTOS if p["id"] == comando["produto_id"]), None)
            if not produto:
                return
            venda_id = criar_venda(conv_id, cliente_id, produto["id"], produto["preco"])
            atualizar_etapa_conversa(conv_id, "fechada")
            await self.enviar_para_cliente(telefone,
                f"Venda confirmada!\nProduto: {produto['nome']}\n"
                f"Total: R$ {comando['valor_total']:.2f}\nObrigado!")
            await self.enviar_para_cliente(SEU_NUMERO,
                f"VENDA!\n{comando['cliente_nome']} - Tel: {telefone}\n"
                f"{produto['nome']} - R$ {comando['valor_total']:.2f}\nID: {venda_id}")
            print(f"VENDA REGISTRADA: {safe(comando['cliente_nome'])} - {safe(produto['nome'])}")

    def extrair_valor_frete(self, texto: str) -> float:
        for p in [r"(?:R\$)?\s*(\d+[.,]\d{2,})", r"(?:valor|frete)\s*:?\s*(?:R\$)?\s*(\d+[.,]\d+)"]:
            m = re.search(p, texto, re.IGNORECASE)
            if m:
                return float(m.group(1).replace(".", "").replace(",", "."))
        return 50.0

    def extrair_prazo(self, texto: str) -> str | None:
        m = re.search(r"(\d+\s*dias?)", texto, re.IGNORECASE)
        return m.group(0) if m else None

    async def parar(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()


async def main():
    bot = WhatsAppBot()
    try:
        ok = await bot.iniciar()
        if ok:
            await bot.escutar_mensagens()
    except KeyboardInterrupt:
        print("\nEncerrando...")
    finally:
        await bot.parar()


if __name__ == "__main__":
    asyncio.run(main())
