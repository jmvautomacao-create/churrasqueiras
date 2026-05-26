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
    linhas = ["CATALOGO DE CHURRASQUEIRAS\n"]
    for p in PRODUTOS:
        linhas.append(f"{p['id']}. {p['nome']}")
        linhas.append(f"   {p['descricao']}")
        linhas.append("")
    return "\n".join(linhas)


def detalhar(produto_id: int) -> str:
    p = produto_por_id(produto_id)
    if not p:
        return "Produto nao encontrado."
    return (
        f"{p['nome']}\n\n"
        f"{p['descricao']}\n\n"
        f"Preco: R$ {p['preco']:.2f}\n"
        f"Dimensoes: {p['medidas']}\n"
        f"Peso: {p['peso']}\n"
    )


def menu_interativo() -> str:
    linhas = [
        "Ola! Bem-vindo a JMV Churrasqueiras!",
        "",
        "Escolha um modelo digitando o NUMERO correspondente:",
        "",
    ]
    for p in PRODUTOS:
        linhas.append(f"  [{p['id']}] {p['nome']}")
    linhas.append("")
    linhas.append("Digite o numero do produto para ver as opcoes!")
    return "\n".join(linhas)


def submenu_produto(produto: dict) -> str:
    return (
        f"Voce escolheu: {produto['nome']}\n"
        f"{produto['descricao']}\n\n"
        f"Escolha uma opcao:\n"
        f"  [1] Folder - Ver folder do produto\n"
        f"  [2] Valor - Consultar preco\n"
        f"  [3] Foto - Enviar foto\n"
        f"  [4] Video - Enviar video\n"
        f"  [5] Frete - Solicitar cotacao de frete\n\n"
        f"Digite o numero da opcao desejada."
    )


def valor_produto(produto: dict) -> str:
    return (
        f"{produto['nome']}\n"
        f"Preco: R$ {produto['preco']:.2f}\n\n"
        f"Dimensoes: {produto['medidas']}\n"
        f"Peso: {produto['peso']}"
    )
