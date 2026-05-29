import json
import time
from openai import OpenAI
from config import GROQ_API_KEY, PRODUTOS

cliente = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

_catalogo = "\n".join(
    f"{p['id']}. {p['nome']} - R$ {p['preco']:,.2f}\n"
    f"   Descrição: {p['descricao']}\n"
    f"   Medidas: {p['medidas']}, Peso: {p['peso']}"
    for p in PRODUTOS
)

SISTEMA = f"""Você é um vendedor de churrasqueiras no WhatsApp. Atenda os clientes de forma educada e objetiva.

## CATÁLOGO DE PRODUTOS
{_catalogo}

## SEU PAPEL
O sistema já envia automaticamente:
- Menu principal com a lista de produtos numerados
- Submenu com opções (Folder, Valor, Foto, Vídeo, Frete) quando o cliente escolhe um produto
- Coleta de dados para frete (nome, CPF, endereço)

Você atua quando o cliente faz perguntas abertas (ex: "qual a diferença?", "é boa?", "tem garantia?") ou após o frete ser cotado para finalizar a venda.

## REGRAS IMPORTANTES
- Seja simpático e profissional
- Nunca invente preços - use APENAS os preços do catálogo acima
- Quando precisar enviar mídia (foto/vídeo), responda com: [ENVIAR_MIDIA:<id_produto>:<tipo>]
  onde tipo pode ser "foto", "video" ou "folder"
- Quando precisar solicitar frete à transportadora, responda com: [SOLICITAR_FRETE:<id_produto>:<cidade>:<estado>:<cep>]
- Quando o cliente fornecer dados (CPF, endereço), apenas confirme educadamente (o sistema já armazena)
- Quando o frete for informado, repasse o valor ao cliente
- Quando a venda for confirmada, responda com: [VENDA_CONFIRMADA:<cliente_nome>:<telefone>:<produto_id>:<valor_total>]
- Responda sempre em português brasileiro"""

_ultima_chamada: float = 0
_INTERVALO_MINIMO = 2.0


def _throttle():
    global _ultima_chamada
    agora = time.time()
    espera = _INTERVALO_MINIMO - (agora - _ultima_chamada)
    if espera > 0:
        time.sleep(espera)
    _ultima_chamada = time.time()


def gerar_resposta(historico: list[dict]) -> str:
    _throttle()

    messages = [{"role": "system", "content": SISTEMA}]
    for m in historico[-10:]:
        role = "user" if m["origem"] == "cliente" else "assistant"
        messages.append({"role": role, "content": m["conteudo"]})

    response = cliente.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
    )
    return response.choices[0].message.content.strip()


def resposta_fallback(historico: list[dict]) -> str:
    from produtos import menu_interativo
    return menu_interativo()


def extrair_comando(texto: str) -> dict | None:
    import re

    padroes = [
        (r"\[ENVIAR_MIDIA:(\d+):(\w+)\]", lambda m: {"acao": "enviar_midia", "produto_id": int(m.group(1)), "tipo": m.group(2)}),
        (r"\[SOLICITAR_FRETE:(\d+):([^:]+):([^:]+):([^\]]+)\]", lambda m: {"acao": "solicitar_frete", "produto_id": int(m.group(1)), "cidade": m.group(2), "estado": m.group(3), "cep": m.group(4)}),
        (r"\[VENDA_CONFIRMADA:([^:]+):([^:]+):(\d+):([^\]]+)\]", lambda m: {"acao": "venda_confirmada", "cliente_nome": m.group(1), "telefone": m.group(2), "produto_id": int(m.group(3)), "valor_total": float(m.group(4))}),
    ]

    for padrao, construtor in padroes:
        match = re.search(padrao, texto)
        if match:
            return construtor(match)
    return None


def limpar_resposta(texto: str) -> str:
    import re
    texto = re.sub(r"\[ENVIAR_MIDIA:\d+:\w+\]", "", texto)
    texto = re.sub(r"\[SOLICITAR_FRETE:\d+:[^\]]+\]", "", texto)
    texto = re.sub(r"\[VENDA_CONFIRMADA:[^\]]+\]", "", texto)
    return texto.strip()
