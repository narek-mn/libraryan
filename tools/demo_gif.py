"""Render a scripted terminal demo to a GIF (PIL + ffmpeg, no screen recording).

Usage: python3 tools/demo_gif.py tools/demo_script.txt docs/assets/demo.gif

Script format, one directive per line:
  $ <command>        typed at the prompt
  > <output line>    printed instantly; inline colors: {r} {g} {y} {c} {m} {d}im {b}old {/}reset
  # pause <seconds>  hold the current frame
  # clear            clear the screen
  # title <text>     window title
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 960, 540
PAD, BAR = 22, 34
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SIZE, LH = 15, 22
BG, FG, BARBG = "#0d1117", "#e6edf3", "#161b22"
COLORS = {"r": "#ff7b72", "g": "#3fb950", "y": "#d29922", "c": "#79c0ff",
          "m": "#d2a8ff", "d": "#7d8590", "b": FG}
PROMPT = "{g}~/weather-cli{/} {c}${/} "
ROWS = (H - BAR - 2 * PAD) // LH

font = ImageFont.truetype(FONT, SIZE)
bold = ImageFont.truetype(BOLD, SIZE)
CW = font.getlength("M")


def spans(text):
    """Split '{g}ok{/} rest' into [(color, bold, 'ok'), (FG, False, ' rest')]."""
    out, color, is_bold = [], FG, False
    for part in re.split(r"(\{[rgycmdb/]\})", text):
        tag = re.fullmatch(r"\{([rgycmdb/])\}", part)
        if not tag:
            if part:
                out.append((color, is_bold, part))
        elif tag[1] == "/":
            color, is_bold = FG, False
        elif tag[1] == "b":
            is_bold = True
        else:
            color = COLORS[tag[1]]
    return out


def visible(text):
    return re.sub(r"\{[rgycmdb/]\}", "", text)


def cut(text, n):
    """First n visible chars of a markup string, tags kept."""
    out, seen = "", 0
    for part in re.split(r"(\{[rgycmdb/]\})", text):
        if re.fullmatch(r"\{[rgycmdb/]\}", part):
            out += part
        else:
            out += part[: max(0, n - seen)]
            seen += len(part)
    return out


def frame(lines, title, cursor):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, BAR], fill=BARBG)
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        d.ellipse([16 + i * 22, 11, 28 + i * 22, 23], fill=c)
    tw = font.getlength(title)
    d.text(((W - tw) / 2, 9), title, font=font, fill=COLORS["d"])
    shown = lines[-ROWS:]
    for row, line in enumerate(shown):
        x, y = PAD, BAR + PAD + row * LH
        for color, is_bold, txt in spans(line):
            d.text((x, y), txt, font=bold if is_bold else font, fill=color)
            x += CW * len(txt)
        if cursor and row == len(shown) - 1:
            d.rectangle([x + 1, y + 2, x + CW - 1, y + LH - 4], fill=FG)
    return img


def render(script, out):
    frames, lines, title = [], [], "libraryan"

    def snap(seconds, cursor=False):
        frames.append((frame(lines, title, cursor), seconds))

    for raw in open(script, encoding="utf-8").read().splitlines():
        if raw.startswith("$ "):
            cmd = raw[2:]
            lines.append(PROMPT)
            for i in range(0, len(cmd) + 1, 2):
                lines[-1] = PROMPT + cmd[:i]
                snap(0.05, cursor=True)
            lines[-1] = PROMPT + cmd
            snap(0.4)
        elif raw.startswith("> ") or raw == ">":
            lines.append(raw[2:])
            snap(0.06)
        elif raw.startswith("# pause"):
            frames[-1] = (frames[-1][0], frames[-1][1] + float(raw.split()[2]))
        elif raw == "# clear":
            lines = []
        elif raw.startswith("# title "):
            title = raw[8:]
    frames[-1] = (frames[-1][0], frames[-1][1] + 3)

    tmp = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmp, "list.txt"), "w") as f:
            for i, (img, sec) in enumerate(frames):
                p = os.path.join(tmp, f"{i:05}.png")
                img.save(p)
                f.write(f"file '{p}'\nduration {sec:.2f}\n")
            f.write(f"file '{p}'\n")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", os.path.join(tmp, "list.txt"), "-vf",
             "split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];"
             "[b][p]paletteuse=dither=none:diff_mode=rectangle", "-loop", "0", out],
            check=True)
        # A still of the last frame, for places that don't animate.
        frames[-1][0].save(os.path.splitext(out)[0] + ".png")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
