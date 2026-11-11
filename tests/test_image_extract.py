"""image_extract 的 PDF 图片解码测试（手工构造最小 PDF，像素级断言）

背景：旧实现直接把流字节写成 .png（FlateDecode 流是无文件头的裸像素），
产出的全是打不开的坏图。本组测试锁定新行为：
按流元数据重建图片、SMask 合成 alpha、JPEG 直通、坏流跳过不落盘。
"""

import zlib
from io import BytesIO

from PIL import Image

from block import Block
from image_extract import extract_pdf_images
from markdown_writer import render


def _stream_obj(entries: str, data: bytes) -> bytes:
    return f"<< {entries} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"


def _build_pdf(*bodies: bytes) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(bodies) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer << /Size {len(bodies) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def _image_page_pdf(image_entries: str, image_data: bytes, extra_bodies=()) -> bytes:
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
        b"/Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>",
        _stream_obj("", b"q 100 0 0 100 0 0 cm /Im0 Do Q"),
        _stream_obj(f"/Type /XObject /Subtype /Image {image_entries}", image_data),
        *extra_bodies,
    ]
    return _build_pdf(*bodies)


def _extract(tmp_path, pdf_bytes, name="t.pdf"):
    src = tmp_path / name
    src.write_bytes(pdf_bytes)
    blocks = extract_pdf_images(str(src), str(tmp_path / "out.md"))
    return blocks, tmp_path / "images"


# 红 / 绿 / 蓝 / 白，2x2 RGB
PIXELS_2X2_RGB = b"\xff\x00\x00\x00\xff\x00\x00\x00\xff\xff\xff\xff"


class TestPdfImageDecode:
    def test_flate_rgb_reconstructed(self, tmp_path):
        """FlateDecode 裸像素流 → 按元数据重建为可用 PNG，像素一致"""
        pdf = _image_page_pdf(
            "/Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode",
            zlib.compress(PIXELS_2X2_RGB),
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert len(blocks) == 1
        assert blocks[0].image_path == "images/t_p1_0.png"
        assert blocks[0].page == 1
        with Image.open(images_dir / "t_p1_0.png") as image:
            assert image.size == (2, 2)
            assert list(image.convert("RGB").getdata()) == [
                (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255),
            ]

    def test_dct_passthrough_as_jpeg(self, tmp_path):
        """DCTDecode（JPEG）→ 原字节直通保存为 .jpg"""
        buf = BytesIO()
        Image.new("RGB", (4, 3), "blue").save(buf, format="JPEG")
        pdf = _image_page_pdf(
            "/Width 4 /Height 3 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode",
            buf.getvalue(),
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert len(blocks) == 1
        assert blocks[0].image_path.endswith(".jpg")
        with Image.open(images_dir / "t_p1_0.jpg") as image:
            assert image.format == "JPEG"
            assert image.size == (4, 3)

    def test_flate_with_smask_alpha(self, tmp_path):
        """SMask 软蒙版 → 合成为 alpha 通道"""
        smask = _stream_obj(
            "/Type /XObject /Subtype /Image /Width 2 /Height 2"
            " /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode",
            zlib.compress(b"\x00\x80\xff\x40"),
        )
        pdf = _image_page_pdf(
            "/Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8"
            " /Filter /FlateDecode /SMask 6 0 R",
            zlib.compress(b"\xff\x00\x00" * 4),
            extra_bodies=[smask],
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert len(blocks) == 1
        with Image.open(images_dir / "t_p1_0.png") as image:
            assert image.mode == "RGBA"
            assert [pixel[3] for pixel in image.getdata()] == [0, 128, 255, 64]

    def test_dct_with_smask_rebuilt_as_png(self, tmp_path):
        """JPEG + SMask → JPEG 无 alpha，需转 PNG 合成蒙版"""
        buf = BytesIO()
        Image.new("RGB", (2, 2), "red").save(buf, format="JPEG")
        smask = _stream_obj(
            "/Type /XObject /Subtype /Image /Width 2 /Height 2"
            " /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode",
            zlib.compress(b"\xff\xff\xff\xff"),
        )
        pdf = _image_page_pdf(
            "/Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8"
            " /Filter /DCTDecode /SMask 6 0 R",
            buf.getvalue(),
            extra_bodies=[smask],
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert len(blocks) == 1
        with Image.open(images_dir / "t_p1_0.png") as image:
            assert image.format == "PNG"
            assert all(pixel[3] == 255 for pixel in image.getdata())

    def test_indexed_palette(self, tmp_path):
        """Indexed 色空间 → 调色板还原为 RGB"""
        pdf = _image_page_pdf(
            "/Width 2 /Height 1 /BitsPerComponent 8"
            " /ColorSpace [/Indexed /DeviceRGB 1 <00FF00FF0000>]",
            b"\x00\x01",
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert len(blocks) == 1
        with Image.open(images_dir / "t_p1_0.png") as image:
            assert list(image.convert("RGB").getdata()) == [(0, 255, 0), (255, 0, 0)]

    def test_iccbased_colorspace(self, tmp_path):
        """ICCBased 3 分量 → 按 RGB 重建"""
        icc = _stream_obj("/N 3", b"fake icc profile")
        pdf = _image_page_pdf(
            "/Width 2 /Height 1 /BitsPerComponent 8"
            " /ColorSpace [/ICCBased 6 0 R]",
            b"\xff\x00\x00\x00\xff\x00",
            extra_bodies=[icc],
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert len(blocks) == 1
        with Image.open(images_dir / "t_p1_0.png") as image:
            assert list(image.convert("RGB").getdata()) == [(255, 0, 0), (0, 255, 0)]

    def test_unfiltered_gray_default(self, tmp_path):
        """无过滤器、无 ColorSpace → 规范缺省 DeviceGray"""
        pdf = _image_page_pdf(
            "/Width 3 /Height 1 /BitsPerComponent 8",
            b"\x00\x80\xff",
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert len(blocks) == 1
        with Image.open(images_dir / "t_p1_0.png") as image:
            assert list(image.convert("L").getdata()) == [0, 128, 255]

    def test_png_predictor_undone(self, tmp_path):
        """FlateDecode + PNG predictor（15）→ pdfminer 已还原，像素一致"""
        raw = b"".join(b"\x00" + PIXELS_2X2_RGB[i * 6:(i + 1) * 6] for i in range(2))
        pdf = _image_page_pdf(
            "/Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode"
            " /DecodeParms << /Predictor 15 /Colors 3 /Columns 2 /BitsPerComponent 8 >>",
            zlib.compress(raw),
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert len(blocks) == 1
        with Image.open(images_dir / "t_p1_0.png") as image:
            assert list(image.convert("RGB").getdata()) == [
                (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255),
            ]


class TestPdfImageSkip:
    def test_corrupt_stream_skipped_without_file(self, tmp_path):
        """损坏的 FlateDecode 流 → 跳过，不落盘坏文件"""
        pdf = _image_page_pdf(
            "/Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode",
            b"\x00\x01not-zlib-data",
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert blocks == []
        assert list(images_dir.glob("*")) == []

    def test_unknown_filter_skipped(self, tmp_path):
        """未知过滤器（/FooDecode）→ 跳过"""
        pdf = _image_page_pdf(
            "/Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FooDecode",
            b"whatever",
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert blocks == []
        assert list(images_dir.glob("*")) == []

    def test_image_mask_skipped(self, tmp_path):
        """ImageMask 模板蒙版不是常规图片 → 跳过"""
        pdf = _image_page_pdf(
            "/ImageMask true /Width 2 /Height 2 /BitsPerComponent 1 /Filter /FlateDecode",
            zlib.compress(b"\x00\x00"),
        )
        blocks, _ = _extract(tmp_path, pdf)
        assert blocks == []

    def test_unsupported_colorspace_skipped(self, tmp_path):
        """Separation/DeviceN 等无法安全还原的色彩空间 → 跳过"""
        pdf = _image_page_pdf(
            "/Width 2 /Height 2 /ColorSpace /Lab /BitsPerComponent 8",
            b"\x00" * 12,
        )
        blocks, images_dir = _extract(tmp_path, pdf)
        assert blocks == []
        assert list(images_dir.glob("*")) == []


class TestMarkdownImageRefEscaping:
    def test_quotes_space_and_parens(self):
        """空格/括号转义，否则链接在第一个 ) 处截断"""
        md = render([Block(type="image", image_path="images/my file (1).png")])
        assert md == "![](images/my%20file%20%281%29.png)"

    def test_quotes_non_ascii(self):
        """中文文件名 → percent-encoding"""
        md = render([Block(type="image", image_path="images/封面 图.png")])
        assert md == "![](images/%E5%B0%81%E9%9D%A2%20%E5%9B%BE.png)"

    def test_plain_path_unchanged(self):
        """纯 ASCII 路径保持原样（桌面端重命名引用不受影响）"""
        md = render([Block(type="image", image_path="assets_abc/image-0.png")])
        assert md == "![](assets_abc/image-0.png)"
