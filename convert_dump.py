"""
MySQL Dump Converter
====================
Converts a raw mysqldump file into a clean SQL dump with explicit column names.
Reads CREATE TABLE statements from the dump itself to extract column mappings.
Fully independent - no external dependencies or project knowledge needed.

Usage:
    python convert_dump.py <input_dump.sql> <output_dump.sql>

Arguments:
    input_dump.sql   - Raw mysqldump file
    output_dump.sql  - Output file path (clean dump with column names)

Example:
    python convert_dump.py raw_dump.sql clean_dump.sql
"""

import sys
import os
import re


def strip_backticks(name):
    """Remove backticks from identifiers"""
    return name.strip('`')


def extract_create_body(content, start_pos):
    """Extract the full body of a CREATE TABLE by tracking parenthesis depth.
    start_pos should point to the opening '(' of the column definitions.
    Returns the content between the outermost parentheses."""
    depth = 0
    in_quote = False
    escape_next = False
    body_start = None
    pos = start_pos

    while pos < len(content):
        c = content[pos]
        if escape_next:
            escape_next = False
            pos += 1
            continue
        if c == '\\':
            escape_next = True
        elif c == "'" and not in_quote:
            in_quote = True
        elif c == "'" and in_quote:
            in_quote = False
        elif not in_quote:
            if c == '(':
                if depth == 0:
                    body_start = pos + 1
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return content[body_start:pos]
        pos += 1
    return None


def parse_create_tables(content):
    """Extract column names from CREATE TABLE statements in the dump.
    Returns {table_name: [col1, col2, ...]}"""
    table_columns = {}
    header_pattern = re.compile(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\(',
        re.IGNORECASE
    )

    for match in header_pattern.finditer(content):
        table_name = strip_backticks(match.group(1))
        # Position of the opening '(' at end of match
        paren_pos = match.end() - 1
        body = extract_create_body(content, paren_pos)
        if body is None:
            continue

        columns = []
        for line in body.split('\n'):
            line = line.strip().rstrip(',')
            if not line:
                continue
            # Skip constraints, keys, indexes
            upper = line.upper().lstrip()
            if any(upper.startswith(kw) for kw in [
                'PRIMARY KEY', 'UNIQUE KEY', 'KEY ', 'INDEX ',
                'CONSTRAINT', 'FOREIGN KEY', 'CHECK ', 'FULLTEXT',
                'SPATIAL', ')'
            ]):
                continue
            # Match column definition: `col_name` type ... or col_name type ...
            col_match = re.match(r'`?(\w+)`?\s+\w+', line)
            if col_match:
                columns.append(col_match.group(1))

        if columns:
            table_columns[table_name] = columns

    return table_columns


def extract_table_name(sql):
    """Extract table name from INSERT/REPLACE statement"""
    match = re.search(r'(?:INSERT|REPLACE)\s+INTO\s+`?(\w+)`?', sql, re.IGNORECASE)
    return match.group(1) if match else None


def has_column_list(sql):
    """Check if INSERT already has explicit column names: INSERT INTO table (col1, col2)"""
    match = re.search(
        r'(?:INSERT|REPLACE)\s+INTO\s+`?\w+`?\s*\(',
        sql, re.IGNORECASE
    )
    if not match:
        return False
    # Check if what follows the ( looks like column names, not values
    after = sql[match.end() - 1:]  # includes the opening (
    # If it starts with (value, value) it's VALUES directly
    # If it starts with (col_name, col_name) VALUES ... it's column list
    values_pos = re.search(r'\)\s*VALUES\s*\(', after, re.IGNORECASE)
    return values_pos is not None


def parse_rows(values_str):
    """Parse multi-value INSERT: (v1,v2),(v3,v4) -> list of row content strings"""
    rows = []
    pos = 0
    while pos < len(values_str):
        if values_str[pos] == '(':
            depth = 1
            start = pos
            in_quote = False
            escape_next = False
            pos += 1
            while pos < len(values_str) and depth > 0:
                c = values_str[pos]
                if escape_next:
                    escape_next = False
                elif c == '\\':
                    escape_next = True
                elif c == "'" and not in_quote:
                    in_quote = True
                elif c == "'" and in_quote:
                    in_quote = False
                elif not in_quote:
                    if c == '(':
                        depth += 1
                    elif c == ')':
                        depth -= 1
                pos += 1
            rows.append(values_str[start + 1:pos - 1])
        else:
            pos += 1
    return rows


def count_row_values(row):
    """Count number of values in a row string"""
    count = 1
    in_quote = False
    escape_next = False
    for c in row:
        if escape_next:
            escape_next = False
            continue
        if c == '\\':
            escape_next = True
        elif c == "'":
            in_quote = not in_quote
        elif c == ',' and not in_quote:
            count += 1
    return count


def trim_extra_columns(rows, expected_count):
    """Remove trailing columns from each row if dump has more than table expects"""
    new_rows = []
    for row in rows:
        actual = count_row_values(row)
        if actual <= expected_count:
            new_rows.append(row)
            continue

        trimmed = row
        for _ in range(actual - expected_count):
            in_quote = False
            escape_next = False
            last_comma = -1
            for j, c in enumerate(trimmed):
                if escape_next:
                    escape_next = False
                    continue
                if c == '\\':
                    escape_next = True
                elif c == "'":
                    in_quote = not in_quote
                elif c == ',' and not in_quote:
                    last_comma = j
            if last_comma > 0:
                trimmed = trimmed[:last_comma]
        new_rows.append(trimmed)
    return new_rows


def is_skip_line(line):
    """Check if a line should be skipped (MySQL directives, procedures, etc.)"""
    upper = line.upper().strip()
    skip_starts = [
        'LOCK TABLES', 'UNLOCK TABLES',
        'SET @MYSQLDUMP', 'SET @@SESSION', 'SET @@GLOBAL',
        'DELIMITER', 'SET ',
    ]
    for s in skip_starts:
        if upper.startswith(s):
            return True
    if line.strip().startswith('/*!'):
        return True
    if any(kw in upper for kw in [
        'CREATE TABLE', 'DROP TABLE',
        'CREATE PROCEDURE', 'CREATE DEFINER', 'DROP PROCEDURE',
        'CREATE DATABASE', 'USE '
    ]):
        return True
    if upper.strip() in ('BEGIN', 'END', 'END;'):
        return True
    return False


def process_dump(input_path, output_path, table_columns):
    """Process the dump file: clean it and add column names to INSERTs"""
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    output_lines = []
    tables_processed = []
    tables_trimmed = []
    tables_passed = []
    tables_skipped = []
    i = 0
    in_procedure = False
    in_create = False

    while i < len(lines):
        line = lines[i].rstrip('\n').rstrip('\r')
        stripped = line.strip()

        # Skip DELIMITER blocks (stored procedures)
        if 'DELIMITER' in stripped.upper() and not stripped.startswith('--'):
            in_procedure = not in_procedure
            i += 1
            continue
        if in_procedure:
            i += 1
            continue

        # Skip CREATE TABLE blocks
        if re.match(r'CREATE\s+TABLE', stripped, re.IGNORECASE):
            in_create = True
            i += 1
            continue
        if in_create:
            if stripped.endswith(';'):
                in_create = False
            i += 1
            continue

        # Keep section comments
        if stripped.startswith('--'):
            if re.search(r'Dumping data for table', stripped):
                if output_lines and output_lines[-1] != '':
                    output_lines.append('')
                output_lines.append(stripped)
            elif 'Dump completed' in stripped:
                if output_lines and output_lines[-1] != '':
                    output_lines.append('')
                output_lines.append(stripped)
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        if is_skip_line(stripped):
            i += 1
            continue

        # Handle INSERT/REPLACE statements
        upper_stripped = stripped.upper()
        if upper_stripped.startswith('INSERT INTO') or upper_stripped.startswith('REPLACE INTO'):
            full_statement = stripped
            while not full_statement.rstrip().endswith(';'):
                i += 1
                if i >= len(lines):
                    break
                full_statement += '\n' + lines[i].rstrip('\n').rstrip('\r')

            table_name = extract_table_name(full_statement)

            # If INSERT already has column names, keep as-is (just strip backticks from table name)
            if has_column_list(full_statement):
                # Clean up: remove backticks from table name
                clean = re.sub(
                    r'(INSERT\s+INTO\s+)`(\w+)`',
                    r'\1\2',
                    full_statement,
                    count=1,
                    flags=re.IGNORECASE
                )
                output_lines.append(clean)
                tables_passed.append(table_name)
                i += 1
                continue

            # INSERT without column names - add them from CREATE TABLE
            if table_name and table_name in table_columns:
                col_list = table_columns[table_name]
                col_str = ', '.join(col_list)
                expected_count = len(col_list)

                values_match = re.search(r'\bVALUES\s*', full_statement, re.IGNORECASE)
                if values_match:
                    values_str = full_statement[values_match.end():].rstrip(';').strip()
                    rows = parse_rows(values_str)

                    if rows:
                        first_count = count_row_values(rows[0])
                        if first_count > expected_count:
                            rows = trim_extra_columns(rows, expected_count)
                            tables_trimmed.append(f"{table_name} ({first_count} -> {expected_count} columns)")

                        values_rebuilt = ','.join(f'({r})' for r in rows)
                        output_lines.append(f"INSERT INTO {table_name} ({col_str}) VALUES {values_rebuilt};")
                        tables_processed.append(table_name)
                    else:
                        tables_skipped.append(f"{table_name} (no rows parsed)")
                else:
                    tables_skipped.append(f"{table_name} (no VALUES clause)")
            elif table_name:
                tables_skipped.append(f"{table_name} (no CREATE TABLE found)")

            i += 1
            continue

        i += 1

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))
        if output_lines and output_lines[-1] != '':
            f.write('\n')

    print(f"\nConversion complete!")
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_path}")
    if tables_processed:
        print(f"\n  Column names added ({len(tables_processed)}):")
        for t in tables_processed:
            print(f"    + {t}")
    if tables_passed:
        print(f"\n  Already had columns ({len(tables_passed)}):")
        for t in tables_passed:
            print(f"    = {t}")
    if tables_trimmed:
        print(f"\n  Columns auto-trimmed:")
        for t in tables_trimmed:
            print(f"    ~ {t}")
    if tables_skipped:
        print(f"\n  Tables skipped:")
        for t in tables_skipped:
            print(f"    - {t}")
    print(f"\n  Output lines: {len(output_lines)}")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python convert_dump.py <input_dump.sql> <output_dump.sql>")
        print()
        print("Converts a raw mysqldump file into a clean SQL dump with explicit column names.")
        print("Reads CREATE TABLE statements from the dump itself - no external dependencies.")
        print()
        print("What it does:")
        print("  - Extracts column names from CREATE TABLE statements in the dump")
        print("  - Adds explicit column names to INSERT statements that lack them")
        print("  - Removes MySQL directives (LOCK/UNLOCK, SET, conditional comments)")
        print("  - Removes CREATE TABLE, DROP TABLE, stored procedures")
        print("  - Handles multi-line INSERT statements")
        print("  - Trims extra trailing columns if INSERT has more values than CREATE TABLE")
        print("  - Keeps section comments (-- Dumping data for table ...)")
        print()
        print("Example:")
        print("  python convert_dump.py raw_dump.sql clean_dump.sql")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found")
        sys.exit(1)

    # First pass: read entire file to extract CREATE TABLE column mappings
    print(f"Scanning CREATE TABLE statements from: {input_file}")
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    table_columns = parse_create_tables(content)
    print(f"  Found {len(table_columns)} table(s)")

    for tbl, cols in sorted(table_columns.items()):
        print(f"    {tbl}: {len(cols)} columns")

    if not table_columns:
        print("WARNING: No CREATE TABLE statements found. INSERTs will be kept as-is.")

    # Second pass: process the dump
    print(f"\nProcessing dump: {input_file}")
    process_dump(input_file, output_file, table_columns)
