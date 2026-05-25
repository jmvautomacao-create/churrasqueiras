import asyncio
import json
import time
import re
from pathlib import Path
from playwright.async_api import async_playwright

from config import PRODUTOS, SEU_NUMERO, TRANSPORTADORAS, BASE_DIR
from database import (
    cliente_por_telefone, criar_cliente, criar_conversa, salvar_mensagem,
    atualizar_etapa_conversa, atualizar_produto_interesse, criar_cotacao,
    atualizar_cotacao, criar_venda, get_historico_conversa, get_conversa_ativa,
    atualizar_cliente,
)
from gemini_agent import gerar_resposta, extrair_comando, limpar_resposta
from produtos import menu_interativo, produto_por_id, detalhar


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
        self.vistos = set()
        self.processando = {}

    async def iniciar(self):
        self.playwright = await async_playwright().start()
        user_data_dir = str(BASE_DIR / "data" / "whatsapp_session")

        import shutil
        sessao_dir = Path(user_data_dir)
        if sessao_dir.exists():
            try:
                shutil.rmtree(sessao_dir)
                safe("Sessao anterior removida.")
            except:
                safe("Sessao anterior mantida.")

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=False,
        )
        self.page = await self.context.new_page()
        await self.page.goto("https://web.whatsapp.com")
        print("Aguardando login... Escaneie o QR Code com o celular.")

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

    async def avaliar(self, codigo: str):
        try:
            return await self.page.evaluate(codigo)
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
            if self.page and not self.page.is_closed():
                try:
                    await self.page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=30000)
                except:
                    pass
        except:
            pass
        await asyncio.sleep(5)
        print("  -> Pagina recuperada (ou nova aba criada).")

    async def detectar_chats(self):
        codigo = """
            () => {
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
                                const msg = row.querySelector('[data-testid="last-msg"]') ||
                                            row.querySelector('span[dir="auto"]:last-child');
                                const texto = msg ? msg.textContent.trim() : '';
                                const badge = row.querySelector('[data-testid="icon-unread-count"]') ||
                                             row.querySelector('[aria-label*="nao lida"]') ||
                                             row.querySelector('[aria-label*="unread"]');
                                achados.push({nome, texto, nao_lida: !!badge});
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

                    const msg = chat.querySelector('[data-testid="last-msg"]') ||
                                chat.querySelector('span[dir="auto"]:last-child');
                    const texto = msg ? msg.textContent.trim() : '';

                    const badge = chat.querySelector('[data-testid="icon-unread-count"]') ||
                                 chat.querySelector('[aria-label*="nao lida"]') ||
                                 chat.querySelector('[aria-label*="unread"]');

                    achados.push({nome, texto, nao_lida: !!badge});
                });
                return JSON.stringify(achados);
            }
        """
        return await self.avaliar(codigo)

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

                if c <= 3 or any(chat.get("nao_lida") for chat in chats):
                    for chat in chats:
                        nome = chat.get("nome", "")
                        texto = chat.get("texto", "")
                        nao_lida = chat.get("nao_lida", False)
                        if nome and nome != "DEBUG":
                            print(f"  [{c}] {safe(nome)}: {'[NAO LIDA] ' if nao_lida else ''}{safe(texto[:50])}")

                for chat in chats:
                    nome = chat.get("nome", "")
                    texto = chat.get("texto", "")
                    nao_lida = chat.get("nao_lida", False)

                    if not nome or not texto or nome == "DEBUG" or nome.startswith("Filt"):
                        continue

                    chave = f"{nome}|{texto}"
                    if chave in self.vistos:
                        continue
                    self.vistos.add(chave)

                    if nao_lida:
                        print(f"\n>>> NOVA MENSAGEM de {safe(nome)}: {safe(texto)}")
                        await self.processar_mensagem(nome, texto)

                await asyncio.sleep(3)

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

    async def _aguardar_input(self, timeout=20):
        for _ in range(timeout):
            for sel in ['[contenteditable="true"]', 'div[role="textbox"]', 'div[aria-placeholder*="mensagem"]', 'div[aria-placeholder*="message"]']:
                el = await self.page.query_selector(sel)
                if el:
                    return el
            await asyncio.sleep(1)
        return None

    async def _digitar(self, texto: str):
        caixa = await self._aguardar_input()
        if not caixa:
            print("[AVISO] Input nao encontrado para digitar")
            return False
        try:
            await caixa.fill("")
            await caixa.type(texto, delay=30)
            return True
        except Exception:
            try:
                await caixa.evaluate("el => { el.focus(); el.textContent = ''; }")
                await caixa.type(texto, delay=30)
                return True
            except Exception as e:
                print(f"[AVISO] Falha ao digitar: {safe(e)}")
                return False

    async def _clicar_enviar(self, max_tentativas=30, usar_enter=False):
        for i in range(max_tentativas):
            if usar_enter:
                try:
                    await self.page.keyboard.press("Enter")
                    await asyncio.sleep(0.3)
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
            await asyncio.sleep(0.5)
        return False

    async def enviar_texto(self, numero: str, texto: str):
        try:
            url = f"https://web.whatsapp.com/send?phone={numero}"
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            if await self._digitar(texto):
                print("  Texto digitado")
            await asyncio.sleep(2)

            if await self._clicar_enviar():
                print(f"  -> Enviado para {numero}")
                await asyncio.sleep(2)
                return

            print(f"  -> Falha ao enviar para {numero}")
        except Exception as e:
            print(f"[ERRO ENVIO] {safe(e)}")

    async def enviar_midia(self, numero: str, caminho: str, legenda: str = ""):
        try:
            url = f"https://web.whatsapp.com/send?phone={numero}"
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            clicou = await self._enviar_com_evaluate("""
                () => {
                    const botoes = document.querySelectorAll('button');
                    for (const btn of botoes) {
                        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                        if ((label.includes('anexar') || label.includes('attach')) && btn.offsetParent !== null) {
                            btn.click();
                            return true;
                        }
                    }
                    const divs = document.querySelectorAll('[data-testid="attach-file"]');
                    for (const d of divs) { if (d.offsetParent !== null) { d.click(); return true; } }
                    return false;
                }
            """)
            if not clicou:
                print("[AVISO] Nao encontrou botao anexar")
            await asyncio.sleep(2)

            input_file = self.page.locator('input[type="file"]').first
            await input_file.set_input_files(str(caminho))
            await asyncio.sleep(5)

            if legenda:
                cap = await self.page.query_selector('[data-testid="caption-input"]')
                if cap:
                    try:
                        await cap.fill("")
                        await cap.type(legenda, delay=30)
                    except:
                        await cap.evaluate("el => el.focus()")
                        await self.page.keyboard.type(legenda)
                await asyncio.sleep(1)

            if await self._clicar_enviar(30, usar_enter=True):
                print(f"  -> Midia enviada: {Path(caminho).name}")
                await asyncio.sleep(2)
                return
            print(f"  -> Falha ao enviar midia: {Path(caminho).name}")
        except Exception as e:
            print(f"[ERRO MIDIA] {safe(e)}")

    async def enviar_para_cliente(self, numero: str, texto: str):
        await self.enviar_texto(numero, texto)

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

    async def processar_mensagem(self, remetente: str, msg_texto: str):
        if remetente in self.processando:
            return
        self.processando[remetente] = True

        try:
            telefone = re.sub(r'\D', '', remetente)
            if not telefone.startswith("55"):
                telefone = "55" + telefone
            if len(telefone) < 12:
                telefone = "55" + re.sub(r'\D', '', remetente)

            cliente_id = criar_cliente(telefone, nome=remetente)
            conversa = get_conversa_ativa(telefone)
            if not conversa:
                conv_id = criar_conversa(cliente_id)
            else:
                conv_id = conversa["conversa_id"]

            salvar_mensagem(conv_id, "cliente", msg_texto)
            historico = get_historico_conversa(conv_id, limite=30)

            if len(historico) <= 1:
                resposta = menu_interativo()
                await self.enviar_para_cliente(telefone, resposta)
                salvar_mensagem(conv_id, "agente", resposta)
                print(f"  -> Menu enviado para {safe(remetente)}")
                return

            if msg_texto.strip().isdigit():
                produto = produto_por_id(int(msg_texto.strip()))
                if produto:
                    resp = (
                        f"Voce escolheu: {produto['nome']}\n\n"
                        f"{detalhar(produto['id'])}\n\n"
                        f"Quer que eu envie a foto?"
                    )
                    await self.enviar_para_cliente(telefone, resp)
                    salvar_mensagem(conv_id, "agente", resp)
                    atualizar_produto_interesse(conv_id, produto["id"])
                    cmd = extrair_comando(f"[ENVIAR_MIDIA:{produto['id']}:foto]")
                    if cmd:
                        await self.executar_comando(cmd, conv_id, cliente_id, telefone, remetente)
                    return

            resposta = gerar_resposta(historico)
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
                md = BASE_DIR / "media" / "churrasqueiras" / produto["midia_dir"]
                if comando["tipo"] == "foto":
                    folder = md / "folder.jpg"
                    if folder.exists():
                        await self.enviar_midia_para_cliente(telefone, folder, produto["nome"])
                        salvar_mensagem(conv_id, "agente", "[folder.jpg]", "foto")
                        await asyncio.sleep(1)
                    fotos = sorted([f for f in md.glob("*") if f.suffix.lower() in (".jpg", ".jpeg", ".png") and f.name != "folder.jpg"])
                    if fotos:
                        await self.enviar_midia_para_cliente(telefone, fotos[0], produto["nome"])
                        salvar_mensagem(conv_id, "agente", f"[{fotos[0].name}]", "foto")
                elif comando["tipo"] == "video":
                    videos = [f for f in md.glob("*") if f.suffix.lower() in (".mp4", ".mov")]
                    if videos:
                        await self.enviar_midia_para_cliente(telefone, videos[0], produto["nome"])
                        salvar_mensagem(conv_id, "agente", f"[{videos[0].name}]", "video")
                atualizar_produto_interesse(conv_id, produto["id"])

        elif acao == "solicitar_frete":
            produto = next((p for p in PRODUTOS if p["id"] == comando["produto_id"]), None)
            if not produto:
                return
            ci = {"cidade": comando["cidade"], "estado": comando["estado"], "cep": comando["cep"]}
            atualizar_cliente(cliente_id, **ci)
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
