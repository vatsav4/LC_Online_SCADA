import os
import sys
import tempfile

# Keep tests away from the real data/ folder (layouts, user accounts, uploads).
os.environ.setdefault("LINE2_DATA_DIR", tempfile.mkdtemp(prefix="line2-test-data-"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "line2_dashboard"))
