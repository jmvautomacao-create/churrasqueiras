import asyncio
import json
import time
import re
from pathlib import Path
from playwright.async_api import async_playwright

from config import PRODUTOS, SEU_NUMERO, NUMERO_TESTE, TRANSPORTADORAS, BASE_DIR
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
    def __init__(self):
        self.page = None
        self.context = None
        self.playwright = None
        self.logado = False
        self.processando: dict[str, bool] = {}
        self.ultimo_processamento: dict[str, float] = {}
        self.ultimo_texto_chat: dict[str, str] = {}
        self.ultimo_visto_texto: dict[str, float] = {}
        self.mapa_contatos = {}
        self.ultimo_mapa = 0
        self.apresentacao_menu: dict[str, dict] = {}
        self.apresentacao_submenu: dict[str, dict] = {}
        self.continuar_submenu: dict[str, dict] = {}

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
        # Limpa dedup p/ este telefone p/ permitir re-selecao
        chaves = [k for k in self.ultimo_visto_texto if k.startswith(f"{telefone}|")]
        for k in chaves:
            self.ultimo_visto_texto.pop(k, None)
        primeiro = f"[1] {PRODUTOS[0]['nome']}"
        ok = await self.enviar_para_cliente(telefone,
            "Ola! Bem-vindo a JMV Churrasqueiras!\n"
            "Escolha um modelo digitando o NUMERO correspondente:\n\n"
            f"{primeiro}", nome_sidebar)
        if not ok:
            return False
        salvar_mensagem(conv_id, "agente", primeiro)
        self.apresentacao_menu[telefone] = {
            "conv_id": conv_id,
            "proximo_idx": 2,
            "apresentados": [1],
            "ultimo_envio": time.time(),
            "todos_enviados": False,
        }
        atualizar_etapa_conversa(conv_id, "apresentacao_menu")
        return True

    async def _avancar_apresentacao_menu(self, telefone: str, conv_id: int, estado: dict):
        BATCH = 4
        for _ in range(BATCH):
            if estado["proximo_idx"] > len(PRODUTOS):
                if not estado.get("todos_enviados"):
                    estado["todos_enviados"] = True
                    await self.enviar_para_cliente(telefone, "Digite o numero do produto que deseja!")
                return
            p = PRODUTOS[estado["proximo_idx"] - 1]
            item = f"[{estado['proximo_idx']}] {p['nome']}"
            ok = await self.enviar_para_cliente(telefone, item)
            if not ok:
                return
            salvar_mensagem(conv_id, "agente", item)
            estado["apresentados"].append(estado["proximo_idx"])
            estado["proximo_idx"] += 1
            estado["ultimo_envio"] = time.time()

    async def _iniciar_apresentacao_submenu(self, telefone: str, conv_id: int, produto: dict):
        self.apresentacao_submenu.pop(telefone, None)
        # Limpa dedup p/ este telefone p/ permitir re-selecao
        chaves = [k for k in self.ultimo_visto_texto if k.startswith(f"{telefone}|")]
        for k in chaves:
            self.ultimo_visto_texto.pop(k, None)
        primeiro = f"Voce escolheu: {produto['nome']}\n\nSelecione uma das opcoes abaixo:\n\n[1] Folder - Ver folder do produto"
        await self.enviar_para_cliente(telefone, primeiro)
        salvar_mensagem(conv_id, "agente", primeiro)
        self.apresentacao_submenu[telefone] = {
            "conv_id": conv_id,
            "produto_id": produto["id"],
            "proximo_idx": 2,
            "apresentados": [1],
            "ultimo_envio": time.time(),
            "todos_enviados": False,
        }
        atualizar_etapa_conversa(conv_id, "apresentacao_submenu")

    async def _avancar_apresentacao_submenu(self, telefone: str, conv_id: int, estado: dict):
        SUB_ITENS = [
            "[2] Valor - Consultar preco",
            "[3] Foto - Enviar foto",
            "[4] Video - Enviar video",
            "[5] Frete - Solicitar cotacao de frete",
            "[6] Voltar ao Menu Principal",
        ]
        BATCH = 3
        for _ in range(BATCH):
            idx = estado["proximo_idx"]
            if idx > 6:
                if not estado.get("todos_enviados"):
                    estado["todos_enviados"] = True
                    await self.enviar_para_cliente(telefone, "Digite o numero da opcao desejada!")
                return
            item = SUB_ITENS[idx - 2]
            ok = await self.enviar_para_cliente(telefone, item)
            if not ok:
                return
            salvar_mensagem(conv_id, "agente", item)
            estado["apresentados"].append(idx)
            estado["proximo_idx"] = idx + 1
            estado["ultimo_envio"] = time.time()

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
        self.continuar_submenu[telefone] = {"conv_id": conv_id, "produto_id": produto_id, "nome_sidebar": nome_sidebar}
        atualizar_etapa_conversa(conv_id, "submenu_continuar")
        await self.enviar_para_cliente(telefone,
            "Deseja mais alguma opcao?\n[1] SIM - Continuar neste produto\n[2] NAO - Voltar ao Menu Principal",
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
                                const spans = row.querySelectorAll('span[dir="auto"]');
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

                    const spans = chat.querySelectorAll('span[dir="auto"]');
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
                    nome = chat.get("nome", "")
                    texto = chat.get("texto", "")
                    nao_lida = chat.get("nao_lida", False)
                    telefone = chat.get("telefone", "")

                    if not nome or nome == "DEBUG" or nome.startswith("Filt"):
                        continue

                    # Dedup intra-ciclo: chats duplicados (ex: role="row" aninhado)
                    if nome in vistos_ciclo:
                        continue
                    vistos_ciclo.add(nome)

                    if not telefone or len(telefone) < 12:
                        continue

                    # Modo teste: atende apenas NUMERO_TESTE
                    if telefone != NUMERO_TESTE:
                        continue

                    if c % 30 == 0 or nao_lida:
                        marca = f" [tel:{telefone}]" if telefone else ""
                        print(f"  [{c}] {safe(nome)}{marca}: {'[NAO LIDA] ' if nao_lida else ''}{safe(texto[:60])}")

                    # Dedup: mesmo conteudo/sem texto nao processar repetido
                    agora = time.time()
                    ultimo = self.ultimo_processamento.get(nome, 0)
                    if texto:
                        chave = f"{telefone}|{texto}"
                        ult_visto = self.ultimo_visto_texto.get(chave, 0)
                        if agora - ult_visto < 60:
                            continue
                    else:
                        if agora - ultimo < 120:
                            continue

                    # Fallback: detectar por mudanca de texto (msgs sem badge)
                    ultimo_texto = self.ultimo_texto_chat.get(nome, "")
                    if texto and texto != ultimo_texto:
                        self.ultimo_texto_chat[nome] = texto
                        nao_lida = True

                    if nao_lida:
                        self.ultimo_processamento[nome] = agora
                        if texto:
                            self.ultimo_visto_texto[f"{telefone}|{texto}"] = agora
                        print(f"\n>>> NOVA MENSAGEM: {safe(nome)}: {safe(texto)}", flush=True)
                        await self.processar_mensagem(nome, texto, telefone, nome)
                        break

                for tel, est in list(self.apresentacao_menu.items()):
                    if est.get("todos_enviados") or est.get("enviando"):
                        continue
                    est["enviando"] = True
                    try:
                        await self._avancar_apresentacao_menu(tel, est["conv_id"], est)
                    except Exception as e:
                        print(f"  [AVANCO menu] {safe(e)}")
                        self.apresentacao_menu.pop(tel, None)
                    finally:
                        est.pop("enviando", None)
                for tel, est in list(self.apresentacao_submenu.items()):
                    if est.get("todos_enviados") or est.get("enviando"):
                        continue
                    est["enviando"] = True
                    try:
                        await self._avancar_apresentacao_submenu(tel, est["conv_id"], est)
                    except Exception as e:
                        print(f"  [AVANCO submenu] {safe(e)}")
                        self.apresentacao_submenu.pop(tel, None)
                    finally:
                        est.pop("enviando", None)

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
                for _ in range(3):
                    # Usa Playwright para clicar no elemento [title] que contem o nome
                    alvo = json.dumps(nome)
                    handle = await self.avaliar(f"""
                        () => {{
                            const rows = document.querySelectorAll('#side [role="row"]');
                            const alvo = {alvo};
                            for (const row of rows) {{
                                const el = row.querySelector('[title]');
                                if (el && el.getAttribute('title') === alvo) {{
                                    return el.getAttribute('title');
                                }}
                            }}
                            return null;
                        }}
                    """)
                    if handle:
                        el = self.page.locator(f'#side [title="{nome}"]').first
                        if await el.count() > 0:
                            await el.click()
                            await asyncio.sleep(0.4)
                            return True
                    await asyncio.sleep(0.2)
            el = self.page.locator('#side [role="row"]').first
            if await el.count() > 0:
                await el.click()
                await asyncio.sleep(0.4)
                return True
            return False
        except Exception as e:
            print(f"  [sidebar erro] {safe(str(e)[:80])}", flush=True)
            return False
    async def enviar_texto(self, numero: str, texto: str, nome_sidebar: str = "") -> bool:
        try:
            tem_input = await self.page.query_selector(self.SELETOR_INPUT)
            if not tem_input:
                nomes = [nome_sidebar] if nome_sidebar else []
                nomes += [n for n, t in self.mapa_contatos.items() if t == numero]
                for nome in nomes:
                    if not nome:
                        continue
                    if await self._abrir_chat_sidebar(nome, numero):
                        try:
                            tem_input = await self.page.wait_for_selector(self.SELETOR_INPUT, timeout=5000)
                        except:
                            tem_input = None
                        if tem_input:
                            break

            if not tem_input:
                print(f"  -> Input nao disponivel para {numero}", flush=True)
                return False

            ok_dig = await self._digitar(texto)
            if not ok_dig:
                print(f"  -> Input nao disponivel para {numero}", flush=True)
                return False
            if await self._clicar_enviar():
                print(f"  -> Enviado para {numero}", flush=True)
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
            tem_input = await self.page.query_selector(self.SELETOR_INPUT)
            if not tem_input:
                nome = next((n for n, t in self.mapa_contatos.items() if t == numero), None)
                if nome:
                    for _ in range(3):
                        if await self._abrir_chat_sidebar(nome):
                            await asyncio.sleep(0.5)
                            tem_input = await self.page.query_selector(self.SELETOR_INPUT)
                            if tem_input:
                                break

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
        uf_match = re.search(r"\b([A-Za-z]{2})\b", endereco.split(",")[-1] if "," in endereco else endereco)
        if uf_match:
            info["estado"] = uf_match.group(1).upper()
        partes = endereco.replace(",", " ").split()
        for i, p in enumerate(partes):
            if p.upper() in ("SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "MT", "MS",
                             "ES", "CE", "RN", "PE", "PB", "AL", "SE", "PI", "MA", "PA", "AM",
                             "AC", "RO", "RR", "AP", "TO"):
                info["estado"] = p.upper()
                if i > 0:
                    info["cidade"] = partes[i - 1].strip()
                break
        return info

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
        if remetente in self.processando:
            return
        self.processando[remetente] = True

        try:
            if not telefone:
                telefone = re.sub(r'\D', '', remetente)
                if not telefone.startswith("55"):
                    telefone = "55" + telefone
                if len(telefone) < 12:
                    telefone = "55" + re.sub(r'\D', '', remetente)

            if len(telefone) < 12:
                print(f"  -> Telefone invalido p/ {safe(remetente)}: {telefone}", flush=True)
                self.processando.pop(remetente, None)
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
                self.processando.pop(remetente, None)
                if ok:
                    print(f"  -> Apresentacao iniciada para {safe(remetente)}", flush=True)
                else:
                    print(f"  -> Falha ao enviar menu para {safe(remetente)}", flush=True)
                return

            # Msg sem texto detectavel: reinicia apresentacao
            if not msg_texto:
                print(f"  -> Msg sem texto, reiniciando menu para {safe(remetente)}", flush=True)
                ok = await self._iniciar_apresentacao_menu(telefone, conv_id, nome_sidebar)
                self.processando.pop(remetente, None)
                if ok:
                    print(f"  -> Apresentacao reiniciada para {safe(remetente)}", flush=True)
                else:
                    print(f"  -> Falha ao reiniciar menu para {safe(remetente)}", flush=True)
                return

            etapa = (conversa or {}).get("etapa", "")

            # --- FLUXO DE FRETE: coleta de dados ---
            if etapa == "frete_nome":
                atualizar_cliente(cliente_id, nome=msg_texto.strip())
                atualizar_etapa_conversa(conv_id, "frete_cpf")
                await self.enviar_para_cliente(telefone, "Obrigado! Agora informe seu CPF ou CNPJ:")
                salvar_mensagem(conv_id, "agente", "Obrigado! Agora informe seu CPF ou CNPJ:")
                return

            if etapa == "frete_cpf":
                atualizar_cliente(cliente_id, cpf=msg_texto.strip())
                atualizar_etapa_conversa(conv_id, "frete_endereco")
                await self.enviar_para_cliente(telefone, "Perfeito! Agora informe seu endereco completo com CEP (Rua, numero, bairro, cidade, estado, CEP):")
                salvar_mensagem(conv_id, "agente", "Perfeito! Informe o endereco completo com CEP:")
                return

            if etapa.startswith("frete_endereco"):
                endereco = msg_texto.strip()
                cliente_info = self._parse_endereco(endereco)
                atualizar_cliente(cliente_id, endereco=endereco, **{k: v for k, v in cliente_info.items() if v})
                atualizar_etapa_conversa(conv_id, "menu_principal")
                await self.enviar_para_cliente(telefone, "Obrigado! Vou consultar o frete com as transportadoras e ja volto.")
                await self._executar_frete(conv_id, cliente_id, telefone)
                return

            # --- APRESENTACAO PROGRESSIVA DO MENU ---
            if etapa == "apresentacao_menu":
                estado = self.apresentacao_menu.get(telefone)
                if not estado:
                    self.apresentacao_menu.pop(telefone, None)
                    atualizar_etapa_conversa(conv_id, "menu_principal")
                    self.processando.pop(remetente, None)
                    return
                else:
                    if msg_texto.strip().isdigit():
                        n = int(msg_texto.strip())
                        if n in estado["apresentados"]:
                            self.apresentacao_menu.pop(telefone, None)
                            produto = produto_por_id(n)
                            if produto:
                                atualizar_produto_interesse(conv_id, produto["id"])
                                self.processando.pop(remetente, None)
                                await self._iniciar_apresentacao_submenu(telefone, conv_id, produto)
                                return
                        else:
                            await self.enviar_para_cliente(telefone, f"Opção {n} ainda não foi apresentada. Aguarde as próximas opções.")
                            return
                    await self._avancar_apresentacao_menu(telefone, conv_id, estado)
                    return

            # --- APRESENTACAO PROGRESSIVA DO SUBMENU ---
            if etapa == "apresentacao_submenu":
                estado = self.apresentacao_submenu.get(telefone)
                if not estado:
                    self.apresentacao_submenu.pop(telefone, None)
                    atualizar_etapa_conversa(conv_id, "menu_principal")
                    self.processando.pop(remetente, None)
                    return
                else:
                    if msg_texto.strip().isdigit():
                        n = int(msg_texto.strip())
                        if n in estado["apresentados"]:
                            self.apresentacao_submenu.pop(telefone, None)
                            self.processando.pop(remetente, None)
                            await self._executar_opcao_submenu(telefone, conv_id, estado["produto_id"], n, nome_sidebar)
                            return
                        else:
                            await self.enviar_para_cliente(telefone, f"Opção {n} ainda não foi apresentada. Aguarde...")
                            return
                    await self._avancar_apresentacao_submenu(telefone, conv_id, estado)
                    return

            # --- SUBMENU: perguntar se deseja continuar ---
            if etapa == "submenu_continuar":
                opt = msg_texto.strip().lower()
                ctx = self.continuar_submenu.pop(telefone, None)
                if not ctx:
                    atualizar_etapa_conversa(conv_id, "menu_principal")
                    return
                if opt in ("1", "sim"):
                    produto = produto_por_id(ctx["produto_id"])
                    if produto:
                        self.processando.pop(remetente, None)
                        await self._iniciar_apresentacao_submenu(telefone, conv_id, produto)
                    return
                self.apresentacao_submenu.pop(telefone, None)
                await self.enviar_para_cliente(telefone, "Voltando ao Menu Principal...", ctx.get("nome_sidebar", ""))
                ok = await self._iniciar_apresentacao_menu(telefone, conv_id, ctx.get("nome_sidebar", ""))
                if ok:
                    print(f"  -> Menu reiniciado para {safe(telefone)}", flush=True)
                return

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
                        self.processando.pop(remetente, None)
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
                    self.processando.pop(remetente, None)
                    await self._iniciar_apresentacao_submenu(telefone, conv_id, produto)
                    return

            # --- CONVERSA LIVRE: usa Gemini ou fallback ---
            try:
                resposta = gerar_resposta(historico)
            except Exception as e:
                print(f"[GEMINI] {safe(e)}")
                resposta = resposta_fallback(historico)

            comando = extrair_comando(resposta)
            resposta_limpa = limpar_resposta(resposta)

            if resposta_limpa:
                await self.enviar_para_cliente(telefone, resposta_limpa)
                salvar_mensagem(conv_id, "agente", resposta_limpa)
            if comando:
                await self.executar_comando(comando, conv_id, cliente_id, telefone, remetente)

        except Exception as e:
            print(f"[ERRO processar] {safe(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.processando.pop(remetente, None)

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
