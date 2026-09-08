"""
render_icon.py - static/favicon.svg からアプリのアイコンを書き出す

SVG をそのまま扱える形式（ブラウザ・Android）はSVGを使うが、
Windows のショートカットで使う .ico はラスタ形式のため変換が必要になる。

外部ライブラリを増やさずに済むよう、必要な範囲だけのSVGパス解析を持つ。
対応する命令は M C c H h v z（favicon.svg で使われているもの）。

    python tools/render_icon.py
"""

from __future__ import annotations

import io
import os
import re
import struct
import sys

from PIL import Image, ImageDraw

# プロジェクトのルート（tools/ の一つ上）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_PATH = os.path.join(BASE_DIR, "static", "favicon.svg")
ICO_PATH = os.path.join(BASE_DIR, "static", "tracker.ico")
PNG_PATH = os.path.join(BASE_DIR, "static", "icon.png")

# .ico に収める寸法。256px 以外は DIB 形式にする
# （エクスプローラーは小さい寸法の PNG を正しく扱えないことがある）
ICO_SIZES = [16, 24, 32, 48, 64, 256]

# なめらかにするため、この倍率で描いてから縮小する
SUPERSAMPLE = 8

# 曲線を折れ線へ変換するときの分割数
CURVE_STEPS = 16

_NUMBER = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_COMMAND = re.compile(r"([MmCcHhVvLlZz])([^MmCcHhVvLlZz]*)")


class SvgError(Exception):
    """SVGを読み取れなかった場合に送出される例外"""


# ── SVG の読み取り ──


def parse_svg(text: str) -> tuple[float, list[dict]]:
    """viewBox の一辺と、描画する図形の一覧を返す

    図形は {"type": "rect"/"path", ...} の形で返す。
    """
    view_box = re.search(r'viewBox="([\d.\s-]+)"', text)
    if not view_box:
        raise SvgError("viewBox が見つかりません")
    values = [float(v) for v in view_box.group(1).split()]
    if len(values) != 4:
        raise SvgError(f"viewBox の値が4つではありません: {values}")
    size = max(values[2], values[3])

    shapes: list[dict] = []
    for match in re.finditer(r"<rect\b([^>]*)>", text):
        attrs = match.group(1)
        shapes.append(
            {
                "type": "rect",
                "x": _attr(attrs, "x"),
                "y": _attr(attrs, "y"),
                "width": _attr(attrs, "width"),
                "height": _attr(attrs, "height"),
            }
        )

    for match in re.finditer(r'<path\b[^>]*\sd="([^"]+)"', text):
        shapes.append({"type": "path", "d": match.group(1)})

    if not shapes:
        raise SvgError("描画する図形が見つかりません")
    return size, shapes


def _attr(attrs: str, name: str) -> float:
    """属性を数値で取り出す（無ければ0）"""
    match = re.search(rf'\s{name}="([\d.-]+)"', attrs)
    return float(match.group(1)) if match else 0.0


def parse_path(data: str) -> list[list[tuple[float, float]]]:
    """パスを、閉じた折れ線（サブパス）の一覧へ変換する"""
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    x = y = 0.0
    start_x = start_y = 0.0

    for command, raw in _COMMAND.findall(data):
        numbers = [float(n) for n in _NUMBER.findall(raw)]

        if command in "Mm":
            if current:
                subpaths.append(current)
            # 2つ目以降の座標対は、直線として扱う
            for index in range(0, len(numbers) - 1, 2):
                px, py = numbers[index], numbers[index + 1]
                if command == "m":
                    px, py = x + px, y + py
                if index == 0:
                    current = [(px, py)]
                    start_x, start_y = px, py
                else:
                    current.append((px, py))
                x, y = px, py

        elif command in "Ll":
            for index in range(0, len(numbers) - 1, 2):
                px, py = numbers[index], numbers[index + 1]
                if command == "l":
                    px, py = x + px, y + py
                current.append((px, py))
                x, y = px, py

        elif command in "Hh":
            for value in numbers:
                x = x + value if command == "h" else value
                current.append((x, y))

        elif command in "Vv":
            for value in numbers:
                y = y + value if command == "v" else value
                current.append((x, y))

        elif command in "Cc":
            for index in range(0, len(numbers) - 5, 6):
                points = numbers[index : index + 6]
                if command == "c":
                    points = [
                        points[0] + x, points[1] + y,
                        points[2] + x, points[3] + y,
                        points[4] + x, points[5] + y,
                    ]
                current += _cubic(
                    (x, y),
                    (points[0], points[1]),
                    (points[2], points[3]),
                    (points[4], points[5]),
                )
                x, y = points[4], points[5]

        elif command in "Zz":
            if current:
                current.append((start_x, start_y))
                subpaths.append(current)
                current = []
            x, y = start_x, start_y

    if current:
        subpaths.append(current)
    return subpaths


def _cubic(p0, p1, p2, p3) -> list[tuple[float, float]]:
    """3次ベジェ曲線を折れ線へ（始点は含めない）"""
    points = []
    for step in range(1, CURVE_STEPS + 1):
        t = step / CURVE_STEPS
        u = 1 - t
        points.append(
            (
                u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
            )
        )
    return points


# ── 描画 ──


def render(size: int, color=(75, 75, 75)) -> Image.Image:
    """指定した一辺の大きさで描画する"""
    text = io.open(SVG_PATH, encoding="utf-8").read()
    view_size, shapes = parse_svg(text)

    big = size * SUPERSAMPLE
    scale = big / view_size
    mask = Image.new("1", (big, big), 0)

    for shape in shapes:
        if shape["type"] == "rect":
            layer = Image.new("1", (big, big), 0)
            ImageDraw.Draw(layer).rectangle(
                [
                    shape["x"] * scale,
                    shape["y"] * scale,
                    (shape["x"] + shape["width"]) * scale,
                    (shape["y"] + shape["height"]) * scale,
                ],
                fill=1,
            )
            mask = _xor(mask, layer)
        else:
            # サブパスごとに塗り、重なりを打ち消し合わせる（even-odd 規則）。
            # 砂時計の内側のくり抜きはこの規則で表される
            for points in parse_path(shape["d"]):
                if len(points) < 3:
                    continue
                layer = Image.new("1", (big, big), 0)
                ImageDraw.Draw(layer).polygon(
                    [(px * scale, py * scale) for px, py in points], fill=1
                )
                mask = _xor(mask, layer)

    # マスクを色と透明度へ起こし、縮小してなめらかにする
    image = Image.new("RGBA", (big, big), color + (0,))
    image.putalpha(mask.convert("L").point(lambda v: 255 if v else 0))
    solid = Image.new("RGBA", (big, big), color + (255,))
    solid.putalpha(image.getchannel("A"))
    return solid.resize((size, size), Image.LANCZOS)


def _xor(a: Image.Image, b: Image.Image) -> Image.Image:
    """2つのマスクの排他的論理和"""
    from PIL import ImageChops

    return ImageChops.logical_xor(a, b)


# ── 書き出し ──


def _dib(image: Image.Image) -> bytes:
    """1つの寸法を DIB 形式へ変換する"""
    w, h = image.size
    rgba = image.convert("RGBA")

    # BITMAPINFOHEADER。高さは XOR と AND の2枚分を表すため2倍にする
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)

    pixels = bytearray()
    for y in range(h - 1, -1, -1):  # 下の行から並べる
        for x in range(w):
            r, g, b, a = rgba.getpixel((x, y))
            pixels += bytes((b, g, r, a))

    # ANDマスク。32bitでは透明度を使うため0で埋めるが、行は4バイト境界に揃える
    row_bytes = ((w + 31) // 32) * 4
    return header + bytes(pixels) + bytes(row_bytes * h)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_ico(source: Image.Image, sizes: list[int], path: str) -> None:
    """複数の寸法を収めた .ico を書き出す"""
    entries = []
    for size in sizes:
        resized = source.resize((size, size), Image.LANCZOS)
        entries.append((size, _png(resized) if size >= 256 else _dib(resized)))

    offset = 6 + 16 * len(entries)
    directory = b""
    body = b""
    for size, data in entries:
        edge = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", edge, edge, 0, 0, 1, 32, len(data), offset)
        body += data
        offset += len(data)

    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(entries)) + directory + body)


def main() -> int:
    try:
        source = render(256)
    except (SvgError, OSError) as e:
        print(f"アイコンを描画できませんでした: {e}", file=sys.stderr)
        return 1

    source.save(PNG_PATH)
    write_ico(source, ICO_SIZES, ICO_PATH)
    print(f"書き出しました: {PNG_PATH}")
    print(f"書き出しました: {ICO_PATH}（{', '.join(f'{s}px' for s in ICO_SIZES)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
