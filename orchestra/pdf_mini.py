"""Generatore PDF minimale, solo stdlib."""

from __future__ import annotations

import re

_PAGE_W = 595
_MARGIN = 50
_TEXT_W = _PAGE_W - 2 * _MARGIN
_BOTTOM = 60
_TOP = 780

_UNICODE_MAP = {}

# spazi e controlli unicode -> spazio o vuoto
for _cp in list(range(0x2000, 0x200B)) + [0x202F, 0x205F, 0x3000, 0x2028, 0x2029,
                                           0x200E, 0x200F, 0x2060, 0x180E, 0x00AD,
                                           0x2061, 0x2062, 0x2063, 0x2064]:
    _UNICODE_MAP.setdefault(chr(_cp), " " if _cp not in (0x200B, 0x200C, 0x200D, 0xFEFF, 0x00AD) else "")

_UNICODE_MAP.update({
    "\u2014": "-", "\u2013": "-", "\u2212": "-",
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2015": "-",
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2026": "...", "\u2192": "->", "\u2190": "<-", "\u2194": "<->",
    "\u2022": "*", "\u00a0": " ", "\u200b": "", "\u200c": "", "\u200d": "",
    "\ufeff": "", "\u00ab": '"', "\u00bb": '"',
    "\u2264": "<=", "\u2265": ">=", "\u2260": "!=", "\u2248": "~",
    "\u00d7": "x", "\u00f7": "/", "\u20ac": "EUR", "\u00a3": "GBP",
    "\u00a7": "par.", "\u00b0": "deg", "\u00b2": "2", "\u00b3": "3",
    "\u00bc": "1/4", "\u00bd": "1/2", "\u00be": "3/4",
    "\u2032": "'", "\u2033": "''", "\u2030": "%", "\u2020": "+",
    "\u2021": "#", "\u2015": "-", "\u00ae": "(R)", "\u00a9": "(C)",
    "\u2122": "(TM)",
})

# codepoint non definiti in cp1252/WinAnsi
_CP1252_UNDEFINED = {0x81, 0x8D, 0x8F, 0x90, 0x9D}


def _sanitize(s):
    out = []
    for ch in (s or ""):
        if ch in _UNICODE_MAP:
            out.append(_UNICODE_MAP[ch])
            continue
        cp = ord(ch)
        if cp in _CP1252_UNDEFINED:
            out.append(" ")
            continue
        if cp <= 255:
            out.append(ch)
        else:
            # sconosciuto: spazio, non '?'
            out.append(" ")
    return "".join(out)


def _esc(s):
    return (s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))


_INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`)")


def _parse_inline(s):
    spans = []
    for p in _INLINE_RE.split(s):
        if not p:
            continue
        if (p.startswith("**") and p.endswith("**")) or (p.startswith("__") and p.endswith("__")):
            spans.append((p[2:-2], True, False))
        elif (p.startswith("*") and p.endswith("*")) or (p.startswith("_") and p.endswith("_")):
            spans.append((p[1:-1], False, True))
        elif p.startswith("`") and p.endswith("`"):
            spans.append((p[1:-1], False, False))
        else:
            spans.append((p, False, False))
    return spans


def _parse_blocks(text):
    lines = (text or "").split("\n")
    blocks = []
    para = []
    i = 0
    n = len(lines)

    def flush_para():
        nonlocal para
        if para:
            blocks.append(("p", " ".join(para)))
            para = []

    while i < n:
        raw = lines[i]
        s = raw.rstrip()
        st = s.strip()
        if st == "":
            flush_para()
            blocks.append(("blank", ""))
            i += 1
            continue
        # tabella markdown: righe consecutive che iniziano con |
        if st.startswith("|"):
            flush_para()
            tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            if len(tbl) >= 2:
                header = [c.strip() for c in tbl[0].strip("|").split("|")]
                rows = []
                for tl in tbl[2:]:
                    cells = [c.strip() for c in tl.strip("|").split("|")]
                    while len(cells) < len(header):
                        cells.append("")
                    rows.append(cells[:len(header)])
                blocks.append(("table", header, rows))
            else:
                for tl in tbl:
                    para.append(tl)
            continue
        if st.startswith("#"):
            flush_para()
            level = 0
            while level < len(st) and st[level] == "#":
                level += 1
            blocks.append(("h", level, st[level:].strip()))
            i += 1
            continue
        if re.match(r"^[-*_]{3,}$", st):
            flush_para()
            blocks.append(("hr", ""))
            i += 1
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", st)
        if m:
            flush_para()
            blocks.append(("li", "num", m.group(1), m.group(2)))
            i += 1
            continue
        if st.startswith(("- ", "* ", "+ ")):
            flush_para()
            blocks.append(("li", "bullet", "", st[2:]))
            i += 1
            continue
        para.append(st)
        i += 1
    flush_para()
    return blocks


def _char_w(size, bold):
    w = 5.0 * (size / 11.0)
    if bold:
        w *= 1.04
    return w


def _wrap_spans(spans, size, avail):
    tokens = []
    for txt, b, it in spans:
        for part in re.findall(r"\S+|\s+", txt):
            tokens.append((part, b, it))

    lines = []
    current = []
    cur_w = 0.0

    def finalize():
        nonlocal current, cur_w
        while current and current[-1][0].strip() == "":
            cur_w -= _char_w(current[-1][1], size) * len(current[-1][0])
            current.pop()
        if current:
            lines.append(current)
        current = []
        cur_w = 0.0

    for tok, b, it in tokens:
        is_space = tok.strip() == ""
        if is_space:
            if not current:
                continue
            sw = _char_w(b and size or size, b) * len(tok)
            current.append((tok, b, it))
            cur_w += sw
            continue
        w = _char_w(b, size) * len(tok) if False else _char_w(size, b) * len(tok)
        if cur_w + w > avail and current:
            while current and current[-1][0].strip() == "":
                cur_w -= _char_w(size, current[-1][1]) * len(current[-1][0])
                current.pop()
            finalize()
            current.append((tok, b, it))
            cur_w = w
        else:
            current.append((tok, b, it))
            cur_w += w
    finalize()
    if not lines:
        lines.append([])
    return lines


def text_to_pdf(text, title="Verdict"):
    text = _sanitize(text or "")
    title = _sanitize(title or "")

    blocks = _parse_blocks(text)

    visual = []

    if title:
        visual.append({"spans": [(title, True, False)], "size": 15.0, "indent": 0.0, "space_after": 6.0})

    for blk in blocks:
        if blk[0] == "blank":
            visual.append({"spans": [], "size": 11.0, "indent": 0.0, "space_after": 4.0, "blank": True})
            continue
        if blk[0] == "hr":
            visual.append({"spans": [], "size": 11.0, "indent": 0.0, "space_after": 4.0, "hr": True})
            continue
        if blk[0] == "h":
            _, level, content = blk
            size = 14.0 if level <= 1 else (12.5 if level == 2 else 11.5)
            spans = [(t, True, it) for (t, b, it) in _parse_inline(content)]
            visual.append({"spans": spans, "size": size, "indent": 0.0, "space_after": 3.0})
            continue
        if blk[0] == "li":
            _, kind, num, content = blk
            size = 11.0
            prefix = "*  " if kind == "bullet" else (num + ".  ")
            spans = [(prefix, False, False)] + _parse_inline(content)
            visual.append({"spans": spans, "size": size, "indent": 14.0, "space_after": 0.0})
            continue
        if blk[0] == "p":
            _, content = blk
            spans = _parse_inline(content)
            visual.append({"spans": spans, "size": 11.0, "indent": 0.0, "space_after": 4.0})
            continue
        if blk[0] == "table":
            _, header, rows = blk
            visual.append({"type": "table", "header": header, "rows": rows, "size": 8.5, "space_after": 6.0})
            continue

    laid_out = []
    for vl in visual:
        if vl.get("blank"):
            laid_out.append({"spans": [], "size": vl["size"], "indent": 0.0, "blank": True, "space_after": 0.0, "height": 6.0})
            continue
        if vl.get("hr"):
            laid_out.append({"spans": None, "size": vl["size"], "indent": 0.0, "hr": True, "space_after": 4.0, "height": 8.0})
            continue
        if vl.get("type") == "table":
            header = vl["header"]
            rows = vl["rows"]
            size = vl["size"]
            avail = _TEXT_W
            # column widths
            ncols = len(header)
            maxlens = [len(str(h)) for h in header]
            for r in rows:
                for i in range(ncols):
                    if i < len(r):
                        maxlens[i] = max(maxlens[i], len(str(r[i])))
            total = sum(maxlens) or 1
            col_widths = [avail * (ml / total) for ml in maxlens]
            for i in range(ncols):
                col_widths[i] = max(26.0, min(col_widths[i], 180.0))
            s = sum(col_widths)
            if s > avail:
                col_widths = [w * avail / s for w in col_widths]

            def _wrap_cell(txt, w):
                cpl = max(6, int((w - 4) / _char_w(size, False)))
                words = (txt or "").split()
                lines = []
                cur = ""
                for wd in words:
                    if len(cur) + 1 + len(wd) <= cpl:
                        cur = (cur + " " + wd).strip()
                    else:
                        if cur:
                            lines.append(cur)
                        cur = wd
                if cur:
                    lines.append(cur)
                if not lines:
                    lines.append("")
                return lines

            for ri, row in enumerate([header] + rows):
                is_header = (ri == 0)
                cells_lines = []
                src = header if is_header else row
                for i in range(ncols):
                    cell_text = src[i] if i < len(src) else ""
                    cells_lines.append(_wrap_cell(cell_text, col_widths[i]))
                maxlines = max((len(cl) for cl in cells_lines), default=1)
                height = maxlines * (size * 1.3) + 4
                laid_out.append({"table_row": True, "cells_lines": cells_lines,
                                 "col_widths": col_widths, "is_header": is_header,
                                 "size": size, "height": height, "blank": False, "hr": False,
                                 "spans": None, "space_after": 0.0})
            laid_out.append({"spans": [], "size": size, "indent": 0.0, "blank": True,
                            "space_after": vl.get("space_after", 6.0), "height": 6.0})
            continue
        avail = _TEXT_W - vl["indent"]
        wrapped = _wrap_spans(vl["spans"], vl["size"], avail)
        for i, line_spans in enumerate(wrapped):
            laid_out.append({"spans": line_spans, "size": vl["size"], "indent": vl["indent"], "blank": False, "hr": False,
                            "space_after": vl["space_after"] if i == len(wrapped) - 1 else 0.0,
                            "height": vl["size"] * 1.35})

    pages = [[]]
    y = _TOP
    for item in laid_out:
        if item.get("blank"):
            lh = 6.0
            if y - lh < _BOTTOM and pages[-1]:
                pages.append([])
                y = _TOP
            pages[-1].append((item, y))
            y -= lh
            if item.get("space_after"):
                y -= item["space_after"]
            continue
        if item.get("hr"):
            lh = 8.0
            if y - lh < _BOTTOM and pages[-1]:
                pages.append([])
                y = _TOP
            pages[-1].append((item, y))
            y -= lh
            continue
        if item.get("table_row"):
            lh = item["height"]
            if y - lh < _BOTTOM and pages[-1]:
                pages.append([])
                y = _TOP
            pages[-1].append((item, y))
            y -= lh
            if item.get("space_after"):
                y -= item["space_after"]
            continue
        lh = item["size"] * 1.35
        if y - lh < _BOTTOM and pages[-1]:
            pages.append([])
            y = _TOP
        pages[-1].append((item, y))
        y -= lh
        if item.get("space_after"):
            y -= item["space_after"]

    pages = [p for p in pages if p]
    if not pages:
        pages = [[]]

    def font_name(bold, italic):
        if bold and italic:
            return "F4"
        if bold:
            return "F2"
        if italic:
            return "F3"
        return "F1"

    page_streams = []
    for page in pages:
        ops = []
        for item, y in page:
            if item.get("blank"):
                continue
            if item.get("hr"):
                ops.append("q 0.5 w %d %d m %d %d l S Q" % (_MARGIN, y - 2, _PAGE_W - _MARGIN, y - 2))
                continue
            if item.get("table_row"):
                cells_lines = item["cells_lines"]
                col_widths = item["col_widths"]
                size = item["size"]
                is_header = item["is_header"]
                row_h = item["height"]
                x = _MARGIN
                total_w = sum(col_widths)
                if is_header:
                    ops.append("q 0.82 0.82 0.82 rg %d %d %d %d re f Q" % (x, int(y) - int(row_h) + 4, int(total_w), int(row_h) - 4))
                cx = x
                for ci, (cw, lines) in enumerate(zip(col_widths, cells_lines)):
                    ops.append("%d %d %d %d re S" % (int(cx), int(y) - int(row_h) + 4, int(cw), int(row_h) - 4))
                    font = "F2" if is_header else "F1"
                    for j, ln in enumerate(lines):
                        by = int(y) - j * int(size * 1.3) - 2
                        if ln:
                            ops.append("BT /%s %.1f Tf %d %d Td (%s) Tj ET" % (font, size, int(cx) + 2, by, _esc(ln)))
                    cx += cw
                continue
            spans = item["spans"] or []
            size = item["size"]
            indent = item["indent"]
            seq = []
            for txt, b, it in spans:
                if txt == "":
                    continue
                fn = font_name(b, it)
                seq.append("/%s %.1f Tf (%s) Tj" % (fn, size, _esc(txt)))
            if not seq:
                continue
            ops.append("BT %d %d Td %s ET" % (_MARGIN + int(indent), int(y), " ".join(seq)))
        stream = "\n".join(ops)
        page_streams.append(stream.encode("cp1252", errors="replace"))

    n = len(page_streams)
    total = 2 + n + n + 4
    font_start = 2 + n + n + 1
    font_id = {"F1": font_start, "F2": font_start + 1, "F3": font_start + 2, "F4": font_start + 3}

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join("%d 0 R" % (3 + i) for i in range(n))
    objects.append(("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)).encode())
    for i in range(n):
        content_id = 3 + n + i
        page_obj = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d 842] "
            "/Resources << /Font << "
            "/F1 %d 0 R /F2 %d 0 R "
            "/F3 %d 0 R /F4 %d 0 R >> >> "
            "/Contents %d 0 R >>"
        ) % (_PAGE_W, font_id["F1"], font_id["F2"], font_id["F3"], font_id["F4"], content_id)
        objects.append(page_obj.encode())
    for stream in page_streams:
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-BoldOblique /Encoding /WinAnsiEncoding >>")

    out = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % i).encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode()
    out += b"0000000000 65535 f \n"
    for i in range(1, len(objects) + 1):
        out += ("%010d 00000 n \n" % offsets[i]).encode()
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_pos)).encode()
    return out
