import sys
sys.path.insert(0, r"C:\Projetos OPENCODE\Churrasqueiras\churrasqueiras-master")

from google.cloud import compute_v1
from google.oauth2 import service_account

SA_KEY = r"C:\Projetos OPENCODE\Churrasqueiras\churrrasqueiras-9670eb796001.json"
PROJECT = "churrrasqueiras"
ZONE = "us-central1-a"
NAME = "bot-churrasqueira"

STARTUP = """#!/bin/bash
apt-get update
apt-get install -y python3 python3-pip git chromium-browser
pip3 install playwright
playwright install chromium
cd /opt
git clone https://github.com/jmvautomacao-create/churrasqueiras.git
cd /opt/churrasqueiras
pip3 install -r requirements.txt 2>/dev/null || pip3 install playwright google-generativeai pandas openpyxl python-dotenv
echo "Setup concluido. Para rodar: cd /opt/churrasqueiras && python3 main.py"
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

metadata = compute_v1.Metadata()
metadata.items = [
    compute_v1.Items(key="startup-script", value=STARTUP)
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
