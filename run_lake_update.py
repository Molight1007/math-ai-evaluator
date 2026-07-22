import subprocess
import sys
import os
from datetime import datetime

os.chdir(r"d:\挑战杯\test_mathlib")

# Clean up any stale state
for d in [".lake/packages", "lake-packages"]:
    if os.path.exists(d):
        import shutil
        try:
            if os.path.isdir(d):
                shutil.rmtree(d)
            else:
                os.remove(d)
        except:
            pass

# Create packages dir
os.makedirs(".lake/packages", exist_ok=True)

log_path = r"d:\挑战杯\test_mathlib\lake_update.log"
start_time = datetime.now()
with open(log_path, "w", encoding="utf-8") as f:
    f.write(f"=== lake update started at {start_time} ===\n")

result = subprocess.run(
    ["lake", "update"],
    capture_output=True,
    text=True,
    timeout=3600  # 1 hour timeout
)

end_time = datetime.now()
duration = (end_time - start_time).total_seconds()

with open(log_path, "a", encoding="utf-8") as f:
    f.write(f"\n=== lake update finished at {end_time} ===\n")
    f.write(f"=== Duration: {duration:.0f} seconds ===\n")
    f.write(f"=== Exit code: {result.returncode} ===\n")
    f.write(f"\n=== STDOUT ===\n{result.stdout}\n")
    f.write(f"\n=== STDERR ===\n{result.stderr}\n")

# Write result marker
with open(r"d:\挑战杯\test_mathlib\lake_update_done.txt", "w") as f:
    f.write(f"SUCCESS:{result.returncode}" if result.returncode == 0 else f"FAILED:{result.returncode}")

print(f"Done. Exit code: {result.returncode}, Duration: {duration:.0f}s")
