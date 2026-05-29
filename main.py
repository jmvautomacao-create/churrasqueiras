import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from database import init_db
from whatsapp_bot import WhatsAppBot


async def main():
    print("=" * 50)
    print("   AGENTE DE VENDAS - CHURRASQUEIRAS")
    print("   WhatsApp Web + Groq (LLaMA 3.3)")
    print("=" * 50)

    init_db()
    print("Banco de dados inicializado.")

    bot = WhatsAppBot()
    sucesso = await bot.iniciar()

    if not sucesso:
        print("Não foi possível fazer login no WhatsApp Web.")
        return

    try:
        await bot.escutar_mensagens()
    except KeyboardInterrupt:
        print("\nParando o bot...")
    finally:
        await bot.parar()
        print("Bot encerrado.")


if __name__ == "__main__":
    asyncio.run(main())
