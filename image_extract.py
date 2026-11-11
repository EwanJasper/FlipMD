"""图片提取模块

PDF：用 pdfplumber 的 page.images 定位图片流，按流元数据
（Width/Height/BitsPerComponent/ColorSpace/SMask）重建为真实图片文件；
JPEG（DCTDecode）原字节直通。无法安全解码的图片跳过并记日志，绝不落盘坏文件。
Word：遍历 doc.inline_shapes + 表格内嵌图片，同样导出 + 引用

返回 Block(type="image", image_path="images/xxx.png") 列表，
由 markdown_writer.render 渲染为 ![](images/xxx.png)。
"""

from __future__ import annotations

import logging
import os
from io import BytesIO

from pdfminer.pdfparser import PDFStream
from pdfminer.pdftypes import resolve1
from pdfminer.psparser import PSLiteral

from block import Block

# 过滤器名称（含 PDF 中的缩写）
_FLATE_FILTERS = {"FlateDecode", "Fl", "F"}
_LZW_FILTERS = {"LZWDecode", "LZW"}
_ASCII_FILTERS = {"ASCII85Decode", "A85", "ASCIIHexDecode", "AHx", "RunLengthDecode", "RL"}
_DCT_FILTERS = {"DCTDecode", "DCT"}
_JPX_FILTERS = {"JPXDecode", "JPX"}
_JBIG2_FILTERS = {"JBIG2Decode", "JBIG2"}
# Flate/LZW/ASCII 系/无过滤：get_data() 返回原始样本（pdfminer 已处理 predictor）
_RAW_SAMPLE_FILTERS = _FLATE_FILTERS | _LZW_FILTERS | _ASCII_FILTERS

# 简单色彩空间 → (分量数, PIL 模式)；Lab/Separation/DeviceN 等无法安全还原，跳过
_DEVICE_COLORSPACES = {
    "DeviceGray": (1, "L"), "G": (1, "L"), "CalGray": (1, "L"),
    "DeviceRGB": (3, "RGB"), "RGB": (3, "RGB"), "CalRGB": (3, "RGB"),
    "DeviceCMYK": (4, "CMYK"), "CMYK": (4, "CMYK"),
}
_ICCBASED_MODES = {1: (1, "L"), 3: (3, "RGB"), 4: (4, "CMYK")}


def extract_pdf_images(pdf_path: str, output_md_path: str) -> list[Block]:
    """提取 PDF 所有页面的图片，返回 image Block 列表

    图片导出到 output_md_path 同级的 images/ 目录。
    Block.image_path 是相对 output_md_path 的路径（如 "images/page3_0.png"）。
    """
    import pdfplumber

    images_dir = os.path.join(os.path.dirname(output_md_path) or ".", "images")
    os.makedirs(images_dir, exist_ok=True)

    blocks: list[Block] = []
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    failed_count = 0

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                for img_idx, img in enumerate(page.images):
                    stream = img.get("stream")
                    if stream is None:
                        continue
                    try:
                        decoded = _decode_pdf_image(stream)
                    except Exception as exc:  # pdfminer 对未知过滤器/损坏流抛异常
                        decoded = None
                        reason = str(exc) or type(exc).__name__
                    else:
                        reason = "无法识别的图片编码"
                    if decoded is None:
                        failed_count += 1
                        logging.info("PDF 第%d页第%d张图片跳过（%s）", page_num, img_idx, reason)
                        continue
                    img_bytes, ext = decoded
                    fname = f"{base_name}_p{page_num}_{img_idx}.{ext}"
                    fpath = os.path.join(images_dir, fname)
                    with open(fpath, "wb") as f:
                        f.write(img_bytes)
                    blocks.append(Block(
                        type="image",
                        y_top=float(img.get("top", page_num * 1000)),
                        page=page_num,
                        image_path=f"images/{fname}",
                    ))
    except Exception as e:
        logging.warning("PDF 图片提取中断（返回已提取的 %d 张）: %s", len(blocks), e)
        return blocks

    if failed_count:
        logging.info("PDF 图片提取完成: 成功 %d 张, 跳过 %d 张", len(blocks), failed_count)
    return blocks


def _decode_pdf_image(stream) -> tuple[bytes, str] | None:
    """将 PDF 图片流解码为 (图片文件字节, 扩展名)；无法安全解码时返回 None"""
    from PIL import Image

    if not isinstance(stream, PDFStream):
        return None
    attrs = stream.attrs
    # 宽高缺失或非法无法重建
    width, height = _int(resolve1(attrs.get("Width"))), _int(resolve1(attrs.get("Height")))
    if not width or not height:
        return None
    # 模板蒙版（1bpc 掩码）不是常规图片
    if resolve1(attrs.get("ImageMask")):
        return None
    # Decode 反转阵列只接受全 [0 1]，其余色彩语义不明
    decode = resolve1(attrs.get("Decode"))
    if decode and any((lo, hi) != (0, 1) for lo, hi in _pairs(decode)):
        return None

    names = {f.name for f, _ in stream.get_filters()}
    data = stream.get_data()  # JPEG/JPX/JBIG2 原样直通；未知过滤器抛 NotImplementedError

    smask = resolve1(attrs.get("SMask"))
    if names & _DCT_FILTERS and not isinstance(smask, PDFStream):
        return data, "jpg"
    if names & (_DCT_FILTERS | _JPX_FILTERS | _JBIG2_FILTERS):
        # JPEG 带 SMask 或 JPX/JBIG2：交给 PIL 试开，开不了就跳过
        try:
            image = Image.open(BytesIO(data)).convert("RGB")
        except Exception:
            return None
        return _png_bytes(_apply_smask(image, smask)), "png"
    if not names or names <= _RAW_SAMPLE_FILTERS:
        image = _samples_to_image(data, attrs, width, height)
        if image is None:
            return None
        return _png_bytes(image), "png"
    return None  # 未知过滤器组合


def _samples_to_image(data: bytes, attrs, width: int, height: int):
    """由解码后的原始样本重建 PIL Image，失败返回 None"""
    from PIL import Image

    bpc = _int(resolve1(attrs.get("BitsPerComponent"))) or 8
    ncomp, mode = _colorspace_info(resolve1(attrs.get("ColorSpace")))
    if mode is None or bpc not in (1, 8):
        return None  # 索引色以外的 2/4 bit 不支持
    row_bytes = width * ncomp if bpc == 8 else (width * bpc + 7) // 8
    expected = row_bytes * height
    if len(data) < expected:
        return None
    if len(data) > expected:
        data = data[:expected]  # 容忍尾部冗余字节
    try:
        if mode == "P":
            palette = _indexed_palette(resolve1(attrs.get("ColorSpace")))
            if palette is None:
                return None
            image = Image.frombytes("P", (width, height), data)
            image.putpalette(palette)
            image = image.convert("RGB")
        else:
            image = Image.frombytes(mode, (width, height), data)
            if mode == "CMYK":
                image = image.convert("RGB")  # 浏览器不渲染 CMYK PNG
    except Exception:
        return None
    return _apply_smask(image, resolve1(attrs.get("SMask")))


def _apply_smask(image, smask):
    """把软蒙版（SMask）合成为 alpha 通道；蒙版不可用时返回原图（不透明）"""
    from PIL import Image

    if not isinstance(smask, PDFStream):
        return image
    alpha = smask.get_data()
    width, height = _int(resolve1(smask.attrs.get("Width"))), _int(resolve1(smask.attrs.get("Height")))
    if not width or not height or len(alpha) != width * height:
        return image  # 蒙版尺寸/位深不符，放弃 alpha 而不是输出错图
    mask = Image.frombytes("L", (width, height), alpha)
    if mask.size != image.size:
        mask = mask.resize(image.size)
    result = image.convert("RGBA")
    result.putalpha(mask)
    return result


def _colorspace_info(cs) -> tuple[int, str | None]:
    """色彩空间 → (分量数, PIL 模式)；无法安全识别返回 (0, None)"""
    if cs is None:
        return 1, "L"  # PDF 规范缺省 DeviceGray
    if isinstance(cs, PSLiteral):
        return _DEVICE_COLORSPACES.get(cs.name, (0, None))
    if isinstance(cs, (list, tuple)) and cs:
        head = resolve1(cs[0])
        if isinstance(head, PSLiteral):
            if head.name == "ICCBased":
                n = _int(resolve1(getattr(resolve1(cs[1]), "attrs", {}).get("N")))
                return _ICCBASED_MODES.get(n, (0, None))
            if head.name == "Indexed":
                return (1, "P") if _colorspace_info(resolve1(cs[1])) == (3, "RGB") else (0, None)
    return (0, None)


def _indexed_palette(cs) -> bytes | None:
    """Indexed 色空间 → RGB 调色板字节；结构不符返回 None"""
    if not (isinstance(cs, (list, tuple)) and len(cs) >= 4):
        return None
    hival = _int(resolve1(cs[2]))
    if hival is None:
        return None
    lookup = resolve1(cs[3])
    if isinstance(lookup, PDFStream):
        lookup = lookup.get_data()
    if not isinstance(lookup, (bytes, bytearray)):
        return None
    palette = bytes(lookup[: (hival + 1) * 3])
    return palette if palette and len(palette) % 3 == 0 else None


def _pairs(decode) -> list[tuple]:
    """Decode 阵列 → [(min, max), ...]；长度非法视为无反转"""
    if len(decode) % 2:
        return []
    return [(decode[i], decode[i + 1]) for i in range(0, len(decode), 2)]


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _png_bytes(image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def extract_docx_images(docx_path: str, output_md_path: str) -> list[Block]:
    """提取 Word 文档中的图片（inline_shapes + 表格内图片）

    Word 的图片没有 y 坐标信息，按文档顺序估算 y_top（按遍历顺序递增）。
    """
    from docx import Document
    from docx.oxml.ns import qn

    images_dir = os.path.join(os.path.dirname(output_md_path) or ".", "images")
    os.makedirs(images_dir, exist_ok=True)

    blocks: list[Block] = []
    base_name = os.path.splitext(os.path.basename(docx_path))[0]
    order = 0
    failed_count = 0

    try:
        doc = Document(docx_path)
        # 收集所有图片关系（rId -> image part）
        rels = {rId: r for rId, r in doc.part.rels.items() if "image" in r.reltype}

        # 遍历 body 子元素，按顺序提取 blip 引用
        seen_rids: set[str] = set()
        for blip_idx, blip in enumerate(doc.element.body.iter(qn("a:blip"))):
            rid = blip.get(qn("r:embed"))
            if not rid or rid not in rels:
                continue
            if rid in seen_rids:
                # 同一图片被多次引用：仍导出一份，避免遗漏（docx 内同 rId 多引用较少）
                pass
            seen_rids.add(rid)
            try:
                image_part = rels[rid].target_part
                img_bytes = image_part.blob
                # 从 content_type 推断扩展名
                ct = image_part.content_type or ""
                if "png" in ct:
                    ext = "png"
                elif "jpeg" in ct or "jpg" in ct:
                    ext = "jpg"
                elif "gif" in ct:
                    ext = "gif"
                elif "bmp" in ct:
                    ext = "bmp"
                else:
                    ext = "png"
                fname = f"{base_name}_{blip_idx}.{ext}"
                fpath = os.path.join(images_dir, fname)
                with open(fpath, "wb") as f:
                    f.write(img_bytes)
                blocks.append(Block(
                    type="image",
                    y_top=float(order),
                    image_path=f"images/{fname}",
                ))
                order += 1
            except Exception as e:
                failed_count += 1
                logging.warning("Word 第%d张图片提取失败: %s", blip_idx, e)
                continue
    except Exception as e:
        logging.warning("Word 图片提取中断（返回已提取的 %d 张）: %s", len(blocks), e)
        return blocks

    if failed_count:
        logging.info("Word 图片提取完成: 成功 %d 张, 失败 %d 张", len(blocks), failed_count)
    return blocks


def extract_images(src_path: str, output_md_path: str) -> list[Block]:
    """根据扩展名分发到 PDF/Word 图片提取"""
    ext = os.path.splitext(src_path)[1].lower()
    if ext == ".pdf":
        return extract_pdf_images(src_path, output_md_path)
    if ext == ".docx":
        return extract_docx_images(src_path, output_md_path)
    return []
