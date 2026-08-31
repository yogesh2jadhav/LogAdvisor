"""Convenience entry point:  python main.py scan --project /path/to/java-spark-project

Installed console scripts `java-log-advisor` / `logadvisor` do the same thing.
"""
from logadvisor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
