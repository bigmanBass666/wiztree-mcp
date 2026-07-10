"""Test CSV importer with a small fixture."""
import os
import csv
import tempfile

from wiztree_mcp.database import Database
from wiztree_mcp.csv_importer import import_csv, find_header_offset, resolve_columns, parse_size, compute_depth

# ── Utility function tests ───────────────────────────────────────────

assert parse_size("123") == 123
assert parse_size("1,234") == 1234
assert parse_size("") == 0
assert parse_size("abc") == 0
print("parse_size: OK")

assert compute_depth("C:") == 0
assert compute_depth("C:\\") == 0
assert compute_depth("C:\\Windows") == 1
assert compute_depth("C:\\Windows\\System32") == 2
assert compute_depth("C:\\Windows\\System32\\") == 2
print("compute_depth: OK")

# ── Header detection tests ───────────────────────────────────────────

fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
csv_path = os.path.join(fixtures_dir, "sample_scan.csv")

with open(csv_path, encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    header = find_header_offset(reader)
    assert header is not None, "Header not found"
    header_row, skipped = header
    print(f"find_header_offset: found header at offset {skipped}: {header_row}")

    idxs = resolve_columns(header_row)
    path_idx, size_idx, allocated_idx, modified_idx, files_idx, folders_idx, _ = idxs
    assert path_idx == 0
    assert size_idx == 1
    assert allocated_idx == 2
    assert modified_idx == 3
    assert files_idx == 4
    assert folders_idx == 5
    print("resolve_columns: OK")

# ── Full CSV import + query tests ────────────────────────────────────

tmpdir_obj = tempfile.TemporaryDirectory()
try:
    tmpdir = tmpdir_obj.name
    db_path = os.path.join(tmpdir, "test.db")
    db = Database(db_path, enable_wal=False)

    try:
        scan_id = db.insert_scan("C:", "2026-07-11T00:00:00", label="Import Test")
        stats = import_csv(db, scan_id, csv_path)

        print(f"\nImport stats: {stats}")
        assert stats["rows"] == 8, f"Expected 8 rows, got {stats['rows']}"
        assert stats["files"] == 4, f"Expected 4 files, got {stats['files']}"
        assert stats["folders"] == 4, f"Expected 4 folders (including root), got {stats['folders']}"
        assert stats["errors"] == 0, f"Expected 0 errors, got {stats['errors']}"

        # Verify queries
        summary = db.get_summary(scan_id, top_n=10)
        print(f"Summary: {summary['total_files']} files, {summary['total_folders']} folders")

        top_files = db._query_entries(scan_id, kind="files", limit=10)
        print(f"Top files: {len(top_files)} entries")
        for f in top_files:
            print(f"  {f['path']}: {f['size']} bytes")

        result = db.search_paths(scan_id, "large_file")
        print(f"Search 'large_file': {result['total_matches']} matches")

        entries = db.drill_down(scan_id, "C:\\Users\\")
        print(f"Drill down C:\\Users\\: {len(entries)} entries")

        ft = db.file_type_summary(scan_id)
        print(f"File types: {len(ft)} types")

        old = db.large_old_files(scan_id, older_than_days=365, min_size=1)
        print(f"Large old files (>365 days): {len(old)} files")

    finally:
        db.close()

finally:
    try:
        tmpdir_obj.cleanup()
    except Exception:
        pass

print("\nAll CSV importer tests passed!")