import subprocess, sys, json, io
script = sys.argv[1]
exe = r"C:\Program Files\SolidCraft\solidcraft-cli.exe"
out = io.StringIO()
p = subprocess.run([exe, "run", script, "--results"], capture_output=True, text=True, encoding="utf-8", errors="replace")
print("RC", p.returncode)
print("STDERR:", p.stderr[:3000])
open(script.replace(".json", "_stdout.json"), "w", encoding="utf-8").write(p.stdout)
print(p.stdout[-6000:])
