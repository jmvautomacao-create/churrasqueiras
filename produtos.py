from config import PRODUTOS


def produto_por_id(produto_id: int) -> dict | None:
    return next((p for p in PRODUTOS if p["id"] == produto_id), None)


def produto_por_nome(nome: str) -> dict | None:
    nome_lower = nome.lower()
    return next(
        (p for p in PRODUTOS if p["nome"].lower() in nome_lower or nome_lower in p["nome"].lower()),
        None,
    )


def catalogar() -> str:
    linhas = ["CATÁLOGO DE CHURRASQUEIRAS\n"]
    for p in PRODUTOS:
        linhas.append(f"{p['id']}. {p['nome']}")
        linhas.append(f"   {p['descricao']}")
        linhas.append("")
    return "\n".join(linhas)


def detalhar(produto_id: int) -> str:
    p = produto_por_id(produto_id)
    if not p:
        return "Produto não encontrado."
    return (
        f"{p['nome']}\n\n"
        f"{p['descricao']}\n\n"
        f"Preço: R$ {p['preco']:.2f}\n"
        f"Dimensões: {p['medidas']}\n"
        f"Peso: {p['peso']}\n"
    )


def menu_interativo() -> str:
    linhas = [
        "Olá! Bem-vindo a JMV Churrasqueiras!",
        "",
        "Escolha um modelo digitando o NÚMERO correspondente:",
        "",
    ]
    for p in PRODUTOS:
        linhas.append(f"  [{p['id']}] {p['nome']}")
    linhas.append("")
    linhas.append("Digite o número do produto para ver as opções!")
    return "\n".join(linhas)


def submenu_produto(produto: dict) -> str:
    return (
        f"Você escolheu: {produto['nome']}\n\n"
        f"Escolha uma opção:\n"
        f"  [a] Folder - Ver folder do produto\n"
        f"  [b] Valor - Consultar preço\n"
        f"  [c] Foto - Enviar foto\n"
        f"  [d] Vídeo - Enviar vídeo\n"
        f"  [e] Frete - Solicitar cotação de frete\n\n"
        f"Digite a letra da opção desejada."
    )


def valor_produto(produto: dict) -> str:
    return (
        f"{produto['nome']}\n"
        f"Preço: R$ {produto['preco']:.2f}\n\n"
        f"Dimensões: {produto['medidas']}\n"
        f"Peso: {produto['peso']}"
    )
