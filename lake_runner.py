import subprocess, os, sys

os.chdir(r"d:\挑战杯\test_mathlib")

# Clean up
for d in [".lake/packages", "lake-packages"]:
    if os.path.exists(d):
        import shutil
        try:
            shutil.rmtree(d, ignore_errors=True)
        except:
            pass

os.makedirs(".lake/packages", exist_ok=True)

log_path = r"d:\挑战杯\test_mathlib\lake_update.log"
done_path = r"d:\挑战杯\test_mathlib\lake_update_done.txt"

with open(log_path, "w", encoding="utf-8") as f:
    f.write("Starting lake update...\n")
    f.flush()

result = subprocess.run(
    ["lake", "update"],
    capture_output=True,
    text=True,
    timeout=7200
)

with open(log_path, "a", encoding="utf-8") as f:
    f.write(f"\n=== Exit code: {result.returncode} ===\n")
    f.write(f"=== STDOUT ===\n{result.stdout}\n")
    f.write(f"=== STDERR ===\n{result.stderr}\n")

with open(done_path, "w") as f:
    f.write(f"EXIT_CODE={result.returncode}")

print(f"DONE: exit_code={result.returncode}")
