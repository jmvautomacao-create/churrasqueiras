import stripe
from config import STRIPE_SECRET_KEY

stripe.api_key = STRIPE_SECRET_KEY


def criar_checkout_pix_cartao(
    nome_produto: str,
    valor_total: float,  # em reais
    cliente_nome: str,
    cliente_telefone: str,
    venda_id: int,
) -> str | None:
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "brl",
                    "product_data": {
                        "name": nome_produto,
                    },
                    "unit_amount": int(round(valor_total * 100)),
                },
                "quantity": 1,
            }],
            metadata={
                "venda_id": str(venda_id),
                "cliente_telefone": cliente_telefone,
            },
            success_url="https://web.whatsapp.com",
            cancel_url="https://web.whatsapp.com",
        )
        return session.url
    except Exception as e:
        print(f"[STRIPE] Erro ao criar checkout: {e}")
        return None


def verificar_pagamento(session_id: str) -> bool:
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        return session.payment_status == "paid"
    except Exception as e:
        print(f"[STRIPE] Erro ao verificar pagamento: {e}")
        return False
