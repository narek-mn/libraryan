"""Generate the logo, README banner and GitHub social preview into docs/assets/.

Usage: python3 tools/brand.py
"""
from PIL import Image, ImageDraw, ImageFont

OUT = "docs/assets/"
LATO = "/usr/share/fonts/truetype/lato/Lato-"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BG, CARD, FG, DIM = "#0d1117", "#161b22", "#e6edf3", "#8b949e"
BLUE, PURPLE, GREEN, GOLD = "#79c0ff", "#d2a8ff", "#3fb950", "#e3b341"

# Logo on a 128 grid: three books and a green "checked" badge.
BOOKS = [  # x, y, w, h, color
    (24, 34, 18, 66, BLUE),
    (46, 24, 22, 76, PURPLE),
    (72, 40, 16, 60, GOLD),
    (92, 30, 14, 70, GREEN),
]
BADGE = (96, 92, 20)  # cx, cy, r


def logo_svg(size=128):
    books = "".join(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="{c}"/>'
        f'<rect x="{x + 4}" y="{y + 10}" width="{w - 8}" height="3" rx="1.5" fill="{BG}" opacity=".35"/>'
        for x, y, w, h, c in BOOKS)
    cx, cy, r = BADGE
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 128 128">'
            f'<rect width="128" height="128" rx="28" fill="{BG}"/>'
            f'{books}'
            f'<rect x="18" y="100" width="96" height="5" rx="2.5" fill="{DIM}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{GREEN}" stroke="{BG}" stroke-width="5"/>'
            f'<path d="M{cx - 9} {cy} l6 6 l12 -12" fill="none" stroke="{BG}" stroke-width="5" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg>\n')


def draw_logo(d, ox, oy, s):
    """Same logo as logo_svg, drawn with PIL at origin (ox, oy), scale s (px per unit)."""
    P = lambda x, y: (ox + x * s, oy + y * s)
    d.rounded_rectangle([*P(0, 0), *P(128, 128)], radius=28 * s, fill=BG)
    for x, y, w, h, c in BOOKS:
        d.rounded_rectangle([*P(x, y), *P(x + w, y + h)], radius=3 * s, fill=c)
        d.rounded_rectangle([*P(x + 4, y + 10), *P(x + w - 4, y + 13)], radius=1.5 * s, fill="#5c6b7a")
    d.rounded_rectangle([*P(18, 100), *P(114, 105)], radius=2.5 * s, fill=DIM)
    cx, cy, r = BADGE
    d.ellipse([*P(cx - r - 2.5, cy - r - 2.5), *P(cx + r + 2.5, cy + r + 2.5)], fill=BG)
    d.ellipse([*P(cx - r, cy - r), *P(cx + r, cy + r)], fill=GREEN)
    d.line([P(cx - 9, cy), P(cx - 3, cy + 6), P(cx + 9, cy - 6)], fill=BG, width=round(5 * s), joint="curve")


def banner_svg():
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
    logo = logo_svg().replace('<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">',
                              '<svg x="48" y="46" width="148" height="148" viewBox="0 0 128 128">')
    chips, x = "", 236
    for text, color in (("single writer", BLUE), ("reviewed before commit", PURPLE),
                        ("no fact lost", GOLD), ("$0 quiet nights", GREEN)):
        w = 15 + len(text) * 8.6
        chips += (f'<rect x="{x}" y="150" width="{w:.0f}" height="30" rx="15" fill="none" stroke="{color}" stroke-opacity=".6"/>'
                  f'<text x="{x + w / 2:.0f}" y="170" fill="{color}" font-size="15" text-anchor="middle" font-family="{font}">{text}</text>')
        x += w + 10
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="240" viewBox="0 0 1200 240">'
            f'<rect width="1200" height="240" rx="18" fill="{BG}"/>'
            f'<rect x="1" y="1" width="1198" height="238" rx="17" fill="none" stroke="#30363d"/>'
            f'{logo}'
            f'<text x="234" y="104" fill="{FG}" font-size="58" font-weight="700" font-family="{font}">Libraryan</text>'
            f'<text x="236" y="136" fill="{DIM}" font-size="21" font-family="{font}">'
            f'The only agent allowed to touch your docs. Every other agent files a request.</text>'
            f'{chips}</svg>\n')


def social_png():
    img = Image.new("RGB", (1280, 640), BG)
    d = ImageDraw.Draw(img)
    for i in range(0, 1280, 32):  # faint grid
        d.line([(i, 0), (i, 640)], fill="#11161d")
    for j in range(0, 640, 32):
        d.line([(0, j), (1280, j)], fill="#11161d")
    draw_logo(d, 88, 96, 1.5)
    d.text((300, 100), "Libraryan", font=ImageFont.truetype(LATO + "Black.ttf", 96), fill=FG)
    d.text((304, 222), "The only agent allowed to touch your docs.", font=ImageFont.truetype(LATO + "Semibold.ttf", 36), fill=FG)
    d.text((304, 270), "Every other agent files a request. Plain Markdown, AGENTS.md, any agent.",
           font=ImageFont.truetype(LATO + "Regular.ttf", 23), fill=DIM)
    # terminal card
    d.rounded_rectangle([88, 360, 1192, 560], radius=16, fill=CARD, outline="#30363d", width=2)
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        d.ellipse([112 + i * 24, 382, 126 + i * 24, 396], fill=c)
    mono = ImageFont.truetype(MONO, 26)
    rows = [[("$ ", BLUE), ("pipx install libraryan", FG)],
            [("$ ", BLUE), ("libraryan init", FG)],
            [("✓ ", GREEN), ("docs(libraryan): set up knowledge base", FG), ("   reviewed · ledger ok", DIM)]]
    for r, row in enumerate(rows):
        x = 120
        for text, color in row:
            d.text((x, 420 + r * 40), text, font=mono, fill=color)
            x += mono.getlength(text)
    d.text((88, 588), "github.com/narek-mn/libraryan", font=ImageFont.truetype(LATO + "Semibold.ttf", 24), fill=DIM)
    d.text((1192, 588), "MIT · pipx · Linux & macOS", font=ImageFont.truetype(LATO + "Regular.ttf", 24), fill=DIM, anchor="ra")
    img.save(OUT + "social-preview.png", optimize=True)


if __name__ == "__main__":
    open(OUT + "logo.svg", "w").write(logo_svg())
    open(OUT + "banner.svg", "w").write(banner_svg())
    social_png()
