import json
from google import genai
from config import GEMINI_API_KEY, PRODUTOS

cliente = genai.Client(api_key=GEMINI_API_KEY)

SISTEMA = f"""Você é um vendedor de churrasqueiras no WhatsApp. Atenda os clientes de forma educada e objetiva.

## CATÁLOGO DE PRODUTOS
{json.dumps(PRODUTOS, indent=2, ensure_ascii=False)}

## FLUXO DE VENDAS
Sempre siga estas etapas em ordem:
1. **Saudação** - Cumprimente e pergunte se a pessoa tem interesse em churrasqueiras
2. **Apresentar catálogo** - Mostre os modelos disponíveis com preços
3. **Apresentar produto** - Quando o cliente escolher, detalhe o produto e PEÇA CONFIRMAÇÃO para enviar fotos/vídeos
4. **Coletar dados** - Após confirmar interesse, peça: NOME COMPLETO, CPF, ENDEREÇO (logradouro, número, bairro, cidade, estado, CEP)
5. **Frete** - Informe que vai solicitar o frete e retornará em breve
6. **Fechamento** - Apresente o valor total (produto + frete) e confirme a venda

## REGRAS IMPORTANTES
- Seja simpático e profissional
- Nunca invente preços - use APENAS os preços do catálogo acima
- Quando precisar enviar mídia (foto/vídeo), responda com: [ENVIAR_MIDIA:<id_produto>:<tipo>]
  onde tipo pode ser "foto" ou "video"
- Quando precisar solicitar frete à transportadora, responda com: [SOLICITAR_FRETE:<id_produto>:<cidade>:<estado>:<cep>]
- Quando o cliente fornecer dados (CPF, endereço), confirme e armazene mentalmente
- Quando o frete for informado, repasse o valor ao cliente
- Quando a venda for confirmada, responda com: [VENDA_CONFIRMADA:<cliente_nome>:<telefone>:<produto_id>:<valor_total>]
- Responda sempre em português brasileiro"""


def gerar_resposta(historico: list[dict]) -> str:
    messages = [{"role": "user" if m["origem"] == "cliente" else "model", "parts": [m["conteudo"]]} for m in historico]

    response = cliente.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            {"role": "user", "parts": [SISTEMA]},
            *messages,
        ],
    )
    return response.text.strip()


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
