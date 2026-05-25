from produtos import menu_interativo, submenu_produto, valor_produto, produto_por_id
from config import PRODUTOS

safe = lambda t: t.encode('ascii', errors='replace').decode('ascii')

print('=== TESTE DE MENUS ===\n')

print('--- Menu Principal (sem precos) ---')
print(menu_interativo())
print()

for p in PRODUTOS:
    print(f'--- Submenu {p["id"]}: {safe(p["nome"][:50])} ---')
    print(submenu_produto(p))
    print()

print('--- Exemplo Valor ---')
print(valor_produto(PRODUTOS[0]))
print()

print('=== IMPORT TEST ===')
from database import init_db
init_db()
print('DB initialized OK')

from gemini_agent import gerar_resposta, extrair_comando, limpar_resposta
print('Gemini agent imported OK')

print('\n=== TODOS OS TESTES OK ===')
