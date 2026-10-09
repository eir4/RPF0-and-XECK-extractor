import os
import sys
import csv
import re
import time
from pathlib import Path


class MagiListener:
    """
    MAGI Subprocess Listener (magi.py)
    
    Reads real-time execution events from standard input pipe (sys.stdin),
    parses event types and timestamps, and flushes results instantly to:
      1. Plain text execution log (.log)
      2. Structured event spreadsheet (.csv)
      3. Summary report document (.txt / .md)
    """

    # Matches: [YYYY-MM-DD HH:MM:SS] [EVENT_TYPE] Details message
    LOG_PATTERN = re.compile(r"^\[(.*?)\]\s+\[(.*?)\]\s+(.*)$")

    def __init__(self, log_dir_path: str):
        self.log_dir = Path(log_dir_path)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Output File Paths
        self.txt_log_path = self.log_dir / "magi_execution.log"
        self.csv_report_path = self.log_dir / "magi_events_manifest.csv"
        self.doc_report_path = self.log_dir / "magi_summary_report.txt"

        # Tracking Statistics
        self.start_time = time.time()
        self.event_counts = {}
        self.checkpoint_history = []
        self.errors = []
        self.warnings = []

        self._init_csv_header()

    def _init_csv_header(self):
        """Initializes the CSV spreadsheet with headers if it doesn't exist."""
        if not self.csv_report_path.exists():
            with open(self.csv_report_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "Event_Category", "Severity", "Details"])
                f.flush()
                os.fsync(f.fileno())

    def _determine_severity(self, event_type: str) -> str:
        """Classifies events into severity categories for spreadsheet filtering."""
        if "ERROR" in event_type:
            return "CRITICAL"
        if "WARN" in event_type:
            return "WARNING"
        if event_type in ("CHECKPOINT", "MAP_DONE", "CSV_DONE"):
            return "MILESTONE"
        return "INFO"

    def process_line(self, line: str):
        """Parses an incoming pipe line and appends to real-time reports."""
        line = line.strip()
        if not line:
            return

        match = self.LOG_PATTERN.match(line)
        if match:
            timestamp, event_type, details = match.groups()
        else:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            event_type = "RAW_PIPE"
            details = line

        severity = self._determine_severity(event_type)

        # 1. Update Metrics
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        if severity == "CRITICAL":
            self.errors.append(f"[{timestamp}] {details}")
        elif severity == "WARNING":
            self.warnings.append(f"[{timestamp}] {details}")
        elif event_type == "CHECKPOINT":
            self.checkpoint_history.append((timestamp, details))

        # 2. Append to Real-Time Plain Text Log
        with open(self.txt_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{severity}] [{event_type}] {details}\n")
            f.flush()
            os.fsync(f.fileno())

        # 3. Append to CSV Spreadsheet
        with open(self.csv_report_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, event_type, severity, details])
            f.flush()
            os.fsync(f.fileno())

    def generate_summary_document(self):
        """Generates a formatted summary report document upon completion or shutdown."""
        elapsed = round(time.time() - self.start_time, 2)
        
        with open(self.doc_report_path, "w", encoding="utf-8") as f:
            f.write("====================================================\n")
            f.write("          MAGI PROCESS EXECUTION SUMMARY            \n")
            f.write("====================================================\n\n")
            f.write(f"Generated On       : {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Runtime      : {elapsed} seconds\n")
            f.write(f"Log Directory      : {self.log_dir.resolve()}\n\n")

            f.write("--- EVENT BREAKDOWN ---\n")
            for evt, count in sorted(self.event_counts.items()):
                f.write(f"  * {evt:<18}: {count}\n")
            f.write("\n")

            f.write("--- MILESTONES & CHECKPOINTS ---\n")
            if self.checkpoint_history:
                for ts, chk in self.checkpoint_history:
                    f.write(f"  [{ts}] {chk}\n")
            else:
                f.write("  No checkpoints recorded.\n")
            f.write("\n")

            f.write("--- WARNINGS & ERRORS ---\n")
            f.write(f"  Total Warnings: {len(self.warnings)}\n")
            f.write(f"  Total Errors  : {len(self.errors)}\n")
            if self.warnings:
                f.write("\n  Warnings List:\n")
                for w in self.warnings:
                    f.write(f"    - {w}\n")
            if self.errors:
                f.write("\n  Errors List:\n")
                for e in self.errors:
                    f.write(f"    - {e}\n")

            f.write("\n====================================================\n")
            f.write("               END OF MAGI REPORT                   \n")
            f.write("====================================================\n")
            f.flush()
            os.fsync(f.fileno())

    def listen(self):
        """Main loop: listens on stdin until pipe is closed by Katsuragi."""
        try:
            for line in sys.stdin:
                self.process_line(line)
                if "SHUTDOWN" in line:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self.generate_summary_document()


if __name__ == "__main__":
    # Target directory passed as sys.argv[1] by KatsuragiMain
    target_log_dir = sys.argv[1] if len(sys.argv) > 1 else "./magi_logs"
    listener = MagiListener(target_log_dir)
    listener.listen()
