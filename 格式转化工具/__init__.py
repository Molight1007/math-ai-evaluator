"""
题目转化工具 - PDF/Word -> JSON 格式转换。
包含 PDF 文本提取和 Word 段落解析两大模块。
"""
from .convert import main as convert_main
from .pdf_to_json import convert_pdf
from .docx_to_json import convert_docx
