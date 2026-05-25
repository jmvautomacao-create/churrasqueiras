# Agente de Vendas - Churrasqueiras

Bot inteligente para WhatsApp Web que vende churrasqueiras usando IA (Google Gemini).

## Funcionalidades

- Atendimento automatizado via WhatsApp Web
- IA conversacional com Google Gemini
- Catálogo de produtos com fotos e vídeos
- Coleta de dados do cliente (nome, CPF, endereço)
- Solicitação de frete a transportadoras via WhatsApp
- Notificação de venda ao vendedor
- Banco de dados SQLite com histórico completo

## Requisitos

- Python 3.10+
- Google Chrome instalado
- Conta Google com API Gemini habilitada

## Instalação

```bash
cd agente_churrasqueira

# Instalar dependências
pip install -r requirements.txt

# Instalar Playwright browsers
playwright install chromium
```

## Configuração

1. Edite `config.py` e adicione sua chave da API Gemini:
   ```python
   GEMINI_API_KEY = "sua_chave_aqui"
   ```
   Obtenha sua chave em: https://aistudio.google.com/apikey

2. Configure seu número e das transportadoras em `config.py`:
   ```python
   SEU_NUMERO = "55DDNÚMERO"
   TRANSPORTADORAS = [
       {"nome": "Transportadora X", "numero": "55DDNÚMERO"},
   ]
   ```

3. Edite os produtos em `config.py` conforme seu catálogo.

## Mídias (Fotos/Vídeos)

Execute para criar as pastas:
```bash
python setup_medias.py
```

Depois cole as fotos (jpg/png) e vídeos (mp4) nas pastas criadas em `media/churrasqueiras/`.

## Como usar

```bash
python main.py
```

1. Escaneie o QR Code do WhatsApp Web
2. O bot começa a ouvir mensagens automaticamente
3. Quando um cliente enviar mensagem, o IA responde

## Fluxo de Vendas

1. Cliente envia mensagem → Bot apresenta catálogo
2. Cliente escolhe produto → Bot envia foto e detalhes
3. Cliente confirma interesse → Bot coleta dados (CPF, endereço)
4. Bot solicita frete às transportadoras via WhatsApp
5. Transportadora responde → Bot repassa valor ao cliente
6. Cliente confirma → Bot registra venda e notifica vendedor
