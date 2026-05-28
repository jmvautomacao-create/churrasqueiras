from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from config import PRODUTOS, BASE_DIR

FONT_PATH = "C:\\Windows\\Fonts\\arial.ttf"
FONT_BOLD_PATH = "C:\\Windows\\Fonts\\arialbd.ttf"

LARGURA = 800
ALTURA = 600
COR_FUNDO = (30, 30, 30)
COR_TITULO = (255, 200, 50)
COR_TEXTO = (255, 255, 255)
COR_PRECO = (50, 255, 100)
COR_DESTAQUE = (255, 100, 50)


def gerar_folder(produto: dict):
    saida = BASE_DIR / "media" / "churrasqueiras" / produto["midia_dir"] / "folder.jpg"

    img = Image.new("RGB", (LARGURA, ALTURA), COR_FUNDO)
    draw = ImageDraw.Draw(img)

    try:
        font_titulo = ImageFont.truetype(FONT_BOLD_PATH, 36)
        font_preco = ImageFont.truetype(FONT_BOLD_PATH, 32)
        font_texto = ImageFont.truetype(FONT_PATH, 22)
        font_rodape = ImageFont.truetype(FONT_PATH, 18)
    except:
        font_titulo = ImageFont.load_default()
        font_preco = font_titulo
        font_texto = font_titulo
        font_rodape = font_titulo

    y = 40
    draw.text((40, y), produto["nome"], fill=COR_TITULO, font=font_titulo)
    y += 60

    draw.text((40, y), f"Preço: R$ {produto['preco']:.2f}", fill=COR_PRECO, font=font_preco)
    y += 55

    draw.line([(40, y), (LARGURA - 40, y)], fill=(80, 80, 80), width=2)
    y += 30

    desc = produto["descricao"]
    palavras = desc.split()
    linha = ""
    for p in palavras:
        teste = linha + " " + p if linha else p
        if len(teste) > 50:
            draw.text((40, y), linha, fill=COR_TEXTO, font=font_texto)
            y += 35
            linha = p
        else:
            linha = teste
    if linha:
        draw.text((40, y), linha, fill=COR_TEXTO, font=font_texto)
        y += 45

    draw.text((40, y), f"Dimensoes: {produto['medidas']}", fill=COR_TEXTO, font=font_texto)
    y += 35
    draw.text((40, y), f"Peso: {produto['peso']}", fill=COR_TEXTO, font=font_texto)
    y += 60

    draw.line([(40, y), (LARGURA - 40, y)], fill=COR_DESTAQUE, width=3)
    y += 25

    msg = "Solicite ja o seu orcamento pelo WhatsApp!"
    bbox = draw.textbbox((0, 0), msg, font=font_rodape)
    tw = bbox[2] - bbox[0]
    draw.text(((LARGURA - tw) // 2, y), msg, fill=COR_DESTAQUE, font=font_rodape)

    img.save(saida, quality=90)
    print(f"Criado: {saida}")


if __name__ == "__main__":
    for p in PRODUTOS:
        gerar_folder(p)
    print("\nTodos os folders foram gerados!")
