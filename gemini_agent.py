import json
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, PRODUTOS

cliente = genai.Client(api_key=GEMINI_API_KEY)

SISTEMA = f"""Você é um vendedor de churrasqueiras no WhatsApp. Atenda os clientes de forma educada e objetiva.

## CATÁLOGO DE PRODUTOS
{json.dumps(PRODUTOS, indent=2, ensure_ascii=False)}

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


def gerar_resposta(historico: list[dict]) -> str:
    from google.genai import types

    contents = [types.Content(role="user", parts=[types.Part(text=SISTEMA)])]
    for m in historico:
        role = "user" if m["origem"] == "cliente" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=m["conteudo"])]))

    response = cliente.models.generate_content(
        model="gemini-2.0-flash",
        contents=contents,
    )
    return response.text.strip()


def resposta_fallback(historico: list[dict]) -> str:
    from produtos import menu_interativo
    return (
        "Ola! Desculpe, estou com problemas de conexao no momento.\n\n"
        "Enquanto isso, veja nosso catalogo:\n\n"
        f"{menu_interativo()}"
    )


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
