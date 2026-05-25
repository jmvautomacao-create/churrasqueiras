import asyncio
import re
from pathlib import Path
from playwright.async_api import async_playwright

BASE = Path(__file__).parent

async def safe(texto):
    return texto.encode('ascii', errors='replace').decode('ascii')

async def main():
    print("="*50)
    print("TESTE DE COMUNICACAO WHATSAPP")
    print("="*50)

    from config import NUMERO_TESTE, SEU_NUMERO
    print(f"   Numero de teste: {NUMERO_TESTE}")
    print(f"   Seu numero (logado): {SEU_NUMERO}")
    print()

    playwright = await async_playwright().start()
    user_data_dir = str(BASE / "data" / "whatsapp_session")

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir, headless=False,
    )
    page = await context.new_page()

    await page.goto("https://web.whatsapp.com")
    print("Aguardando login...")

    logado = False
    for i in range(60):
        await asyncio.sleep(2)
        try:
            if "web.whatsapp.com" not in page.url:
                await page.goto("https://web.whatsapp.com")
                continue
            side = await page.query_selector('#side')
            if side:
                logado = True
                print(f"  Login OK! ({i*2}s)")
                break
        except:
            pass

    if not logado:
        print("Falha no login")
        await context.close()
        await playwright.stop()
        return

    # --- TESTE 1: Verificar se consegue ler chats ---
    print("\n--- TESTE 1: Leitura de chats ---")
    chats_raw = await page.evaluate("""
        () => {
            const achados = [];
            const side = document.querySelector('#side');
            if (!side) return '[]';
            const chats = side.querySelectorAll('[role="row"]');
            chats.forEach((chat, i) => {
                if (i > 50) return;
                const el = chat.querySelector('[title]');
                const nome = el ? el.getAttribute('title') : '';
                if (!nome || nome.length > 30) return;
                const spans = chat.querySelectorAll('span[dir="auto"]');
                const texto = spans.length > 1 ? spans[spans.length - 1].textContent.trim() : '';
                if (texto.startsWith('default-')) return;
                const badge = chat.querySelector('[data-testid="icon-unread-count"]');
                achados.push({nome, texto: texto.substring(0, 80), nao_lida: !!badge});
            });
            return JSON.stringify(achados);
        }
    """)
    import json
    chats = json.loads(chats_raw)
    print(f"  Total chats detectados: {len(chats)}")

    # Procurar o numero de teste
    encontrou_teste = False
    for c in chats:
        tel = re.sub(r'\D', '', c['nome'])
        if NUMERO_TESTE in tel:
            encontrou_teste = True
            print(f"  >>> CHAT DE TESTE ENCONTRADO: {await safe(c['nome'])}")
            print(f"      Ultima msg: {await safe(c['texto'])}")
            print(f"      Nao lida: {c['nao_lida']}")

    if not encontrou_teste:
        print(f"  >>> CHAT DE TESTE NAO ENCONTRADO em {len(chats)} chats")
        print(f"      O numero {NUMERO_TESTE} precisa ter uma conversa com este WhatsApp")

    # --- TESTE 2: Enviar mensagem ---
    print("\n--- TESTE 2: Envio de mensagem ---")
    print(f"  Enviando para {NUMERO_TESTE}...")

    url = f"https://web.whatsapp.com/send?phone={NUMERO_TESTE}"
    await page.goto(url, wait_until="domcontentloaded")
    await asyncio.sleep(5)

    # Digitar
    caixa = None
    for _ in range(15):
        for sel in ['[contenteditable="true"]', 'div[role="textbox"]']:
            caixa = await page.query_selector(sel)
            if caixa:
                break
        if caixa:
            break
        await asyncio.sleep(1)

    if not caixa:
        print("  ERRO: Input nao encontrado")
        await context.close()
        await playwright.stop()
        return

    texto_teste = "Ola, gostaria de saber sobre as churrasqueiras"
    await caixa.fill("")
    await caixa.type(texto_teste, delay=20)
    await asyncio.sleep(1)
    print(f"  Texto digitado: {texto_teste}")

    # Enviar
    enviou = False
    for _ in range(20):
        ok = await page.evaluate("""
            () => {
                const botoes = document.querySelectorAll('button');
                for (const btn of botoes) {
                    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                    if ((label.includes('enviar') || label.includes('send')) && btn.offsetParent !== null) {
                        btn.click(); return true;
                    }
                }
                const spans = document.querySelectorAll('span[data-icon="send"]');
                for (const sp of spans) {
                    const pai = sp.closest('button') || sp.parentElement;
                    if (pai && pai.offsetParent !== null) { pai.click(); return true; }
                    if (sp.offsetParent !== null) { sp.click(); return true; }
                }
                return false;
            }
        """)
        if ok:
            enviou = True
            print("  >>> MENSAGEM ENVIADA COM SUCESSO!")
            break
        await asyncio.sleep(0.5)

    if not enviou:
        print("  ERRO: Nao conseguiu enviar")
        await context.close()
        await playwright.stop()
        return

    await asyncio.sleep(3)

    # --- TESTE 3: Verificar se mensagem aparece no chat ---
    print("\n--- TESTE 3: Verificacao da mensagem enviada ---")
    await page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    chats_raw2 = await page.evaluate("""
        () => {
            const achados = [];
            const side = document.querySelector('#side');
            if (!side) return '[]';
            const chats = side.querySelectorAll('[role="row"]');
            chats.forEach((chat) => {
                const el = chat.querySelector('[title]');
                const nome = el ? el.getAttribute('title') : '';
                if (!nome) return;
                const spans = chat.querySelectorAll('span[dir="auto"]');
                const texto = spans.length > 1 ? spans[spans.length - 1].textContent.trim() : '';
                const tel = (nome + ' ' + texto).replace(/\\D/g, '');
                achados.push({nome, texto: texto.substring(0, 100), tel: tel.substring(0, 20)});
            });
            return JSON.stringify(achados);
        }
    """)
    chats2 = json.loads(chats_raw2)
    for c in chats2:
        if NUMERO_TESTE in c.get('tel', ''):
            print(f"  >>> Chat encontrado: {await safe(c['nome'])}")
            print(f"      Ultima mensagem: {await safe(c['texto'])}")
            if texto_teste in c['texto']:
                print(f"  >>> MENSAGEM CONFIRMADA!")
            break
    else:
        print(f"  AVISO: Chat do teste nao encontrado na segunda leitura")
        print(f"  Mostrando alguns chats:")
        for c in chats2[:5]:
            print(f"    {await safe(c['nome'])}: {await safe(c['texto'][:50])} | tel:{c['tel']}")

    print("\n" + "="*50)
    print("TESTE CONCLUIDO!")
    print("Navegador permanecera aberto para inspecao.")
    print("Feche manualmente quando terminar.")
    print("="*50)

    await asyncio.sleep(30)
    await context.close()
    await playwright.stop()

if __name__ == "__main__":
    asyncio.run(main())
