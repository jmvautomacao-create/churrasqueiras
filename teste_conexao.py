import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

async def testar():
    from playwright.async_api import async_playwright

    def safe(texto):
        if not isinstance(texto, str):
            texto = str(texto)
        return texto.encode('ascii', errors='replace').decode('ascii')

    print("Iniciando teste de conexao WhatsApp...")

    playwright = await async_playwright().start()
    user_data_dir = str(Path(__file__).parent / "data" / "whatsapp_session")

    import shutil
    sessao = Path(user_data_dir)
    if sessao.exists():
        shutil.rmtree(sessao)
        print("Sessao limpa.")

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir, headless=False,
    )
    page = await context.new_page()

    await page.goto("https://web.whatsapp.com")
    print("Aguardando login (escaneie o QR Code)...")

    logado = False
    for i in range(60):
        await asyncio.sleep(2)
        try:
            url = page.url
            titulo = await page.title()
            print(f"  [{i*2}s] {safe(titulo)} | {safe(url)}")

            if "web.whatsapp.com" not in url:
                print("  -> Redirecionado! Voltando...")
                await page.goto("https://web.whatsapp.com")
                await asyncio.sleep(2)
                continue

            panel = await page.query_selector('[data-testid="conversation-panel-main"]')
            side = await page.query_selector('#side')
            if panel or side:
                logado = True
                print("LOGADO COM SUCESSO!")
                break
        except Exception as e:
            print(f"  -> {safe(e)}")

    if not logado:
        print("Nao foi possivel fazer login.")
        await context.close()
        await playwright.stop()
        return

    # Teste: escanear chats
    print("\n--- Escaneando chats ---")

    for tentativa in range(10):
        try:
            chats = await page.evaluate("""
                () => {
                    const r = [];
                    const side = document.querySelector('#side');
                    if (!side) return "sem sidebar";
                    const items = side.querySelectorAll('[role="row"]');
                    items.forEach((item, i) => {
                        if (i > 10) return;
                        const titleEl = item.querySelector('[title]');
                        const nome = titleEl ? titleEl.getAttribute('title') : 'sem titulo';
                        const badge = item.querySelector('[data-testid="icon-unread-count"]') ||
                                     item.querySelector('[aria-label*="nao lida"]');
                        const texto = (item.textContent || '').substring(0, 60);
                        r.push({i, nome, badge: !!badge, texto: texto.replace(/[\\u2714\\u2716\\u2764]/g,'')});
                    });
                    return JSON.stringify(r);
                }
            """)
            print(f"Chats encontrados: {safe(chats)}")
            break
        except Exception as e:
            print(f"Tentativa {tentativa+1} falhou: {safe(e)}")
            if "navigation" in str(e).lower() or "context" in str(e).lower():
                print("  -> Navegacao detectada, reabrindo...")
                await page.goto("https://web.whatsapp.com")
                await asyncio.sleep(3)
            else:
                break
        await asyncio.sleep(2)

    # Teste: enviar mensagem
    print("\n--- Teste de envio ---")
    # Usando o proprio numero do usuario (ou da transportadora A) como teste
    from config import SEU_NUMERO
    numero_teste = SEU_NUMERO
    print(f"Enviando mensagem de teste para {numero_teste}...")

    if numero_teste:
        try:
            url = f"https://web.whatsapp.com/send?phone={numero_teste}"
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            inserido = await page.evaluate("""
                () => {
                    const divs = document.querySelectorAll('[contenteditable="true"]');
                    for (const div of divs) {
                        if (div.offsetParent !== null) {
                            div.focus();
                            div.textContent = '';
                            document.execCommand('insertText', false, 'Teste do bot de churrasqueiras!');
                            return true;
                        }
                    }
                    return false;
                }
            """)
            print(f"  Texto inserido: {inserido}")
            await asyncio.sleep(1)

            for _ in range(20):
                enviou = await page.evaluate("""
                    () => {
                        const botoes = document.querySelectorAll('button');
                        for (const btn of botoes) {
                            const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                            if ((label.includes('enviar') || label.includes('send')) && btn.offsetParent !== null) {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                if enviou:
                    print(f"  Mensagem enviada com sucesso!")
                    break
                await asyncio.sleep(0.5)
        except Exception as e:
            print(f"  Erro no envio: {safe(e)}")

    print("\nTeste concluido. Navegador permanecera aberto por 60s para inspecao.")
    await asyncio.sleep(60)

    await context.close()
    await playwright.stop()
    print("Navegador fechado.")

if __name__ == "__main__":
    asyncio.run(testar())
