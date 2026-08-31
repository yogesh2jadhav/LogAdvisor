import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURE_PROJECT = os.path.join(os.path.dirname(__file__), "fixtures", "sample-spark-project")
