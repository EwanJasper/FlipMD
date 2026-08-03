"""图片提取模块

PDF：用 pdfplumber 的 page.images 提取图片，导出到 <output>/images/
Word：遍历 doc.inline_shapes + 表格内嵌图片，同样导出 + 引用

返回 Block(type="image", image_path="images/xxx.png") 列表，
由 markdown_writer.render 渲染为 ![](images/xxx.png)。
"""

from __future__ import annotations

import logging
import os

from block import Block


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
                # page.images 返回 dict 列表，含 stream/name/embedded_image
                for img_idx, img in enumerate(page.images):
                    try:
                        # 优先用 page.extract_image（pdfplumber 0.10+）
                        extracted = page.extract_image(
                            x0=img.get("x0"), y0=img.get("top"),
                            x1=img.get("x1"), y1=img.get("bottom"),
                        ) if hasattr(page, "extract_image") else None
                        if extracted and "image" in extracted:
                            img_bytes = extracted["image"]
                            ext = extracted.get("ext", "png")
                        else:
                            # 退路：直接访问 stream
                            stream = img.get("stream")
                            if stream is None:
                                continue
                            img_bytes = stream.get_data()
                            ext = "png"
                        # 保存
                        fname = f"{base_name}_p{page_num}_{img_idx}.{ext}"
                        fpath = os.path.join(images_dir, fname)
                        with open(fpath, "wb") as f:
                            f.write(img_bytes)
                        blocks.append(Block(
                            type="image",
                            y_top=float(img.get("top", page_num * 1000)),
                            image_path=f"images/{fname}",
                        ))
                    except Exception as e:
                        failed_count += 1
                        logging.warning("PDF 第%d页第%d张图片提取失败: %s", page_num, img_idx, e)
                        continue
    except Exception as e:
        logging.warning("PDF 图片提取中断（返回已提取的 %d 张）: %s", len(blocks), e)
        return blocks

    if failed_count:
        logging.info("PDF 图片提取完成: 成功 %d 张, 失败 %d 张", len(blocks), failed_count)
    return blocks


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
