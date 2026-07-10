"""Quick database integration test."""
import tempfile
from wiztree_mcp.database import Database

tmpdir_obj = tempfile.TemporaryDirectory()
try:
    db_path = tmpdir_obj.name + "/test.db"
    db = Database(db_path, enable_wal=False)

    try:
        scan_id = db.insert_scan("C:", "2026-07-11T00:00:00", label="Test Scan")
        print(f"Created scan #{scan_id}")

        db.insert_entry(scan_id, "C:\\", 500_000_000_000, 500_000_000_000, None, True, 1, 1, 0)
        db.insert_entry(scan_id, "C:\\file1.bin", 100_000_000_000, 100_000_000_000, "2026-01-01", False, None, None, 1)
        db.insert_entry(scan_id, "C:\\file2.bin", 50_000_000_000, 50_000_000_000, "2026-06-01", False, None, None, 1)
        db.insert_entry(scan_id, "C:\\big_folder\\", 200_000_000_000, 200_000_000_000, None, True, 5, 1, 1)
        db.conn.commit()

        scans = db.list_scans()
        print(f"List scans: {len(scans)} scan(s)")

        summary = db.get_summary(scan_id, top_n=10)
        print(f"Summary: {summary['total_files']} files, {summary['total_folders']} folders")

        rows = db._query_entries(scan_id, kind="files", limit=10)
        print(f"Top files: {len(rows)} entries")

        result = db.search_paths(scan_id, "file")
        print(f"Search 'file': {result['total_matches']} matches, total {result['total_size']} bytes")

        ft = db.file_type_summary(scan_id)
        print(f"File types: {len(ft)} extensions")

        deleted = db.cleanup_scans(keep_latest=1)
        print(f"Cleanup: deleted {len(deleted)} scan(s)")

    finally:
        db.close()

finally:
    try:
        tmpdir_obj.cleanup()
    except Exception:
        pass

print("\nAll database tests passed!")