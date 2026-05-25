import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "database" / "agente.db"


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            telefone TEXT NOT NULL UNIQUE,
            endereco TEXT,
            cpf TEXT,
            cidade TEXT,
            estado TEXT,
            cep TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conversas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            status TEXT DEFAULT 'ativo',
            produto_interesse_id INTEGER,
            etapa TEXT DEFAULT 'saudacao',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS cotacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversa_id INTEGER NOT NULL,
            transportadora TEXT NOT NULL,
            valor_frete REAL,
            prazo TEXT,
            status TEXT DEFAULT 'solicitada',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversa_id) REFERENCES conversas(id)
        );

        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversa_id INTEGER NOT NULL,
            origem TEXT NOT NULL,
            conteudo TEXT NOT NULL,
            tipo TEXT DEFAULT 'texto',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversa_id) REFERENCES conversas(id)
        );

        CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversa_id INTEGER NOT NULL,
            cliente_id INTEGER NOT NULL,
            produto_id INTEGER NOT NULL,
            valor_produto REAL NOT NULL,
            valor_frete REAL,
            valor_total REAL,
            status TEXT DEFAULT 'pendente',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversa_id) REFERENCES conversas(id),
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        );
    """)

    conn.commit()
    conn.close()


def cliente_por_telefone(telefone):
    conn = get_connection()
    cliente = conn.execute(
        "SELECT * FROM clientes WHERE telefone = ?", (telefone,)
    ).fetchone()
    conn.close()
    return dict(cliente) if cliente else None


def criar_cliente(telefone, nome=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO clientes (telefone, nome) VALUES (?, ?)",
        (telefone, nome),
    )
    conn.commit()
    cliente_id = cursor.lastrowid or cliente_por_telefone(telefone)["id"]
    conn.close()
    return cliente_id


def atualizar_cliente(cliente_id, **kwargs):
    campos = []
    valores = []
    for chave, valor in kwargs.items():
        if valor is not None:
            campos.append(f"{chave} = ?")
            valores.append(valor)
    if not campos:
        return
    valores.append(cliente_id)
    conn = get_connection()
    conn.execute(
        f"UPDATE clientes SET {', '.join(campos)} WHERE id = ?", valores
    )
    conn.commit()
    conn.close()


def criar_conversa(cliente_id, produto_id=None):
    conn = get_connection()
    cursor = conn.cursor()

    ativa = conn.execute(
        "SELECT * FROM conversas WHERE cliente_id = ? AND status = 'ativo'",
        (cliente_id,),
    ).fetchone()

    if ativa:
        conn.close()
        return ativa["id"]

    cursor.execute(
        "INSERT INTO conversas (cliente_id, produto_interesse_id) VALUES (?, ?)",
        (cliente_id, produto_id),
    )
    conn.commit()
    conv_id = cursor.lastrowid
    conn.close()
    return conv_id


def salvar_mensagem(conversa_id, origem, conteudo, tipo="texto"):
    conn = get_connection()
    conn.execute(
        "INSERT INTO mensagens (conversa_id, origem, conteudo, tipo) VALUES (?, ?, ?, ?)",
        (conversa_id, origem, conteudo, tipo),
    )
    conn.execute(
        "UPDATE conversas SET atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (conversa_id,),
    )
    conn.commit()
    conn.close()


def atualizar_etapa_conversa(conversa_id, etapa):
    conn = get_connection()
    conn.execute(
        "UPDATE conversas SET etapa = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (etapa, conversa_id),
    )
    conn.commit()
    conn.close()


def atualizar_produto_interesse(conversa_id, produto_id):
    conn = get_connection()
    conn.execute(
        "UPDATE conversas SET produto_interesse_id = ? WHERE id = ?",
        (produto_id, conversa_id),
    )
    conn.commit()
    conn.close()


def criar_cotacao(conversa_id, transportadora):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO cotacoes (conversa_id, transportadora) VALUES (?, ?)",
        (conversa_id, transportadora),
    )
    conn.commit()
    cot_id = cursor.lastrowid
    conn.close()
    return cot_id


def atualizar_cotacao(cotacao_id, valor_frete=None, prazo=None, status=None):
    campos = []
    valores = []
    if valor_frete is not None:
        campos.append("valor_frete = ?")
        valores.append(valor_frete)
    if prazo is not None:
        campos.append("prazo = ?")
        valores.append(prazo)
    if status is not None:
        campos.append("status = ?")
        valores.append(status)
    if not campos:
        return
    valores.append(cotacao_id)
    conn = get_connection()
    conn.execute(
        f"UPDATE cotacoes SET {', '.join(campos)} WHERE id = ?", valores
    )
    conn.commit()
    conn.close()


def criar_venda(conversa_id, cliente_id, produto_id, valor_produto, valor_frete=None):
    conn = get_connection()
    cursor = conn.cursor()
    valor_total = valor_produto + (valor_frete or 0)
    cursor.execute(
        """INSERT INTO vendas
           (conversa_id, cliente_id, produto_id, valor_produto, valor_frete, valor_total)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (conversa_id, cliente_id, produto_id, valor_produto, valor_frete, valor_total),
    )
    conn.commit()
    venda_id = cursor.lastrowid
    conn.close()
    return venda_id


def get_historico_conversa(conversa_id, limite=20):
    conn = get_connection()
    msgs = conn.execute(
        """SELECT origem, conteudo, tipo, criado_em
           FROM mensagens WHERE conversa_id = ?
           ORDER BY criado_em ASC LIMIT ?""",
        (conversa_id, limite),
    ).fetchall()
    conn.close()
    return [dict(m) for m in msgs]


def get_conversa_ativa(telefone):
    conn = get_connection()
    row = conn.execute(
        """SELECT c.id as conversa_id, cl.id as cliente_id, cl.nome, cl.telefone,
                  cl.endereco, cl.cpf, c.etapa, c.produto_interesse_id
           FROM conversas c
           JOIN clientes cl ON cl.id = c.cliente_id
           WHERE cl.telefone = ? AND c.status = 'ativo'
           ORDER BY c.atualizado_em DESC LIMIT 1""",
        (telefone,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None
