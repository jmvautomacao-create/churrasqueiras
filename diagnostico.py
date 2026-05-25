import asyncio
from playwright.async_api import async_playwright
from pathlib import Path

BASE_DIR = Path(__file__).parent

async def diagnosticar():
    print("Iniciando diagnostico do WhatsApp Web...")

    playwright = await async_playwright().start()
    user_data_dir = str(BASE_DIR / "data" / "whatsapp_session")

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
    )

    page = await context.new_page()
    await page.goto("https://web.whatsapp.com")

    print("Aguardando login (60s)...")
    try:
        await page.wait_for_selector('[data-testid="conversation-panel-main"]', timeout=60000)
        print("Login OK!")
    except:
        print("Login nao detectado, continuando mesmo assim...")

    await asyncio.sleep(5)

    print("\n=== DIAGNOSTICO DA ESTRUTURA ===")

    info = await page.evaluate("""
        () => {
            const resultados = [];

            // 1. Testar varios seletores para a sidebar
            const seletores = [
                '#side',
                '[data-testid="chat-list"]',
                '[role="tabpanel"]',
                'div[tabindex="-1"]'
            ];

            for (const sel of seletores) {
                const el = document.querySelector(sel);
                resultados.push({
                    seletor: sel,
                    encontrado: !!el,
                    filhos: el ? el.querySelectorAll('[role="row"]').length : 0,
                    tag: el ? el.tagName : '-'
                });
            }

            // 2. Procurar todos os [role="row"] no documento
            const allRows = document.querySelectorAll('[role="row"]');
            resultados.push({seletor: 'TOTAL [role="row"]', encontrado: true, filhos: allRows.length});

            // 3. Para cada row, ver se tem title
            const chatsInfo = [];
            allRows.forEach((row, i) => {
                if (i > 10) return;
                const titleEl = row.querySelector('[title]');
                const nome = titleEl ? titleEl.getAttribute('title') : 'sem title';
                const hasBadge = !!row.querySelector('[data-testid="icon-unread-count"]');
                const texto = (row.textContent || '').substring(0, 80);
                chatsInfo.push({index: i, nome, hasBadge, texto});
            });

            return JSON.stringify({seletores: resultados, chats: chatsInfo}, null, 2);
        }
    """)

    print(info)

    print("\nDiagnostico concluido. O navegador permanecera aberto para inspecao manual.")
    print("Pressione Ctrl+C no terminal para fechar.")

    try:
        while True:
            await asyncio.sleep(10)
    except:
        pass
    finally:
        await context.close()
        await playwright.stop()

if __name__ == "__main__":
    asyncio.run(diagnosticar())
