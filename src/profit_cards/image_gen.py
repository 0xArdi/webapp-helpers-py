from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import io

# ---------- Assets ----------

class Assets:
    def __init__(self, pnl_profit, pnl_loss, font_regular, font_semibold, font_bold, font_price_path):
        self.pnl_profit = Image.open(pnl_profit).convert("RGBA")
        self.pnl_loss = Image.open(pnl_loss).convert("RGBA")
        self.font_regular = font_regular
        self.font_semibold = font_semibold
        self.font_bold = font_bold
        self.font_price = font_price_path      # ✅ new attribute


p = Path(Path(__file__).parent, "assets")

assets = Assets(
    p / "pnlProfit.png",
    p / "pnlLoss.png",
    p / "SchibstedGrotesk-Regular.ttf",
    p / "SchibstedGrotesk-SemiBold.ttf",
    p / "SchibstedGrotesk-Bold.ttf",
    p / "DejaVuSansCondensed-Bold.ttf",
)

@dataclass
class Agent:
    name: str
    symbol: str
    profilePicture: str  # <-- URL now


# ---------- Utility ----------

def truncate(s: str, max_len: int = 18) -> str:
    return s[: max_len - 1] + "…" if len(s) > max_len else s


def format_percent(percent: float) -> str:
    if percent == 0:
        return "0%"
    sign = "+" if percent > 0 else "-"
    val = abs(percent) * 100
    s = f"{val:,.1f}".rstrip("0").rstrip(".")
    return f"{sign}{s}%"


def fit_font_size(draw, text, base_size, max_width, font_path):
    size = base_size
    while size > 1:
        font = ImageFont.truetype(font_path, size=size)
        if draw.textlength(text, font=font) <= max_width:
            return size
        size -= 1
    return 1


def rounded_avatar_from_url(url: str, size: int, radius: int = 15) -> Image.Image:
    """
    Downloads an image, scales/crops it to fill a square (object-fit: cover),
    and applies rounded corners.
    """
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

    # ✅ apply object-fit cover BEFORE any forced resize
    img = object_fit_cover(img, size, size)

    # create a rounded mask
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)

    img.putalpha(mask)
    return img



def draw_glow_text(
    base: Image.Image,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    glow_color: tuple[int, int, int],
    anchor: str = "rs",
):
    """
    Softer, wider glow:
      - Higher blur radius
      - Lower alpha for a more subtle, elegant neon effect
    """
    W, H = base.size
    x, y = xy

    img = base.convert("RGBA")

    # Wider but softer halo
    for i in range(3, 0, -1):   # only 3 layers for subtle effect
        glow_layer = Image.new("RGBA", (W, H), (glow_color[0], glow_color[1], glow_color[2], 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        glow_draw.text((x, y), text, font=font, fill=(*glow_color, 180), anchor=anchor)
        # higher blur radius per layer, but lower opacity overall
        blurred = glow_layer.filter(ImageFilter.GaussianBlur(radius=i * 10))
        img = Image.alpha_composite(img, blurred)

    # Final crisp white text on top
    draw = ImageDraw.Draw(img)
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255), anchor=anchor)

    base.paste(img, (0, 0))


def object_fit_cover(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """
    Replicates CSS object-fit: cover.
    Scales image to fill target box while preserving aspect ratio,
    cropping the excess evenly from the center.
    """
    src_w, src_h = img.size
    target_ratio = target_width / target_height
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # Image is wider: match height, crop sides
        new_height = target_height
        new_width = int(new_height * src_ratio)
    else:
        # Image is taller: match width, crop top/bottom
        new_width = target_width
        new_height = int(new_width / src_ratio)

    resized = img.resize((new_width, new_height), Image.LANCZOS)

    left = (new_width - target_width) // 2
    top = (new_height - target_height) // 2
    return resized.crop((left, top, left + target_width, top + target_height))

# ---------- Main ----------

def build_profit_card(agent: Agent, percent: float, avg_price: str, cur_price: str, assets: Assets) -> Image.Image:
    is_profit = percent >= 0
    formatted = format_percent(percent)

    base = (assets.pnl_profit if is_profit else assets.pnl_loss).copy()
    W, H = base.size
    draw = ImageDraw.Draw(base)

    percentX, avatarSize, avatarY, gap = 1900, 180, 640, 30
    symbolFontSize, nameFontSize, lineGap = 70, 50, 20

    name = truncate(agent.name)
    font_symbol = ImageFont.truetype(assets.font_bold, size=symbolFontSize)
    font_name = ImageFont.truetype(assets.font_regular, size=nameFontSize)

    block_width = max(draw.textlength(agent.symbol, font=font_symbol),
                      draw.textlength(name, font=font_name))

    text_left = percentX - int(block_width)
    avatarX = text_left - gap - avatarSize

    symbolY = int(
        avatarY + avatarSize / 2 - (symbolFontSize * 0.8 + lineGap + nameFontSize * 0.8) / 2 + symbolFontSize * 0.8)
    nameY = symbolY + lineGap + int(nameFontSize * 0.8)

    avatar = rounded_avatar_from_url(agent.profilePicture, avatarSize)
    base.alpha_composite(avatar, dest=(avatarX, avatarY))

    draw.text((text_left, symbolY), agent.symbol, font=font_symbol, fill=(188, 146, 255), anchor="ls")
    draw.text((text_left, nameY), name, font=font_name, fill=(255, 255, 255), anchor="ls")

    # Percent text with glow
    percent_font_size = fit_font_size(draw, formatted, 350, 1250, assets.font_semibold)
    font_percent = ImageFont.truetype(assets.font_semibold, size=percent_font_size)
    percentY = int(400 + percent_font_size * 0.4)

    glow = (121, 225, 93) if is_profit else (217, 49, 72)
    draw_glow_text(base, (percentX, percentY), formatted, font_percent, glow)

    price_font   = ImageFont.truetype(assets.font_price, size=60)
    min_price_width = 180  # adjust to taste

    def pad_price(text: str) -> str:
        w = draw.textlength(text, font=price_font)
        if w >= min_price_width:
            return text
        # Add non-breaking spaces until width is enough
        padded = text
        while draw.textlength(padded, font=price_font) < min_price_width:
            padded = " " + padded  # pad on left to preserve right alignment
        return padded

    # Pad both price strings if needed
    avg_price_str = pad_price(f"${avg_price}")
    cur_price_str = pad_price(f"${cur_price}")
    draw.text((1350, 1100), avg_price_str, font=price_font, fill=(255, 255, 255), anchor="rs")
    draw.text((percentX, 1100), cur_price_str, font=price_font, fill=(255, 255, 255), anchor="rs")

    return base
