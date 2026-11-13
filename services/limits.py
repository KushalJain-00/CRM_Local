# services/limits.py — the one place upload/scan size caps live.
# Intake, the folder scan and the API spool all consume these.
MAX_FILE_SIZE = 10 * 1024 * 1024        # per-file bytes
MAX_TOTAL_SIZE = 100 * 1024 * 1024      # per batch bytes
MAX_FILE_COUNT = 50                     # per batch
