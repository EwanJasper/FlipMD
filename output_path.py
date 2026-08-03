"""输出路径计算与重名保护

- apply_name_template(template, base_name)：应用 {name}/{date}/{seq} 模板
- resolve_unique_output_path(out_dir, name, ext, template)：重名自动加序号
"""

from __future__ import annotations

import os
from datetime import date


def apply_name_template(template: str | None, base_name: str, seq: int = 0) -> str:
    """应用输出文件名模板

    支持变量：
        {name} 源文件名（不含扩展名）
        {date} 当天日期 YYYY-MM-DD
        {seq}  序号（从 0 开始，重名保护时递增）

    template 为空时直接返回 base_name。
    """
    if not template:
        return base_name
    return template.format(
        name=base_name,
        date=date.today().isoformat(),
        seq=seq,
    )


def resolve_unique_output_path(
    out_dir: str | None,
    src_path: str,
    ext: str = ".md",
    template: str | None = None,
) -> str:
    """计算输出路径，遇到重名自动加 _1/_2/...

    :param out_dir: 输出目录（None=与源文件同目录）
    :param src_path: 源文件路径
    :param ext: 输出扩展名（含点，如 .md）
    :param template: 文件名模板（None=用源文件名）
    :return: 不冲突的输出绝对路径
    """
    base = os.path.splitext(os.path.basename(src_path))[0]
    directory = out_dir if out_dir else os.path.dirname(src_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    # 先尝试无序号
    name = apply_name_template(template, base, seq=0)
    candidate = os.path.join(directory or ".", name + ext)
    if not os.path.exists(candidate):
        return candidate

    # 重名则加序号 _1/_2/...
    # 若模板含 {seq}，模板自身负责序号；否则这里追加
    if template and "{seq}" in template:
        # 模板自带序号：递增直到不冲突
        seq = 1
        while True:
            name = apply_name_template(template, base, seq=seq)
            candidate = os.path.join(directory or ".", name + ext)
            if not os.path.exists(candidate):
                return candidate
            seq += 1
            if seq > 9999:
                # 防御性兜底
                return candidate
    else:
        seq = 1
        while True:
            candidate = os.path.join(directory or ".", f"{name}_{seq}{ext}")
            if not os.path.exists(candidate):
                return candidate
            seq += 1
            if seq > 9999:
                return candidate
