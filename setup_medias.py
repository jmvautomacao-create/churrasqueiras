from pathlib import Path
from config import PRODUTOS, BASE_DIR


def criar_estrutura_medias():
    print("Criando estrutura de diretórios para mídias...\n")

    for produto in PRODUTOS:
        dir_path = BASE_DIR / "media" / "churrasqueiras" / produto["midia_dir"]
        dir_path.mkdir(parents=True, exist_ok=True)

        print(f"[PASTA] {dir_path}/")
        print(f"   - Adicione aqui as fotos (jpg, png) e vídeos (mp4)")
        print(f"   - Produto: {produto['nome']}")
        print()

    print("Estrutura criada com sucesso!")
    print("\nInstruções:")
    print("1. Coloque as fotos (jpg/png) e vídeos (mp4) nas pastas correspondentes")
    print("2. O bot enviará a primeira foto/vídeo que encontrar em cada pasta")
    print("3. Nomeie os arquivos de forma descritiva (ex: foto1.jpg, vídeo.mp4)")


if __name__ == "__main__":
    criar_estrutura_medias()
