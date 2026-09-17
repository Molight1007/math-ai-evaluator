# -*- coding: utf-8 -*-
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = r"D:\挑战杯\output\20260915-cuoti-guiyin\pipeline-state.yaml"
t = io.open(p, encoding="utf-8").read()
t = t.replace("current_stage: S2", "current_stage: S3")
t = t.replace("""  name: doc-formatter
  status: pending
  output_format: html""", """  name: doc-formatter
  status: completed
  route: html
  html_sub: template
  genre: business-report
  html_review_attempts: 1
  html_review_score: 100
  output: stage2/formatted-错题归因分析.html
  output_format: html""")
io.open(p, "w", encoding="utf-8").write(t)
print(t)

r = r"C:\Users\35174\.workbuddy\plugins\cache\workbuddy-builtin\tencent-docx\5.5.6-wb.38337834.g5f969292.h4918b5ced607\skills\html-to-docx"
print("html-to-docx 目录:", sorted(os.listdir(r)))
print("scripts:", sorted(os.listdir(os.path.join(r, "scripts"))))
