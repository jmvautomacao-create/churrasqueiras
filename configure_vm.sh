#!/bin/bash
set -e

BOT_DIR="/opt/churrasqueiras"

echo "=============================================="
echo "  CONFIGURACAO DO BOT CHURRASQUEIRA"
echo "=============================================="
echo ""

# Verifica se o repositorio existe
if [ ! -d "$BOT_DIR" ]; then
    echo "[!] Repositorio nao encontrado em $BOT_DIR"
    echo "    Aguardando clone do startup-script..."
    for i in $(seq 1 30); do
        if [ -d "$BOT_DIR" ]; then
            echo "  -> OK"
            break
        fi
        sleep 5
    done
    if [ ! -d "$BOT_DIR" ]; then
        echo "[!] Repositorio nao disponivel. Clonando..."
        cd /opt
        git clone https://github.com/jmvautomacao-create/churrasqueiras.git
    fi
fi

cd "$BOT_DIR"

# Instala dependencias Python
echo ""
echo "[1/5] Instalando dependencias Python..."
pip3 install -r requirements.txt 2>/dev/null || pip3 install playwright google-generativeai pandas openpyxl python-dotenv
echo "  -> OK"

# Instala Playwright Chromium
echo ""
echo "[2/5] Instalando Chromium (Playwright)..."
playwright install chromium 2>/dev/null
echo "  -> OK"

# Chaves da API
echo ""
echo "[3/5] Configurando chaves de API (.env)"
echo ""

if [ -f .env ]; then
    echo "  Arquivo .env ja existe. Deseja sobrescrever? (s/N)"
    read -r resp
    if [ "$resp" != "s" ] && [ "$resp" != "S" ]; then
        echo "  -> Mantendo .env existente"
    else
        rm .env
    fi
fi

if [ ! -f .env ]; then
    echo "  Digite sua GROQ_API_KEY (ex: gsk_...):"
    read -r groq_key
    echo "  Digite sua STRIPE_SECRET_KEY (ex: sk_test_...):"
    read -r stripe_key
    cat > .env << EOF
GROQ_API_KEY="$groq_key"
STRIPE_SECRET_KEY="$stripe_key"
EOF
    chmod 600 .env
    echo "  -> .env criado"
fi

# Numero do vendedor
echo ""
echo "[4/5] Configurando numero do vendedor"
echo ""

SEU_NUMERO_ATUAL=$(grep -oP 'SEU_NUMERO\s*=\s*"\K[^"]+' config.py)
echo "  Numero atual no config.py: $SEU_NUMERO_ATUAL"
echo "  Digite o novo numero (com DDI+DDD, ex: 555195036289) ou Enter para manter:"
read -r novo_numero
if [ -n "$novo_numero" ]; then
    sed -i "s/SEU_NUMERO = \"[^\"]*\"/SEU_NUMERO = \"$novo_numero\"/" config.py
    echo "  -> Numero atualizado"
fi

# Criar service systemd para rodar 24h
echo ""
echo "[5/5] Configurando servico para rodar 24h"
echo ""

sudo tee /etc/systemd/system/bot-churrasqueira.service > /dev/null << EOF
[Unit]
Description=WhatsApp Bot - Churrasqueiras
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$BOT_DIR
ExecStart=/usr/bin/python3 $BOT_DIR/main.py
Restart=always
RestartSec=10
Environment=DISPLAY=:0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable bot-churrasqueira.service

echo ""
echo "=============================================="
echo "  CONFIGURACAO CONCLUIDA!"
echo "=============================================="
echo ""
echo "  Para iniciar o bot agora:"
echo "    sudo systemctl start bot-churrasqueira"
echo ""
echo "  Para ver os logs:"
echo "    sudo journalctl -u bot-churrasqueira -f"
echo ""
echo "  Para parar:"
echo "    sudo systemctl stop bot-churrasqueira"
echo ""
echo "  Para escanear o QR Code (necessario na 1a vez):"
echo "    cd $BOT_DIR && python3 main.py"
echo "    (escaneie o QR com o celular, depois Ctrl+C"
echo "     e rode: sudo systemctl start bot-churrasqueira)"
echo ""
echo "  IMPORTANTE: Antes do 1o QR Code, va no console GCP"
echo "  e pare a VM. Depois inicie de novo para escanear."
echo ""

# Pergunta se quer rodar agora
echo "Deseja rodar o bot agora para escanear o QR Code? (s/N)"
read -r rodar_agora
if [ "$rodar_agora" = "s" ] || [ "$rodar_agora" = "S" ]; then
    echo "  Escaneie o QR Code com o celular..."
    echo "  Depois de logado, pressione Ctrl+C e rode:"
    echo "    sudo systemctl start bot-churrasqueira"
    echo ""
    python3 main.py
fi
