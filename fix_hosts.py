import sys
hosts_path = r"C:\Windows\System32\drivers\etc\hosts"
content = open(hosts_path, "r", encoding="utf-8").read()
lines = content.split("\n")
new_lines = []
for l in lines:
    s = l.strip()
    if "github" in s.lower() and s.startswith("127.0.0.1") and not s.startswith("#"):
        new_lines.append("# DISABLED_BY_LEAN_SETUP " + l)
    else:
        new_lines.append(l)
open(hosts_path, "w", encoding="utf-8").write("\n".join(new_lines))
print("DONE - all github entries disabled")
