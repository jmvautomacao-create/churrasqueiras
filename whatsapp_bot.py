import asyncio
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


class WhatsAppBot:
    def __init__(self):
        self.page = None
        self.context = None
        self.playwright = None
        self.logado = False
        self.ultimas_mensagens = set()
        self.processando = {}
        self.conversas_abertas = set()

    async def iniciar(self):
        self.playwright = await async_playwright().start()
        user_data_dir = str(BASE_DIR / "data" / "whatsapp_session")

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        self.page = await self.context.new_page()
        await self.page.goto("https://web.whatsapp.com")

        print("Aguardando login no WhatsApp Web...")
        try:
            await self.page.wait_for_selector('[data-testid="conversation-panel-main"]', timeout=180000)
            print("Login confirmado!")
            self.logado = True
            await asyncio.sleep(3)
        except:
            print("Tempo limite excedido para login no WhatsApp Web.")
            return False
        return True

    async def debug_estrutura(self):
        try:
            html = await self.page.evaluate("""
                () => {
                    const side = document.querySelector('#side') || document.querySelector('[data-testid="chat-list"]');
                    if (!side) return 'Sidebar nao encontrada';
                    const chats = side.querySelectorAll('[role="row"]');
                    const info = [];
                    chats.forEach((c, i) => {
                        if (i > 5) return;
                        const titleEl = c.querySelector('[title]');
                        const title = titleEl ? titleEl.getAttribute('title') : 'sem titulo';
                        const text = c.textContent.substring(0, 100);
                        info.push({index: i, title, text});
                    });
                    return JSON.stringify(info);
                }
            """)
            print(f"[DEBUG] Estrutura do WhatsApp: {html}")
        except Exception as e:
            print(f"[DEBUG] Erro ao inspecionar: {e}")

    async def obter_chats(self):
        dados = await self.page.evaluate("""
            () => {
                const side = document.querySelector('#side') || document.querySelector('[data-testid="chat-list"]');
                if (!side) return [];

                const chats = side.querySelectorAll('[role="row"]');
                const resultados = [];

                chats.forEach(chat => {
                    try {
                        const titleEl = chat.querySelector('[title]');
                        const nome = titleEl ? titleEl.getAttribute('title') : '';

                        if (!nome) return;

                        const msgPreview = chat.querySelector('[data-testid="last-msg"]') ||
                                            chat.querySelector('span[dir="auto"]:last-child');
                        const texto = msgPreview ? msgPreview.textContent.trim() : '';

                        const unreadBadge = chat.querySelector('[data-testid="icon-unread-count"]') ||
                                            chat.querySelector('[aria-label*="não lida"]') ||
                                            chat.querySelector('[aria-label*="unread"]');

                        resultados.push({
                            nome: nome,
                            texto: texto,
                            nao_lida: !!unreadBadge
                        });
                    } catch(e) {}
                });

                return resultados;
            }
        """)
        return dados

    async def obter_novas_mensagens(self):
        chats = await self.obter_chats()
        novas = []

        for chat in chats:
            if not chat["nao_lida"]:
                continue

            nome = chat["nome"]
            texto = chat["texto"]

            if not texto:
                continue

            chave = f"{nome}:{texto}"
            if chave in self.ultimas_mensagens:
                continue

            self.ultimas_mensagens.add(chave)
            novas.append({"nome": nome, "mensagem": texto})
            print(f"[DEBUG] Nova mensagem detectada de {nome}: {texto[:50]}...")

        return novas

    async def enviar_texto(self, numero: str, texto: str):
        url = f"https://web.whatsapp.com/send?phone={numero}"
        await self.page.goto(url)
        try:
            await self.page.wait_for_selector('[data-testid="conversation-compose-box-input"]', timeout=15000)
        except:
            await asyncio.sleep(5)

        await asyncio.sleep(2)
        msg_box = self.page.locator('[data-testid="conversation-compose-box-input"]')
        await msg_box.fill(texto)
        await asyncio.sleep(1)

        send_btn = self.page.locator('[data-testid="compose-btn-send"]')
        if await send_btn.count() == 0:
            send_btn = self.page.locator('button[aria-label="Enviar"]')
        if await send_btn.count() == 0:
            send_btn = self.page.locator('button span[data-icon="send"]')

        await send_btn.click()
        await asyncio.sleep(2)

    async def enviar_midia(self, numero: str, caminho_arquivo: str, legenda: str = ""):
        url = f"https://web.whatsapp.com/send?phone={numero}"
        await self.page.goto(url)
        try:
            await self.page.wait_for_selector('[data-testid="conversation-compose-box-input"]', timeout=15000)
        except:
            await asyncio.sleep(5)

        await asyncio.sleep(2)
        attach_btn = self.page.locator('[data-testid="attach-file"]')
        if await attach_btn.count() == 0:
            attach_btn = self.page.locator('button[aria-label="Anexar"]')
        if await attach_btn.count() == 0:
            attach_btn = self.page.locator('div[role="button"][aria-label*="anex"]')

        await attach_btn.click()
        await asyncio.sleep(2)

        file_input = self.page.locator('input[type="file"]')
        await file_input.set_input_files(str(caminho_arquivo))
        await asyncio.sleep(3)

        if legenda:
            caption_box = self.page.locator('[data-testid="caption-input"]')
            if await caption_box.count() > 0:
                await caption_box.fill(legenda)

        send_btn = self.page.locator('[data-testid="compose-btn-send"]')
        if await send_btn.count() == 0:
            send_btn = self.page.locator('button[aria-label="Enviar"]')

        await send_btn.click()
        await asyncio.sleep(3)

    async def enviar_para_cliente(self, numero: str, texto: str):
        await self.enviar_texto(numero, texto)

    async def enviar_midia_para_cliente(self, numero: str, caminho: str, legenda: str = ""):
        await self.enviar_midia(numero, caminho, legenda)

    async def solicitar_frete_transportadora(self, transportadora: dict, produto, cliente_info: dict):
        nome = transportadora["nome"]
        numero = transportadora["numero"]

        msg = (
            f"Ola {nome}, solicitacao de cotacao de frete:\n\n"
            f"Produto: {produto['nome']}\n"
            f"Dimensoes: {produto['medidas']}\n"
            f"Peso: {produto['peso']}\n\n"
            f"Endereco de entrega:\n"
            f"{cliente_info.get('endereco', 'N/I')}\n"
            f"CEP: {cliente_info.get('cep', 'N/I')}\n"
            f"Cidade/UF: {cliente_info.get('cidade', 'N/I')} - {cliente_info.get('estado', 'N/I')}\n\n"
            f"Favor informar valor do frete e prazo de entrega."
        )

        await self.enviar_texto(numero, msg)
        return nome

    async def aguardar_resposta_transportadora(self, transportadora_nome: str, timeout: int = 120) -> str | None:
        inicio = time.time()
        tamanho_anterior = len(self.ultimas_mensagens)

        while time.time() - inicio < timeout:
            await asyncio.sleep(5)
            chats = await self.obter_chats()

            for chat in chats:
                if transportadora_nome.lower() not in chat["nome"].lower():
                    continue
                if not chat["nao_lida"]:
                    continue

                chave = f"{chat['nome']}:{chat['texto']}"
                if chave not in self.ultimas_mensagens:
                    self.ultimas_mensagens.add(chave)
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
            if len(telefone) < 10:
                telefone = "5555" + re.sub(r'\D', '', remetente)

            cliente_id = criar_cliente(telefone, nome=remetente)
            conversa = get_conversa_ativa(telefone)

            if not conversa:
                conv_id = criar_conversa(cliente_id)
            else:
                conv_id = conversa["conversa_id"]

            salvar_mensagem(conv_id, "cliente", msg_texto)

            historico = get_historico_conversa(conv_id, limite=30)
            eh_primeira_msg = len(historico) <= 1

            if eh_primeira_msg:
                resposta = menu_interativo()
                await self.enviar_para_cliente(telefone, resposta)
                salvar_mensagem(conv_id, "agente", resposta)
                return

            numero = msg_texto.strip()
            if numero.isdigit():
                produto = produto_por_id(int(numero))
                if produto:
                    resposta = (
                        f"Voce escolheu: {produto['nome']}\n\n"
                        f"{detalhar(produto['id'])}\n\n"
                        f"Quer que eu envie a foto com detalhes deste modelo?"
                    )
                    await self.enviar_para_cliente(telefone, resposta)
                    salvar_mensagem(conv_id, "agente", resposta)
                    atualizar_produto_interesse(conv_id, produto["id"])
                    resposta_comando = f"[ENVIAR_MIDIA:{produto['id']}:foto]"
                    comando = extrair_comando(resposta_comando)
                    if comando:
                        await self.executar_comando(comando, conv_id, cliente_id, telefone, remetente)
                    return

            try:
                resposta = gerar_resposta(historico)
            except Exception as e:
                print(f"[ERRO] Gemini falhou: {e}")
                await self.enviar_para_cliente(telefone, "Desculpe, estou com problemas para processar sua mensagem. Tente novamente em instantes.")
                return

            comando = extrair_comando(resposta)
            resposta_limpa = limpar_resposta(resposta)

            if resposta_limpa:
                await self.enviar_para_cliente(telefone, resposta_limpa)
                salvar_mensagem(conv_id, "agente", resposta_limpa)

            if comando:
                await self.executar_comando(comando, conv_id, cliente_id, telefone, remetente)

        except Exception as e:
            print(f"[ERRO] processar_mensagem: {e}")
        finally:
            self.processando.pop(remetente, None)

    async def executar_comando(self, comando: dict, conv_id: int, cliente_id: int, telefone: str, remetente: str):
        acao = comando["acao"]

        if acao == "enviar_midia":
            produto_id = comando["produto_id"]
            tipo = comando["tipo"]
            produto = next((p for p in PRODUTOS if p["id"] == produto_id), None)
            if produto:
                midia_dir = BASE_DIR / "media" / "churrasqueiras" / produto["midia_dir"]
                if tipo == "foto":
                    folder = midia_dir / "folder.jpg"
                    if folder.exists():
                        await self.enviar_midia_para_cliente(telefone, folder, produto["nome"])
                        salvar_mensagem(conv_id, "agente", "[Enviou folder.jpg]", "foto")
                        await asyncio.sleep(1)
                    fotos = sorted(
                        list(midia_dir.glob("*.jpg")) + list(midia_dir.glob("*.png")) + list(midia_dir.glob("*.jpeg")),
                        key=lambda f: f.name,
                    )
                    fotos = [f for f in fotos if f.name != "folder.jpg"]
                    if fotos:
                        await self.enviar_midia_para_cliente(telefone, fotos[0], produto["nome"])
                        salvar_mensagem(conv_id, "agente", f"[Enviou foto: {fotos[0].name}]", "foto")
                    if not folder.exists() and not fotos:
                        await self.enviar_para_cliente(telefone, "Desculpe, nao encontrei a foto deste produto.")
                elif tipo == "video":
                    videos = list(midia_dir.glob("*.mp4")) + list(midia_dir.glob("*.mov"))
                    if videos:
                        await self.enviar_midia_para_cliente(telefone, videos[0], produto["nome"])
                        salvar_mensagem(conv_id, "agente", f"[Enviou video: {videos[0].name}]", "video")
                    else:
                        await self.enviar_para_cliente(telefone, "Desculpe, nao encontrei o video deste produto.")
                atualizar_produto_interesse(conv_id, produto_id)

        elif acao == "solicitar_frete":
            produto_id = comando["produto_id"]
            cidade = comando["cidade"]
            estado = comando["estado"]
            cep = comando["cep"]

            produto = next((p for p in PRODUTOS if p["id"] == produto_id), None)
            if not produto:
                return

            cliente_info = {"cidade": cidade, "estado": estado, "cep": cep}
            atualizar_cliente(cliente_id, cidade=cidade, estado=estado, cep=cep)

            await self.enviar_para_cliente(telefone, "Estou solicitando o frete as transportadoras. Assim que tiver retorno, te aviso!")

            for transportadora in TRANSPORTADORAS:
                cot_id = criar_cotacao(conv_id, transportadora["nome"])
                await self.solicitar_frete_transportadora(transportadora, produto, cliente_info)
                resp = await self.aguardar_resposta_transportadora(transportadora["nome"], timeout=180)

                if resp:
                    valor = self.extrair_valor_frete(resp)
                    prazo = self.extrair_prazo(resp)
                    atualizar_cotacao(cot_id, valor_frete=valor, prazo=prazo, status="recebida")

                    msg_cliente = (
                        f"Recebi a cotacao da {transportadora['nome']}:\n"
                        f"Valor do frete: R$ {valor:.2f}\n"
                        f"Prazo: {prazo or 'a confirmar'}\n\n"
                        f"Total com frete: R$ {produto['preco'] + valor:.2f}\n"
                        f"Deseja confirmar a compra?"
                    )
                    await self.enviar_para_cliente(telefone, msg_cliente)
                else:
                    atualizar_cotacao(cot_id, status="sem_resposta")

        elif acao == "venda_confirmada":
            cliente_nome = comando["cliente_nome"]
            produto_id = comando["produto_id"]
            valor_total = comando["valor_total"]

            produto = next((p for p in PRODUTOS if p["id"] == produto_id), None)
            if not produto:
                return

            venda_id = criar_venda(conv_id, cliente_id, produto_id, produto["preco"])
            atualizar_etapa_conversa(conv_id, "fechada")

            await self.enviar_para_cliente(
                telefone,
                f"Venda confirmada!\n\n"
                f"Produto: {produto['nome']}\n"
                f"Total: R$ {valor_total:.2f}\n\n"
                f"Em breve entrarei em contato com os detalhes de pagamento e entrega. Obrigado!"
            )

            await self.enviar_para_cliente(
                SEU_NUMERO,
                f"NOVA VENDA CONFIRMADA!\n\n"
                f"Cliente: {cliente_nome}\n"
                f"Telefone: {telefone}\n"
                f"Produto: {produto['nome']}\n"
                f"Valor Total: R$ {valor_total:.2f}\n"
                f"ID Venda: {venda_id}"
            )

    def extrair_valor_frete(self, texto: str) -> float:
        padroes = [
            r"(?:R\$|R\$)?\s*(\d+[.,]\d{2,})",
            r"(?:valor|frete|total)\s*(?:de|:)?\s*(?:R\$)?\s*(\d+[.,]\d+)",
        ]
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return float(match.group(1).replace(".", "").replace(",", "."))
        return 50.0

    def extrair_prazo(self, texto: str) -> str | None:
        padroes = [
            r"(\d+)\s*(?:dia|dias)",
            r"(?:prazo|entrega)\s*(?:de|:)?\s*(\d+\s*(?:dia|dias))",
        ]
        for padrao in padroes:
            match = re.search(padrao, texto, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    async def escutar_mensagens(self):
        print("Ouvindo mensagens... Pressione Ctrl+C para parar.")
        await self.debug_estrutura()

        while True:
            try:
                novas = await self.obter_novas_mensagens()

                for msg in novas:
                    nome = msg["nome"]
                    texto = msg["mensagem"]

                    if "Voce:" in texto[:10] or "You:" in texto[:5]:
                        continue

                    print(f"\n>>> Nova mensagem de {nome}: {texto}")
                    await self.processar_mensagem(nome, texto)

                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ERRO] loop escutar: {e}")
                await asyncio.sleep(5)

    async def parar(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
