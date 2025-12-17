import subprocess
import sys


def run(module: str):
    cmd = [sys.executable, "-m", module]
    print(f"\n=== Running: {' '.join(cmd)} ===")
    subprocess.run(cmd, check=True)


def main():
    run("src.ingest.fetch")
    run("src.ingest.pages")
    run("src.ingest.chunk")

if __name__ == "__main__":
    main()