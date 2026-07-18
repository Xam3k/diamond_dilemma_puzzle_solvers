"""
Runner that imports and executes analysis.py from within the working directory.
Can be executed with: python run_analysis.py
"""
import subprocess
import sys
import os

os.chdir(r'C:\Users\xavie\coding\diamond-dilemma')
result = subprocess.run([sys.executable, 'analysis.py'], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
