import sys
sys.path.insert(0, r"C:\Projetos OPENCODE\Churrasqueiras\churrasqueiras-master")

from google.cloud import compute_v1
from google.oauth2 import service_account

SA_KEY = r"C:\Projetos OPENCODE\Churrasqueiras\churrrasqueiras-9670eb796001.json"
SSH_PUB = r"C:\Users\Usuario\.ssh\gcp_vm_key.pub"
PROJECT = "churrrasqueiras"
ZONE = "us-central1-a"
NAME = "bot-churrasqueira"

STARTUP = """#!/bin/bash
set -e

apt-get update
apt-get install -y python3 python3-pip git

pip3 install playwright
PLAYWRIGHT_BROWSERS_PATH=/opt/chromium playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=/opt/chromIUM python3 -m playwright install-deps chromium

cd /opt
git clone https://github.com/jmvautomacao-create/churrasqueiras.git
cd /opt/churrasqueiras

pip3 install pandas openpyxl python-dotenv openai stripe google-genai 2>&1

# config.py is gitignored, create from scratch
cat > config.py << 'CONFIGEOF'
from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
PASTA_SOLICITACOES = BASE_DIR / "solicitacoes"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")

SEU_NUMERO = "555199999999"

TRANSPORTADORAS = [
    {"nome": "Transportadora A", "numero": "555199999991"},
    {"nome": "Transportadora B", "numero": "555199999992"},
]

PRODUTOS = [
    {"id": 1, "nome": "Churrasqueira Tonel 6 espetos",       "descricao": "Churrasqueira tonel com 6 espetos",         "preco": 1249.90, "medidas": "80x60x100cm", "peso": "18 kg", "midia_dir": "churrasqueira_tonel"},
    {"id": 2, "nome": "Churrasqueira Tonel 11 Espetos",      "descricao": "Churrasqueira tonel com 11 espetos",        "preco": 1949.90, "medidas": "80x60x100cm", "peso": "22 kg", "midia_dir": "churrasqueira_tonel_11"},
    {"id": 3, "nome": "Churrasqueira Tonel Costel\u00e3o",        "descricao": "Churrasqueira tonel para costel\u00e3o",         "preco": 1499.90, "medidas": "80x60x100cm", "peso": "26 kg", "midia_dir": "churrasqueira_costelao"},
    {"id": 4, "nome": "Churrasqueira Combo Tonel",           "descricao": "Churrasqueira combo tonel completa",        "preco": 2349.90, "medidas": "80x60x100cm", "peso": "30 kg", "midia_dir": "churrasqueira_combo"},
    {"id": 5, "nome": "Churrasqueira Galvanizada 6 Espetos", "descricao": "Churrasqueira galvanizada com 6 espetos",   "preco": 1949.90, "medidas": "80x60x100cm", "peso": "25 kg", "midia_dir": "churrasqueira_galvanizada"},
    {"id": 6, "nome": "Churrasqueira Galvanizada 11 Espetos","descricao": "Churrasqueira galvanizada com 11 espetos",  "preco": 2649.90, "medidas": "80x60x100cm", "peso": "28 kg", "midia_dir": "churrasqueira_galvanizada_11"},
    {"id": 7, "nome": "Churrasqueira Galvanizada Costel\u00e3o",  "descricao": "Churrasqueira galvanizada para costel\u00e3o",   "preco": 2299.90, "medidas": "80x60x100cm", "peso": "31 kg", "midia_dir": "churrasqueira_galvanizada_costelao"},
    {"id": 8, "nome": "Churrasqueira Galvanizada Combo",     "descricao": "Churrasqueira galvanizada combo completa",  "preco": 2990.90, "medidas": "80x60x100cm", "peso": "35 kg", "midia_dir": "churrasqueira_galvanizada_combo"},
    {"id": 9, "nome": "Churrasqueira Port\u00e1til",              "descricao": "Churrasqueira port\u00e1til dobr\u00e1vel",           "preco": 359.90,  "medidas": "50x28x42cm", "peso": "6 kg",  "midia_dir": "churrasqueira_portatil"},
]
CONFIGEOF

cat > /etc/systemd/system/bot-churrasqueira.service << 'SERVICEEOF'
[Unit]
Description=WhatsApp Bot - Churrasqueiras
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/churrasqueiras
ExecStart=/usr/bin/python3 /opt/churrasqueiras/main.py
Restart=always
RestartSec=10
Environment=DISPLAY=:0 PLAYWRIGHT_BROWSERS_PATH=/opt/chromium

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable bot-churrasqueira

echo "Setup concluido com sucesso!"
echo ""
echo "NEXT STEP: SSH into VM and create .env:"
echo "  ssh usuario@(curl -s http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip -H 'Metadata-Flavor: Google')"
echo "  sudo tee /opt/churrasqueiras/.env << 'EOF'"
echo "  GROQ_API_KEY=\"sua_groq_key\""
echo "  STRIPE_SECRET_KEY=\"sua_stripe_key\""
echo "  EOF"
echo "  sudo chmod 600 /opt/churrasqueiras/.env"
echo "  sudo systemctl start bot-churrasqueira"
echo ""
echo "Then scan QR Code manually: cd /opt/churrasqueiras && sudo python3 main.py"
"""

creds = service_account.Credentials.from_service_account_file(SA_KEY)

instance = compute_v1.Instance()
instance.name = NAME
instance.machine_type = f"zones/{ZONE}/machineTypes/e2-micro"

boot = compute_v1.AttachedDisk()
boot.boot = True
boot.initialize_params = compute_v1.AttachedDiskInitializeParams()
boot.initialize_params.source_image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
boot.initialize_params.disk_size_gb = 20
boot.initialize_params.disk_type = f"zones/{ZONE}/diskTypes/pd-standard"
instance.disks = [boot]

network = compute_v1.NetworkInterface()
network.name = "global/networks/default"
network.access_configs = [compute_v1.AccessConfig()]  # gives external IP
instance.network_interfaces = [network]

with open(SSH_PUB) as f:
    ssh_key = f.read().strip()

metadata = compute_v1.Metadata()
metadata.items = [
    compute_v1.Items(key="startup-script", value=STARTUP),
    compute_v1.Items(key="ssh-keys", value=f"usuario:{ssh_key}"),
]
instance.metadata = metadata

sa = compute_v1.ServiceAccount()
sa.email = "sa-churrasqueiras@churrrasqueiras.iam.gserviceaccount.com"
sa.scopes = ["https://www.googleapis.com/auth/cloud-platform"]
instance.service_accounts = [sa]

client = compute_v1.InstancesClient(credentials=creds)
print(f"Criando VM {NAME}...")
op = client.insert(project=PROJECT, zone=ZONE, instance_resource=instance)
print(f"Operacao: {op.name}")
print("A VM esta sendo criada (2-3 minutos).")
print(f"Acesse pelo console: https://console.cloud.google.com/compute/instancesDetail/zones/{ZONE}/instances/{NAME}?project={PROJECT}")
