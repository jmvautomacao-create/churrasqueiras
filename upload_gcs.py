import os, json, subprocess, sys
from pathlib import Path

BUCKET_NAME = "churrasqueiras-backup"
PROJECT_ID = "Churrasqueiras"
ZIP_PATH = os.path.expanduser(r"~\Desktop\churrasqueiras-backup.zip")

print("=" * 60)
print(" BACKUP - Google Cloud Storage")
print("=" * 60)

# Verifica se o zip existe
if not os.path.exists(ZIP_PATH):
    print(f"\n[!] ZIP não encontrado: {ZIP_PATH}")
    print("Execute novamente após criar o backup.")
    sys.exit(1)

# Pede caminho da chave JSON
print(f"""
Passo 1 - Criar chave da Service Account:
  1. Acesse https://console.cloud.google.com/apis/credentials
  2. Projeto: {PROJECT_ID}
  3. Clique em "CRIAR CREDENCIAIS" > "Service Account"
  4. Nome: sa-churrasqueiras-backup, clique em CRIAR E CONCLUIR
  5. Na lista, clique no e-mail da service account criada
  6. Aba "Chaves" > "Adicionar Chave" > "Criar Nova Chave"
  7. Tipo JSON > CRIAR (download automático)
""")

key_path = input("Cole o caminho da chave .json baixada: ").strip().strip('"').strip("'")
key_path = os.path.expanduser(key_path)

if not os.path.exists(key_path):
    print(f"[!] Arquivo não encontrado: {key_path}")
    sys.exit(1)

print("\nConectando ao Google Cloud Storage...")

from google.cloud import storage
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file(key_path)
client = storage.Client(project=PROJECT_ID, credentials=creds)

# Cria bucket se não existir
try:
    bucket = client.lookup_bucket(BUCKET_NAME)
    if not bucket:
        print(f"Criando bucket gs://{BUCKET_NAME}...")
        bucket = client.create_bucket(BUCKET_NAME, location="us-central1")
        print("  Bucket criado!")
    else:
        print(f"Bucket gs://{BUCKET_NAME} já existe.")
except Exception as e:
    print(f"[!] Erro ao acessar bucket: {e}")
    sys.exit(1)

# Upload
blob_name = f"churrasqueiras-backup-{Path(ZIP_PATH).stem}.zip"
blob = bucket.blob(blob_name)
print(f"\nEnviando {blob_name} ({os.path.getsize(ZIP_PATH)/1024/1024:.0f} MB)...")
blob.upload_from_filename(ZIP_PATH)
print(f"\nOK! Arquivo em: gs://{BUCKET_NAME}/{blob_name}")
print("Você pode ver no Console: https://console.cloud.google.com/storage/browser/" + BUCKET_NAME)
