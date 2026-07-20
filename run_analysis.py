"""
Runner that imports and executes analysis.py from within the working directory.
Can be executed with: python run_analysis.py
"""
import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
result = subprocess.run([sys.executable, 'analysis.py'], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
