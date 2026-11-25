#!/usr/bin/env python3
"""THE WORLD IN ONE DAY - 24 November 2026.

A one-image summary of the world news of Tuesday 24 November 2026,
built for make.fun's news-image-20261124 bounty.

The program is pure Python 3 standard library. It reads four
photographic panels from assets/ (AI-generated in the build session,
free of any text), composites them into a newspaper front page with
crisp hand-drawn vector type, quantises the result to a 256-colour
palette and writes /output/entry.png (or $MAKEFUN_OUTPUT_DIR/entry.png).
It runs with no network and is byte-for-byte deterministic.
"""

import os
import struct
import sys
import zlib

# ---------------------------------------------------------------- PNG input

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_png(path):
    """Decode a PNG file to (width, height, RGB bytes)."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != _PNG_MAGIC:
        raise ValueError("not a PNG file: %s" % path)
    pos = 8
    idat = bytearray()
    palette = None
    width = height = bit_depth = colour_type = interlace = None
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            (width, height, bit_depth, colour_type, _comp, _filt,
             interlace) = struct.unpack(">IIBBBBB", body)
        elif tag == b"PLTE":
            palette = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + length
    if interlace != 0:
        raise ValueError("interlaced PNG is not supported: %s" % path)
    if bit_depth not in (8, 16):
        raise ValueError("unsupported bit depth %r" % bit_depth)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type]
    step = channels * (bit_depth // 8)          # bytes per pixel, raw stream
    raw = zlib.decompress(bytes(idat))
    stride = width * step
    out = bytearray(height * stride)
    prev = bytearray(stride)
    src = 0
    for y in range(height):
        ftype = raw[src]
        src += 1
        row = bytearray(raw[src:src + stride])
        src += stride
        if ftype == 1:                          # Sub
            for i in range(step, stride):
                row[i] = (row[i] + row[i - step]) & 0xFF
        elif ftype == 2:                        # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ftype == 3:                        # Average
            for i in range(stride):
                left = row[i - step] if i >= step else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:                        # Paeth
            for i in range(stride):
                a = row[i - step] if i >= step else 0
                b = prev[i]
                c = prev[i - step] if i >= step else 0
                row[i] = (row[i] + _paeth(a, b, c)) & 0xFF
        out[y * stride:(y + 1) * stride] = row
        prev = row
    if bit_depth == 16:
        out = out[0::2]                         # keep the high byte per sample
    rgb = bytearray(width * height * 3)
    if colour_type == 2:
        rgb[:] = out
    elif colour_type == 6:
        j = 0
        for i in range(0, len(out), 4):
            rgb[j:j + 3] = out[i:i + 3]
            j += 3
    elif colour_type == 0:
        j = 0
        for i in range(len(out)):
            v = out[i]
            rgb[j] = v
            rgb[j + 1] = v
            rgb[j + 2] = v
            j += 3
    elif colour_type == 4:
        j = 0
        for i in range(0, len(out), 2):
            v = out[i]
            rgb[j] = v
            rgb[j + 1] = v
            rgb[j + 2] = v
            j += 3
    elif colour_type == 3:
        j = 0
        for i in range(len(out)):
            p = out[i] * 3
            rgb[j:j + 3] = palette[p:p + 3]
            j += 3
    return width, height, bytes(rgb)


# ------------------------------------------------------------------- canvas

class Canvas:
    """A flat RGB pixel buffer with rectangle and image placement."""

    def __init__(self, width, height, colour):
        self.w = width
        self.h = height
        self.px = bytearray(colour) * (width * height)

    def fill_rect(self, x, y, w, h, colour):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(colour) * (x1 - x0)
        span = (x1 - x0) * 3
        for yy in range(y0, y1):
            off = (yy * self.w + x0) * 3
            self.px[off:off + span] = row

    def paste_cover(self, image, x, y, w, h):
        """Place an image into the box (x, y, w, h), area-averaged.

        The source is expected to be a whole multiple of the box in each
        axis (the shipped panels are exactly 2x), but any ratio works.
        """
        sw, sh, src = image
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        fx = sw / w
        fy = sh / h
        for dy in range(y0, y1):
            sy0 = int((dy - y) * fy)
            sy1 = max(sy0 + 1, int((dy - y + 1) * fy))
            for dx in range(x0, x1):
                sx0 = int((dx - x) * fx)
                sx1 = max(sx0 + 1, int((dx - x + 1) * fx))
                r = g = b = n = 0
                for sy in range(sy0, min(sy1, sh)):
                    base = sy * sw * 3
                    for sx in range(sx0, min(sx1, sw)):
                        o = base + sx * 3
                        r += src[o]
                        g += src[o + 1]
                        b += src[o + 2]
                        n += 1
                off = (dy * self.w + dx) * 3
                self.px[off] = r // n
                self.px[off + 1] = g // n
                self.px[off + 2] = b // n

    def blend(self, x, y, tile, tw, th, colour):
        """Alpha-blend a greyscale coverage tile in a single colour."""
        cr, cg, cb = colour
        for ty in range(th):
            yy = y + ty
            if yy < 0 or yy >= self.h:
                continue
            base = yy * self.w * 3
            trow = ty * tw
            for tx in range(tw):
                cov = tile[trow + tx]
                if cov == 0:
                    continue
                xx = x + tx
                if xx < 0 or xx >= self.w:
                    continue
                off = base + xx * 3
                if cov == 255:
                    self.px[off] = cr
                    self.px[off + 1] = cg
                    self.px[off + 2] = cb
                else:
                    inv = 255 - cov
                    self.px[off] = (cr * cov + self.px[off] * inv) // 255
                    self.px[off + 1] = (cg * cov + self.px[off + 1] * inv) // 255
                    self.px[off + 2] = (cb * cov + self.px[off + 2] * inv) // 255


# ------------------------------------------------------------- stroke font
# Glyphs live on a grid: cap height y=0..9, x-height y=3.5..9, baseline
# y=9, descenders to y=12. Each glyph is a tuple of strokes; each stroke
# is a tuple of (x, y) points joined as a polyline. A one-point stroke
# stamps a round dot. Advances are in the same units (default 8).

GLYPHS = {
    "A": (((1, 9), (4, 0), (7, 9)), ((2.7, 5.9), (5.3, 5.9))),
    "B": (((1.5, 0), (1.5, 9)),
          ((1.5, 0), (4.1, 0.3), (5.3, 2.1), (4.3, 4.2), (1.5, 4.5)),
          ((1.5, 4.5), (4.5, 4.5), (5.7, 6.7), (4.4, 9), (1.5, 9))),
    "C": (((6.8, 2.1), (5.1, 0.6), (3, 0.7), (1.7, 2.5), (1.6, 6.5),
           (2.9, 8.6), (5, 8.9), (6.8, 6.9)),),
    "D": (((1.5, 0), (1.5, 9)),
          ((1.5, 0), (4, 0.3), (6, 2.4), (6, 6.6), (4, 8.7), (1.5, 9))),
    "E": (((6.8, 0), (1.5, 0), (1.5, 9), (6.8, 9)),
          ((1.5, 4.5), (5.6, 4.5))),
    "F": (((6.8, 0), (1.5, 0), (1.5, 9)), ((1.5, 4.5), (5.4, 4.5))),
    "G": (((6.8, 2.1), (5.1, 0.6), (3, 0.7), (1.7, 2.5), (1.6, 6.5),
           (2.9, 8.6), (5, 8.9), (6.9, 7.6), (6.9, 5.3), (4.7, 5.3)),),
    "H": (((1.5, 0), (1.5, 9)), ((6.5, 0), (6.5, 9)),
          ((1.5, 4.5), (6.5, 4.5))),
    "I": (((4, 0), (4, 9)), ((2.2, 0), (5.8, 0)), ((2.2, 9), (5.8, 9))),
    "J": (((6.5, 0), (6.5, 6.6), (5.7, 8.7), (3.9, 9.1), (2.3, 8),
           (1.9, 6.5)), ((4.7, 0), (6.5, 0))),
    "K": (((1.5, 0), (1.5, 9)), ((6.6, 0), (1.9, 4.9)),
          ((2.8, 3.9), (6.8, 9))),
    "L": (((1.5, 0), (1.5, 9), (6.8, 9)),),
    "M": (((1.3, 9), (1.3, 0), (4, 5.6), (6.7, 0), (6.7, 9)),),
    "N": (((1.3, 9), (1.3, 0), (6.7, 9), (6.7, 0)),),
    "O": (((4, 0), (6.2, 1.2), (7, 4.5), (6.2, 7.8), (4, 9), (1.8, 7.8),
           (1, 4.5), (1.8, 1.2), (4, 0)),),
    "P": (((1.5, 9), (1.5, 0)),
          ((1.5, 0), (4.6, 0.3), (5.9, 2.2), (4.6, 4.6), (1.5, 4.6))),
    "Q": (((4, 0), (6.2, 1.2), (7, 4.5), (6.2, 7.8), (4, 9), (1.8, 7.8),
           (1, 4.5), (1.8, 1.2), (4, 0)), ((5, 6.7), (7.3, 9.3))),
    "R": (((1.5, 9), (1.5, 0)),
          ((1.5, 0), (4.6, 0.3), (5.9, 2.2), (4.6, 4.6), (1.5, 4.6)),
          ((4.1, 4.6), (6.8, 9))),
    "S": (((6.6, 1.9), (5, 0.5), (2.8, 0.7), (1.8, 2.4), (2.7, 4.2),
           (5.3, 5.1), (6.2, 6.8), (5, 8.7), (2.7, 8.9), (1.4, 7.3)),),
    "T": (((4, 0), (4, 9)), ((0.8, 0), (7.2, 0))),
    "U": (((1.3, 0), (1.3, 6.4), (2.2, 8.6), (4, 9.1), (5.8, 8.6),
           (6.7, 6.4), (6.7, 0)),),
    "V": (((0.9, 0), (4, 9), (7.1, 0)),),
    "W": (((0.7, 0), (2, 9), (4, 3.6), (6, 9), (7.3, 0)),),
    "X": (((1.2, 0), (6.8, 9)), ((6.8, 0), (1.2, 9))),
    "Y": (((0.9, 0), (4, 4.7)), ((7.1, 0), (4, 4.7)), ((4, 4.7), (4, 9))),
    "Z": (((1.2, 0), (6.8, 0), (1.2, 9), (6.8, 9)),),
    "a": (((5.8, 3.5), (5.8, 9)),
          ((3.7, 3.5), (2, 4.4), (1.5, 6.3), (2, 8.2), (3.7, 9),
           (5.3, 8.3), (5.8, 6.4))),
    "b": (((1.5, 0), (1.5, 9)),
          ((1.5, 5.6), (2.6, 3.9), (4.5, 3.5), (5.9, 5.2), (5.9, 7.2),
           (4.5, 9), (2.6, 8.7), (1.5, 7.4))),
    "c": (((5.8, 4.7), (4.4, 3.6), (2.7, 3.8), (1.7, 5.4), (1.7, 7.2),
           (2.7, 8.7), (4.4, 8.9), (5.8, 7.9)),),
    "d": (((5.8, 0), (5.8, 9)),
          ((5.8, 5.6), (4.6, 3.9), (2.8, 3.5), (1.6, 5.2), (1.6, 7.2),
           (2.8, 9), (4.6, 8.7), (5.8, 7.4))),
    "e": (((1.6, 6.1), (5.9, 6.1)),
          ((5.9, 6.1), (5.3, 4.2), (3.7, 3.5), (2, 4.5), (1.6, 6.6),
           (2.3, 8.5), (4, 9), (5.7, 7.9))),
    "f": (((5.7, 1.1), (4.5, 0.3), (3.5, 1.5), (3.5, 9)),
          ((1.9, 3.8), (5.5, 3.8))),
    "g": (((5.8, 3.5), (5.8, 10.2), (4.9, 11.7), (3.2, 11.9), (2, 10.9)),
          ((3.7, 3.5), (2, 4.4), (1.5, 6.3), (2, 8.2), (3.7, 9),
           (5.3, 8.3), (5.8, 6.4))),
    "h": (((1.5, 0), (1.5, 9)),
          ((1.5, 5.7), (2.6, 4), (4.5, 3.6), (5.7, 5.3), (5.7, 9))),
    "i": (((3.4, 3.5), (3.4, 9)), ((3.4, 1.3),)),
    "j": (((3.9, 3.5), (3.9, 10.1), (3.1, 11.6), (1.7, 11.7), (1, 10.7)),
          ((3.9, 1.3),)),
    "k": (((1.5, 0), (1.5, 9)), ((5.6, 3.5), (2.1, 6.4)),
          ((3.1, 5.6), (5.9, 9))),
    "l": (((3.4, 0), (3.4, 9)),),
    "m": (((1.2, 3.5), (1.2, 9)),
          ((1.2, 5.5), (2.2, 3.9), (3.9, 3.6), (4.7, 5.2), (4.7, 9)),
          ((4.7, 5.5), (5.6, 3.9), (7.3, 3.6), (8.1, 5.2), (8.1, 9))),
    "n": (((1.5, 3.5), (1.5, 9)),
          ((1.5, 5.7), (2.6, 4), (4.5, 3.6), (5.7, 5.3), (5.7, 9))),
    "o": (((3.9, 3.5), (5.6, 4.3), (6.2, 6.2), (5.6, 8.2), (3.9, 9),
           (2.2, 8.2), (1.6, 6.2), (2.2, 4.3), (3.9, 3.5)),),
    "p": (((1.5, 3.5), (1.5, 11.9)),
          ((1.5, 5.6), (2.6, 3.9), (4.5, 3.5), (5.9, 5.2), (5.9, 7.2),
           (4.5, 9), (2.6, 8.7), (1.5, 7.4))),
    "q": (((5.8, 3.5), (5.8, 11.9)),
          ((5.8, 5.6), (4.6, 3.9), (2.8, 3.5), (1.6, 5.2), (1.6, 7.2),
           (2.8, 9), (4.6, 8.7), (5.8, 7.4))),
    "r": (((1.5, 3.5), (1.5, 9)),
          ((1.5, 5.7), (2.6, 4.1), (4.4, 3.6), (5.6, 4.3))),
    "s": (((5.7, 4.6), (4.4, 3.6), (2.7, 3.8), (2, 5.2), (2.8, 6.5),
           (4.9, 7.1), (5.5, 8), (4.4, 8.9), (2.6, 8.8), (1.6, 7.9)),),
    "t": (((3.6, 1.2), (3.6, 7.7), (4.4, 8.9), (5.8, 8.7)),
          ((1.8, 3.8), (5.6, 3.8))),
    "u": (((1.4, 3.5), (1.4, 6.9), (2.2, 8.7), (4.1, 9), (5.9, 7.9),
           (6.3, 6.3), (6.3, 3.5)), ((6.3, 6.6), (6.3, 9))),
    "v": (((1.2, 3.5), (4, 9), (6.8, 3.5)),),
    "w": (((0.9, 3.5), (2.1, 9), (3.9, 5.2), (5.7, 9), (6.9, 3.5)),),
    "x": (((1.6, 3.5), (6.2, 9)), ((6.2, 3.5), (1.6, 9))),
    "y": (((1.2, 3.5), (3.9, 8.5)), ((6.6, 3.5), (3.9, 8.5)),
          ((3.9, 8.5), (3.1, 10.9), (1.9, 11.7), (1.1, 10.8))),
    "z": (((1.4, 3.5), (6.4, 3.5), (1.4, 9), (6.4, 9)),),
    "0": (((4, 0), (5.9, 1.4), (6.3, 4.5), (5.9, 7.6), (4, 9), (2.1, 7.6),
           (1.7, 4.5), (2.1, 1.4), (4, 0)),),
    "1": (((2.7, 1.9), (4.6, 0.1), (4.6, 9)), ((2.4, 9), (6.6, 9))),
    "2": (((1.6, 2.4), (2.6, 0.7), (4.6, 0.6), (6, 2.2), (5.5, 4.3),
           (1.4, 9), (6.6, 9)),),
    "3": (((1.6, 1.7), (3, 0.5), (5, 0.8), (5.8, 2.4), (4.7, 4.2),
           (3.3, 4.5)),
          ((3.3, 4.5), (5.1, 4.6), (6.1, 6.6), (5, 8.8), (2.8, 8.9),
           (1.5, 7.5))),
    "4": (((4.9, 9), (4.9, 0), (1.2, 6.3), (7, 6.3)),),
    "5": (((6.4, 0), (2.1, 0), (1.9, 4.1)),
          ((1.9, 4.3), (4.3, 4.1), (6, 6.3), (4.8, 8.8), (2.5, 8.9),
           (1.3, 7.4))),
    "6": (((5.9, 1.7), (4.2, 0.6), (2.4, 2.4), (1.7, 5.6), (2.3, 8),
           (4, 9.1), (5.9, 8), (6.3, 6.1), (5, 4.5), (2.7, 4.7),
           (1.9, 5.8)),),
    "7": (((1.2, 0), (6.8, 0), (3.6, 9)),),
    "8": (((4, 4.4), (2.6, 3.6), (2.3, 1.9), (3.1, 0.5), (4.9, 0.5),
           (5.7, 1.9), (5.4, 3.6), (4, 4.4), (2.5, 5.4), (2.1, 7.2),
           (3, 8.8), (5, 8.8), (5.9, 7.2), (5.5, 5.4), (4, 4.4)),),
    "9": (((2.1, 7.3), (3.8, 8.4), (5.6, 6.6), (6.3, 3.4), (5.7, 1),
           (4, -0.1), (2.1, 1), (1.7, 2.9), (3, 4.5), (5.3, 4.3),
           (6.1, 3.2)),),
    " ": (),
    ".": (((3.6, 8.5),),),
    ",": (((3.9, 8.1), (3.3, 10.1)),),
    "'": (((3.7, 0.3), (3.2, 2.3)),),
    ":": (((3.6, 3.2),), ((3.6, 8.3),)),
    ";": (((3.6, 3.2),), ((3.9, 8.1), (3.3, 10.1))),
    "-": (((1.7, 5.4), (5.5, 5.4)),),
    "–": (((1.2, 5.4), (6.4, 5.4)),),
    "—": (((0.7, 5.4), (7.5, 5.4)),),
    "·": (((3.8, 5.2),),),
    "•": (((3.9, 5),),),
    "!": (((3.8, 0), (3.8, 6.3)), ((3.8, 8.5),)),
    "?": (((1.7, 2.2), (2.8, 0.6), (4.9, 0.7), (5.9, 2.3), (5.2, 4.1),
           (3.9, 5), (3.9, 6.6)), ((3.9, 8.5),)),
    "(": (((5.5, 0.5), (3.9, 2.4), (3.2, 4.7), (3.9, 7), (5.5, 8.9)),),
    ")": (((2.9, 0.5), (4.5, 2.4), (5.2, 4.7), (4.5, 7), (2.9, 8.9)),),
    "/": (((1.6, 9.3), (6.2, 0.1)),),
    "&": (((6.3, 8.9), (2.1, 3.6), (2.3, 1.5), (4.2, 0.6), (5.4, 1.9),
           (4.7, 3.7), (1.9, 6.3), (2.1, 8.3), (4.2, 9), (6.9, 6.9)),),
    "%": (((2.2, 0.6), (3.4, 1.4), (2.2, 2.6), (1.2, 1.6), (2.2, 0.6)),
          ((6.4, 9.3), (1.8, 0.1)),
          ((5.9, 6.8), (7.1, 7.6), (5.9, 8.8), (4.9, 7.8), (5.9, 6.8))),
    "$": (((6.4, 1.9), (4.9, 0.6), (2.8, 0.8), (1.9, 2.4), (2.7, 4.1),
           (5.2, 5), (6, 6.7), (4.9, 8.6), (2.6, 8.8), (1.5, 7.4)),
          ((4, -0.6), (4, 9.8))),
    "+": (((1.8, 4.5), (6.2, 4.5)), ((4, 2.2), (4, 6.8))),
    "=": (((1.6, 3.4), (6.4, 3.4)), ((1.6, 6.2), (6.4, 6.2))),
    "<": (((6.3, 1.2), (1.9, 4.5), (6.3, 7.8)),),
    ">": (((1.7, 1.2), (6.1, 4.5), (1.7, 7.8)),),
    "#": (((3.1, 0), (2.4, 9)), ((5.6, 0), (4.9, 9)),
          ((1.2, 3.3), (6.9, 3.3)), ((1, 6.1), (6.7, 6.1))),
    "*": (((4, 1.2), (4, 7.8)), ((1.6, 2.6), (6.4, 6.4)),
          ((6.4, 2.6), (1.6, 6.4))),
    "°": (((4, 0.4), (5.3, 1.2), (4.9, 2.7), (3.6, 3.1), (2.7, 2.3),
           (3.1, 0.9), (4, 0.4)),),
    "…": (((1.6, 8.5),), ((4.2, 8.5),), ((6.8, 8.5),)),
    '"': (((2.8, 0.3), (2.4, 2.3)), ((5.4, 0.3), (5, 2.3))),
    "“": (((2.8, 0.3), (2.4, 2.3)), ((5.4, 0.3), (5, 2.3))),
    "”": (((2.8, 0.3), (2.4, 2.3)), ((5.4, 0.3), (5, 2.3))),
    "‘": (((3.7, 0.3), (3.2, 2.3)),),
    "’": (((3.7, 0.3), (3.2, 2.3)),),
    "İ": (((4, 0), (4, 9)), ((2.2, 0), (5.8, 0)), ((2.2, 9), (5.8, 9)),
          ((4, -1.9),)),
    "Ü": (((1.3, 0), (1.3, 6.4), (2.2, 8.6), (4, 9.1), (5.8, 8.6),
           (6.7, 6.4), (6.7, 0)), ((2.4, -1.9),), ((5.6, -1.9),)),
}

ADVANCE = {
    "I": 5.2, "J": 5.6, "M": 8.4, "W": 9.4, " ": 4.2,
    "f": 4.8, "i": 3.6, "j": 4, "l": 3.6, "m": 9.6, "r": 5.2, "t": 5.2,
    "w": 9.2, "1": 6.8,
    ".": 3.6, ",": 3.6, "'": 3.2, ":": 3.6, ";": 3.6, "!": 3.6,
    "-": 5.4, "–": 6.8, "—": 8.2, "·": 3.8, "•": 4.4,
    "(": 4.6, ")": 4.6, "/": 5.2, "…": 8.4, "°": 5.4, '"': 5.6,
    "“": 5.6, "”": 5.6, "‘": 3.2, "’": 3.2, "İ": 5.2,
}
DEFAULT_ADVANCE = 8.0


# ------------------------------------------------------------- text engine

SUPER = 2                     # supersampling factor for type
_GLYPH_TOP = 2.4              # glyph space kept above y=0 (dots, accents)
_GLYPH_BOT = 12.6             # glyph space kept below y=0 (descenders)


def _advance(ch):
    return ADVANCE.get(ch, DEFAULT_ADVANCE)


def text_units(text, ls):
    if not text:
        return 0.0
    return sum(_advance(ch) for ch in text) + ls * (len(text) - 1)


def text_width(text, cap, ls=0.55):
    """Width in final pixels of a string at the given cap height."""
    return text_units(text, ls) * (cap / 9.0)


def _disc_offsets(radius):
    r = int(radius + 0.5)
    return [(dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1)
            if dx * dx + dy * dy <= radius * radius]


def _render_tile(text, cap, bold, ls):
    """Render a string to a coverage tile at final resolution.

    Returns (tile bytes, tile width, tile height, dx, dy) where dx, dy
    position the tile so the text's pen origin lands at (0, 0) and the
    glyph y=0 line lands at y=0.
    """
    u_f = cap / 9.0
    u_t = u_f * SUPER
    radius = (0.82 if bold else 0.60) * u_t
    pad = int(radius) + 2
    tw_t = int(text_units(text, ls) * u_t + 0.999) + 2 * pad
    th_t = int((_GLYPH_BOT + _GLYPH_TOP) * u_t + 0.999) + 2 * pad
    mask = bytearray(tw_t * th_t)
    offsets = _disc_offsets(radius)
    step = max(1.0, radius * 0.45)
    pen = float(pad)
    for ch in text:
        glyph = GLYPHS.get(ch)
        if glyph:
            for stroke in glyph:
                pts = [(pen + gx * u_t, pad + (gy + _GLYPH_TOP) * u_t)
                       for (gx, gy) in stroke]
                for i in range(len(pts)):
                    x0, y0 = pts[i]
                    if i + 1 < len(pts):
                        x1, y1 = pts[i + 1]
                    else:
                        x1, y1 = x0, y0
                    dist = max(abs(x1 - x0), abs(y1 - y0))
                    n = max(1, int(dist / step))
                    for k in range(n + 1):
                        cx = x0 + (x1 - x0) * k / n
                        cy = y0 + (y1 - y0) * k / n
                        for (dx, dy) in offsets:
                            xx = int(cx + 0.5) + dx
                            yy = int(cy + 0.5) + dy
                            if 0 <= xx < tw_t and 0 <= yy < th_t:
                                mask[yy * tw_t + xx] = 255
        pen += (_advance(ch) + ls) * u_t
    tw = tw_t // SUPER
    th = th_t // SUPER
    tile = bytearray(tw * th)
    for yy in range(th):
        for xx in range(tw):
            total = 0
            for sy in range(SUPER):
                base = (yy * SUPER + sy) * tw_t + xx * SUPER
                for sx in range(SUPER):
                    total += mask[base + sx]
            tile[yy * tw + xx] = total // (SUPER * SUPER)
    dx = -int(pad / SUPER + 0.5)
    dy = -int((pad + _GLYPH_TOP * u_t) / SUPER + 0.5)
    return bytes(tile), tw, th, dx, dy


def draw_text(canvas, x, y_top, text, cap, colour, bold=False, ls=0.55,
              align="left"):
    """Draw a string; y_top is the final-pixel y of the glyph y=0 line.

    Returns the final-pixel x just past the text.
    """
    width = text_width(text, cap, ls)
    if align == "center":
        x = x - width / 2.0
    elif align == "right":
        x = x - width
    tile, tw, th, dx, dy = _render_tile(text, cap, bold, ls)
    canvas.blend(int(round(x)) + dx, int(round(y_top)) + dy, tile, tw, th,
                 colour)
    return x + width


def wrap_text(text, cap, bold, ls, max_width):
    """Greedy word wrap; returns a list of lines that fit max_width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if current and text_width(trial, cap, ls) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


# ------------------------------------------------------- palette and output

_BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def _build_palette(rgb, max_colours, reserved):
    """Median-cut palette; reserved colours come first, exactly."""
    reserved_set = set(reserved)
    counts = {}
    sums = {}
    for i in range(0, len(rgb), 3):
        r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
        if (r, g, b) in reserved_set:
            continue
        key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
        if key in counts:
            counts[key] += 1
            s = sums[key]
            s[0] += r
            s[1] += g
            s[2] += b
        else:
            counts[key] = 1
            sums[key] = [r, g, b]
    boxes = [sorted(counts.items())]
    target = max_colours - len(reserved)
    while len(boxes) < target:
        best = -1
        best_score = -1
        for bi, box in enumerate(boxes):
            if len(box) < 2:
                continue
            rs = [(k >> 10) & 31 for k, _c in box]
            gs = [(k >> 5) & 31 for k, _c in box]
            bs = [k & 31 for k, _c in box]
            spread = max(max(rs) - min(rs), max(gs) - min(gs),
                         max(bs) - min(bs))
            pop = sum(c for _k, c in box)
            score = pop * (spread + 1)
            if score > best_score:
                best_score = score
                best = bi
        if best < 0:
            break
        box = boxes.pop(best)
        rs = [(k >> 10) & 31 for k, _c in box]
        gs = [(k >> 5) & 31 for k, _c in box]
        bs = [k & 31 for k, _c in box]
        ranges = (max(rs) - min(rs), max(gs) - min(gs), max(bs) - min(bs))
        shift = (10, 5, 0)[ranges.index(max(ranges))]
        box.sort(key=lambda kc: ((kc[0] >> shift) & 31, kc[0]))
        total = sum(c for _k, c in box)
        acc = 0
        cut = len(box) - 1
        for idx, (_k, c) in enumerate(box):
            acc += c
            if acc >= total / 2:
                cut = idx + 1
                break
        if cut >= len(box):
            cut = len(box) - 1
        boxes.append(box[:cut])
        boxes.append(box[cut:])
    palette = [tuple(c) for c in reserved]
    for box in boxes:
        total = sum(c for _k, c in box)
        r = sum(sums[k][0] for k, _c in box) // total
        g = sum(sums[k][1] for k, _c in box) // total
        b = sum(sums[k][2] for k, _c in box) // total
        palette.append((r, g, b))
    return palette


def _index_image(rgb, w, h, palette, reserved_count):
    exact = {}
    for i in range(reserved_count):
        exact[palette[i]] = i
    cache = {}
    out = bytearray(w * h)
    for y in range(h):
        brow = _BAYER[y & 3]
        base = y * w * 3
        obase = y * w
        for x in range(w):
            o = base + x * 3
            r, g, b = rgb[o], rgb[o + 1], rgb[o + 2]
            hit = exact.get((r, g, b))
            if hit is not None:
                out[obase + x] = hit
                continue
            d = brow[x & 3] - 8
            r2 = min(255, max(0, r + d))
            g2 = min(255, max(0, g + d))
            b2 = min(255, max(0, b + d))
            key = ((r2 >> 3) << 10) | ((g2 >> 3) << 5) | (b2 >> 3)
            idx = cache.get(key)
            if idx is None:
                cr = (r2 & 0xF8) + 4
                cg = (g2 & 0xF8) + 4
                cb = (b2 & 0xF8) + 4
                best = 0
                best_dist = None
                for pi, (pr, pg, pb) in enumerate(palette):
                    dist = ((pr - cr) * (pr - cr) + (pg - cg) * (pg - cg)
                            + (pb - cb) * (pb - cb))
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best = pi
                idx = best
                cache[key] = idx
            out[obase + x] = idx
    return out


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode_png(rgb, w, h, reserved, max_colours):
    """Quantise to a palette and encode as an indexed PNG."""
    palette = _build_palette(rgb, max_colours, reserved)
    indices = _index_image(rgb, w, h, palette, len(reserved))
    raw = bytearray()
    for y in range(h):
        row = indices[y * w:(y + 1) * w]
        sub = bytes((row[i] - (row[i - 1] if i else 0)) & 0xFF
                    for i in range(w))
        s0 = sum(v if v < 128 else 256 - v for v in row)
        s1 = sum(v if v < 128 else 256 - v for v in sub)
        if s1 < s0:
            raw.append(1)
            raw += sub
        else:
            raw.append(0)
            raw += row
    plte = b"".join(bytes(c) for c in palette)
    return (_PNG_MAGIC
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + _chunk(b"PLTE", plte)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


# ---------------------------------------------------------------- the poster

PAPER = (246, 241, 231)
INK = (23, 20, 17)
RED = (163, 29, 37)
BODY = (52, 47, 42)
WHITE = (250, 247, 240)
DARK = (26, 23, 20)
BAND_LINE = (238, 233, 224)
BAND_REGION = (240, 170, 158)
BAND_SRC = (168, 160, 148)
RESERVED = (PAPER, INK, RED, WHITE, DARK)

MX = 30                       # page margin
CW = 1024 - 2 * MX            # content width


def build_poster(here):
    assets = {}
    for name in ("fire", "graves", "cop31", "bitcoin"):
        assets[name] = read_png(os.path.join(here, "assets", name + ".png"))
    cv = Canvas(1024, 1024, PAPER)

    # Masthead
    cv.fill_rect(MX, 18, CW, 3, INK)
    cv.fill_rect(MX, 24, CW, 1, INK)
    draw_text(cv, 512, 33, "THE DAY IN NEWS", 11.5, RED, bold=True, ls=1.6,
              align="center")
    draw_text(cv, 512, 52, "THE WORLD IN ONE DAY", 45, INK, bold=True,
              ls=0.4, align="center")
    cv.fill_rect(MX, 106, CW, 2, INK)
    cv.fill_rect(MX, 114, CW, 38, RED)
    draw_text(cv, 512, 122, "TUESDAY, 24 NOVEMBER 2026", 21, WHITE,
              bold=True, ls=1.0, align="center")

    # Lead story: the Cikande factory fire
    draw_text(cv, MX, 166, "INDONESIA — CIKANDE, BANTEN", 13.5, RED,
              bold=True, ls=0.8)
    cv.fill_rect(MX - 2, 184, CW + 4, 314, INK)
    cv.paste_cover(assets["fire"], MX, 186, CW, 310)
    draw_text(cv, MX, 512, "FACTORY FIRE:", 37, INK, bold=True, ls=0.3)
    draw_text(cv, MX, 558, "28 WORKERS STILL MISSING", 37, INK, bold=True,
              ls=0.3)
    sub = ("Sixteen victims identified at the Cikande candy factory as "
           "rescuers keep searching the ruins, and police open a "
           "negligence investigation.")
    yy = 606
    for line in wrap_text(sub, 15, False, 0.35, CW):
        draw_text(cv, MX, yy, line, 15, BODY, ls=0.35)
        yy += 21
    cv.fill_rect(MX, 656, CW, 2, INK)

    # Three more stories in a row
    columns = (
        ("graves", "RUSSIA — THE WAR'S TOLL",
         ("RUSSIA'S WAR DEAD", "TOP 700,000"),
         "Counted from leaked data by Meduza and Mediazona."),
        ("cop31", "CLIMATE — ANTALYA, TÜRKIYE",
         ("COP31 CLIMATE TALKS", "COLLAPSE IN TURKEY"),
         "Summit ends with no deal — a first since 2009."),
        ("bitcoin", "MARKETS — CRYPTO",
         ("BITCOIN'S WORST", "NOVEMBER SINCE 2018"),
         "Near $60,000 amid 'extreme fear' and fund outflows."),
    )
    gy = 668
    for i, (asset, kicker, headline, sub) in enumerate(columns):
        x = MX + i * 327
        cv.fill_rect(x - 2, gy - 2, 313, 128, INK)
        cv.paste_cover(assets[asset], x, gy, 309, 124)
        draw_text(cv, x, gy + 132, kicker, 11, RED, bold=True, ls=0.7)
        hy = gy + 152
        for line in headline:
            draw_text(cv, x, hy, line, 16, INK, bold=True, ls=0.25)
            hy += 21
        sy = gy + 200
        for line in wrap_text(sub, 12.5, False, 0.3, 309):
            draw_text(cv, x, sy, line, 12.5, BODY, ls=0.3)
            sy += 16

    # Briefing band: five more stories in one line each
    cv.fill_rect(MX, 904, CW, 112, DARK)
    draw_text(cv, 46, 915, "ALSO ON 24 NOVEMBER", 12.5, WHITE, bold=True,
              ls=1.2)
    draw_text(cv, 978, 918, "SOURCES: REUTERS · AFP · AP · MEDUZA/MEDIAZONA"
              " · WHO", 9, BAND_SRC, ls=0.4, align="right")
    briefing = (
        ("UKRAINE — ", "Strikes kill 11 near Kyiv; power cut to 353,000 "
         "homes"),
        ("MIDDLE EAST — ", "Iran vows reply as US sanctions its oil "
         "networks"),
        ("UNITED STATES — ", "First Gen Z woman elected to Congress, "
         "aged 29"),
        ("EUROPE — ", "EU proposes a 22nd sanctions package on Russia"),
        ("CONGO — ", "Ebola deaths pass 5,600, WHO says; Kenya counts "
         "down"),
    )
    yy = 936
    for region, rest in briefing:
        end = draw_text(cv, 46, yy, region, 11, BAND_REGION, bold=True,
                        ls=0.3)
        draw_text(cv, end, yy, rest, 11, BAND_LINE, ls=0.3)
        yy += 15.8
    return cv


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(outdir, exist_ok=True)
    canvas = build_poster(here)
    rgb = bytes(canvas.px)
    data = None
    for max_colours in (256, 192, 144):
        data = encode_png(rgb, 1024, 1024, RESERVED, max_colours)
        if len(data) <= 1000000:
            break
    with open(os.path.join(outdir, "entry.png"), "wb") as handle:
        handle.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
