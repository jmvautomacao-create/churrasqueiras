"""
Testes unitários para extração de dados de frete.
Uso: python test_extracao.py
"""
import re


class BotStub:
    """Stub do WhatsAppBot com os métodos de extração."""

    def extrair_valor_frete(self, texto: str) -> float:
        padroes = [
            r"(?:VALOR\s*(?:DO\s*)?FRETE|FRETE)\s*:?\s*(?:R\$)?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)",
            r"(?:R\$)\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)",
            r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s*(?:reais|R\$)?",
        ]
        for p in padroes:
            m = re.search(p, texto, re.IGNORECASE)
            if m:
                val = m.group(1)
                val = re.sub(r"[^\d,.]", "", val)
                if "," in val and "." in val:
                    if val.rindex(",") > val.rindex("."):
                        val = val.replace(".", "").replace(",", ".")
                    else:
                        val = val.replace(",", "")
                elif "," in val:
                    val = val.replace(".", "").replace(",", ".")
                return float(val)
        return 0.0

    def extrair_prazo(self, texto: str) -> str | None:
        padroes = [
            r"(\d+[_\s-]*dias?\s*úteis?)",
            r"(\d+[_\s-]*dias?\s*uteis)",
            r"(\d+[_\s-]*dias?\s*corridos?)",
            r"(\d+[_\s-]*dias?)",
        ]
        for p in padroes:
            m = re.search(p, texto, re.IGNORECASE)
            if m:
                return m.group(0)
        return None

    def extrair_protocolo_transportadora(self, texto: str) -> str | None:
        padroes = [
            r"Protocolo\s+Transportadora:\s*(\S+)",
            r"Protocolo[:\s]+\s*(\S+)",
            r"Prot[.:]?\s*(?:transp[.:]?)?\s*(\S+)",
            r"(?:COD[.:]?|PROT(?!OCOL)[.:]?|PEDIDO[.:]?)\s*(\d{4,})",
        ]
        for p in padroes:
            m = re.search(p, texto, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val.startswith(("VALOR", "PRAZO", "Protocolo")):
                    continue
                return val
        return None


bot = BotStub()

ERROS = 0
ACERTOS = 0


def teste(nome, fn, entrada, esperado):
    global ERROS, ACERTOS
    resultado = fn(entrada)
    if resultado == esperado:
        ACERTOS += 1
        print(f"  [OK] {nome}")
    else:
        ERROS += 1
        print(f"  [FAIL] {nome}")
        print(f"      entrada:  {entrada!r}")
        print(f"      esperado: {esperado!r}")
        print(f"      obtido:   {resultado!r}")


# ─── Cenários de extração ───

print("=== extrair_valor_frete ===")

teste("VALOR DO FRETE com R$", bot.extrair_valor_frete,
      "VALOR DO FRETE R$ 150,00", 150.00)

teste("VALOR DO FRETE: com R$", bot.extrair_valor_frete,
      "VALOR DO FRETE: R$ 200,00", 200.00)

teste("Apenas R$", bot.extrair_valor_frete,
      "R$ 300,00", 300.00)

teste("Frete: R$ sem descricao", bot.extrair_valor_frete,
      "Frete: R$ 180,00", 180.00)

teste("Valor com ponto milhar", bot.extrair_valor_frete,
      "VALOR DO FRETE: R$ 1.250,50", 1250.50)

teste("Valor sem R$", bot.extrair_valor_frete,
      "VALOR FRETE 99,90", 99.90)

teste("Sem valor nenhum", bot.extrair_valor_frete,
      "Ola tudo bem?", 0.0)

teste("Valor inteiro", bot.extrair_valor_frete,
      "VALOR DO FRETE: R$ 500", 500.00)

print()
print("=== extrair_prazo ===")

teste("Prazo completo acentuado", bot.extrair_prazo,
      "PRAZO DE ENTREGA: 20 dias úteis", "20 dias úteis")

teste("Prazo sem acento", bot.extrair_prazo,
      "PRAZO DE ENTREGA 15 dias uteis", "15 dias uteis")

teste("Prazo com underline", bot.extrair_prazo,
      "Prazo: 30_dias", "30_dias")

teste("Apenas dias", bot.extrair_prazo,
      "Prazo: 25 dias", "25 dias")

teste("Sem prazo", bot.extrair_prazo,
      "VALOR DO FRETE: R$ 150,00", None)

teste("Prazo dias corridos", bot.extrair_prazo,
      "PRAZO: 10 dias corridos", "10 dias corridos")

print()
print("=== extrair_protocolo_transportadora ===")

teste("Protocolo Transportadora: COD", bot.extrair_protocolo_transportadora,
      "Protocolo Transportadora: COD12345", "COD12345")

teste("Protocolo Transportadora: PROT", bot.extrair_protocolo_transportadora,
      "Protocolo Transportadora: PROT98765 CPF: 68225369068", "PROT98765")

teste("Protocolo: sem Transportadora", bot.extrair_protocolo_transportadora,
      "Protocolo: ABC123", "ABC123")

teste("Prot: abreviado", bot.extrair_protocolo_transportadora,
      "Prot: 998877", "998877")

teste("PROT sem dois-pontos", bot.extrair_protocolo_transportadora,
      "PROT 554433", "554433")

teste("COD: prefixo", bot.extrair_protocolo_transportadora,
      "COD: 771122", "771122")

teste("PEDIDO: prefixo", bot.extrair_protocolo_transportadora,
      "PEDIDO: 11223344", "11223344")

teste("Sem protocolo", bot.extrair_protocolo_transportadora,
      "VALOR DO FRETE: R$ 150,00", None)

teste("PROTOCOLO TRANSPORTADORA maiusculo", bot.extrair_protocolo_transportadora,
      "PROTOCOLO TRANSPORTADORA: XYZ999", "XYZ999")

teste("Protocolo valor unico digito", bot.extrair_protocolo_transportadora,
      "Protocolo Transportadora: 1", "1")

# ─── Mensagens completas simulando resposta real da FOB ───

print()
print("=== Mensagens completas (integração) ===")

msg1 = """Ola boa noite tudo bem?
VALOR DO FRETE R$ 150,00
PRAZO DE ENTREGA 20 dias uteis
CPF/CNPJ: 68225369068
Protocolo Transportadora: COD12345"""

teste("Mensagem completa 1 - valor", bot.extrair_valor_frete, msg1, 150.00)
teste("Mensagem completa 1 - prazo", bot.extrair_prazo, msg1, "20 dias uteis")
teste("Mensagem completa 1 - protocolo", bot.extrair_protocolo_transportadora, msg1, "COD12345")

msg2 = """VALOR DO FRETE: R$ 200,00
PRAZO DE ENTREGA: 15 dias úteis
Protocolo Transportadora: PROT98765
CPF/CNPJ: 68225369068"""

teste("Mensagem completa 2 - valor", bot.extrair_valor_frete, msg2, 200.00)
teste("Mensagem completa 2 - prazo", bot.extrair_prazo, msg2, "15 dias úteis")
teste("Mensagem completa 2 - protocolo", bot.extrair_protocolo_transportadora, msg2, "PROT98765")

msg3 = """R$ 300,00
30 dias úteis
Protocolo: ABC123
CPF: 68225369068"""

teste("Mensagem completa 3 - valor", bot.extrair_valor_frete, msg3, 300.00)
teste("Mensagem completa 3 - prazo", bot.extrair_prazo, msg3, "30 dias úteis")
teste("Mensagem completa 3 - protocolo", bot.extrair_protocolo_transportadora, msg3, "ABC123")

msg4 = """Frete: R$ 180,00
Prazo: 25 dias
Prot: 998877
68225369068"""

teste("Mensagem completa 4 - valor", bot.extrair_valor_frete, msg4, 180.00)
teste("Mensagem completa 4 - prazo", bot.extrair_prazo, msg4, "25 dias")
teste("Mensagem completa 4 - protocolo", bot.extrair_protocolo_transportadora, msg4, "998877")

# ─── Resumo ───

print()
print("=" * 40)
total = ACERTOS + ERROS
print(f"Resultado: {ACERTOS}/{total} acertos, {ERROS} erros")
if ERROS == 0:
    print(">>> TODOS OS TESTES PASSARAM <<<")
else:
    print(f">>> {ERROS} TESTE(S) FALHARAM <<<")
print("=" * 40)
