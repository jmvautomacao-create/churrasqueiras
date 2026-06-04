import os, sys
from pathlib import Path

SA_KEY = r"C:\Projetos OPENCODE\Churrasqueiras\churrrasqueiras-9670eb796001.json"
BUCKET_NAME = "churrasqueiras-backup"
PROJECT_ID = "churrrasqueiras"
ZIP_PATH = os.path.expanduser(r"~\Desktop\churrasqueiras-backup.zip")

print("=" * 60)
print(" BACKUP - Google Cloud Storage")
print("=" * 60)

if not os.path.exists(ZIP_PATH):
    print(f"\n[!] ZIP nao encontrado: {ZIP_PATH}")
    print("Execute novamente apos criar o backup.")
    sys.exit(1)

if not os.path.exists(SA_KEY):
    print(f"\n[!] Chave Service Account nao encontrada: {SA_KEY}")
    sys.exit(1)

print("\nConectando ao Google Cloud Storage...")

from google.cloud import storage
from google.oauth2 import service_account

creds = service_account.Credentials.from_service_account_file(SA_KEY)
client = storage.Client(project=PROJECT_ID, credentials=creds)
bucket = client.bucket(BUCKET_NAME)

blob_name = "churrasqueiras-backup.zip"
blob = bucket.blob(blob_name)
size_mb = os.path.getsize(ZIP_PATH) / 1024 / 1024
print(f"\nEnviando {blob_name} ({size_mb:.0f} MB)...")
blob.upload_from_filename(ZIP_PATH)
print(f"\nOK! Arquivo em: gs://{BUCKET_NAME}/{blob_name}")
print("Console: https://console.cloud.google.com/storage/browser/churrasqueiras-backup")
