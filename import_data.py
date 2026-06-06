# import_data.py
import csv
import re
from pathlib import Path
from app import get_db_connection, PostgresConnectionWrapper

def create_database():
    """Create the database and medicines table (drops previous medicines table)."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS medicines;")
    
    if isinstance(conn, PostgresConnectionWrapper):
        cur.execute('''
        CREATE TABLE medicines (
            id SERIAL PRIMARY KEY,
            category TEXT,
            name VARCHAR(255) NOT NULL,
            code VARCHAR(255),
            unit TEXT,
            basic_price REAL,
            mrp REAL,
            loose_unit TEXT,
            loose_basic_price REAL,
            loose_mrp REAL,
            pack_size_ml REAL,
            loose_size_ml REAL,
            pack_amount REAL,
            pack_unit TEXT,
            loose_amount REAL,
            loose_unit_type TEXT,
            stock REAL DEFAULT 0,
            UNIQUE(name, code)
        );
        ''')
    else:
        cur.execute('''
        CREATE TABLE medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            name TEXT NOT NULL,
            code TEXT,
            unit TEXT,
            basic_price REAL,
            mrp REAL,
            loose_unit TEXT,
            loose_basic_price REAL,
            loose_mrp REAL,
            pack_size_ml REAL,
            loose_size_ml REAL,
            pack_amount REAL,
            pack_unit TEXT,
            loose_amount REAL,
            loose_unit_type TEXT,
            stock REAL DEFAULT 0,
            UNIQUE(name, code)
        );
        ''')
        
    cur.execute("CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_medicines_code ON medicines(code);")
    conn.commit()
    conn.close()

# --- robust unit parser ---
_unit_aliases = {
    'ml': 'ml', 'milliliter': 'ml', 'millilitre': 'ml', 'l': 'l',
    'g': 'g', 'gm': 'g', 'gram': 'g', 'mg': 'mg', 'mcg': 'mcg', 'µg': 'mcg',
    'nos': 'nos', 'no': 'nos', 'tablet': 'nos', 'tab': 'nos', 'tabs': 'nos',
    'capsule': 'nos', 'strip': 'strip', 'bottle': 'bottle',
    'sachet': 'sachet', 'pack': 'pack'
}

def normalize_unit(u: str):
    if not u:
        return ''
    u = u.strip().lower()
    for key in _unit_aliases:
        if key in u:
            return _unit_aliases[key]
    if 'tablet' in u or 'tab' in u:
        return 'nos'
    if 'capsule' in u:
        return 'nos'
    return ''

def parse_unit(raw: str):
    if not raw:
        return 0.0, ''
    s = raw.strip()
    s_sp = re.sub(r'[\u00A0\t]+', ' ', s).replace('×', 'x').replace('*', 'x')

    m = re.search(r'(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)(?:\s*(mg|mcg|g|kg|ml|l))?', s_sp, re.IGNORECASE)
    if m:
        left = float(m.group(1))
        right = float(m.group(2))
        unit = normalize_unit(m.group(3) or s_sp)
        return left * right, unit

    pairs = re.findall(r'(\d+(?:\.\d+)?)\s*(mg|mcg|g|kg|ml|l|nos|no|tab|tabs?|capsules?|strip|bottle|sachet|pack)?',
                         s_sp, re.IGNORECASE)
    if pairs:
        if len(pairs) == 1:
            num, u = pairs[0]
            return float(num), normalize_unit(u or s_sp)

        count_idx, size_idx = None, None
        for i, (num, u) in enumerate(pairs):
            nu = normalize_unit(u)
            if nu in ('pack', 'strip', 'nos', '') and count_idx is None and float(num).is_integer():
                count_idx = i
            if nu in ('mg', 'g', 'mcg', 'ml', 'l') and size_idx is None:
                size_idx = i
        if count_idx is not None and size_idx is not None:
            count = float(pairs[count_idx][0])
            size = float(pairs[size_idx][0])
            unit = normalize_unit(pairs[size_idx][1])
            return count * size, unit

        totals = [(float(n), normalize_unit(u)) for n, u in pairs if n]
        if totals:
            unit_counts = {}
            for amt, u in totals:
                unit_counts[u] = unit_counts.get(u, 0) + amt
            chosen_unit, total = max(unit_counts.items(), key=lambda x: x[1])
            return total, chosen_unit

    m2 = re.search(r'(\d+(?:\.\d+)?)', s_sp)
    if m2:
        return float(m2.group(1)), normalize_unit(s_sp)

    return 0.0, ''

def import_csv_to_db(csv_file_path):
    conn = get_db_connection()
    cur = conn.cursor()
    current_category = None
    inserted, skipped = 0, 0

    csv_path = Path(csv_file_path)
    if not csv_path.exists():
        print("CSV file not found:", csv_file_path)
        return

    # Determine query based on database engine type
    if isinstance(conn, PostgresConnectionWrapper):
        query = '''
            INSERT INTO medicines
            (category, name, code, unit, basic_price, mrp, loose_unit,
             loose_basic_price, loose_mrp, pack_size_ml, loose_size_ml,
             pack_amount, pack_unit, loose_amount, loose_unit_type, stock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (name, code) DO NOTHING
        '''
    else:
        query = '''
            INSERT OR IGNORE INTO medicines
            (category, name, code, unit, basic_price, mrp, loose_unit,
             loose_basic_price, loose_mrp, pack_size_ml, loose_size_ml,
             pack_amount, pack_unit, loose_amount, loose_unit_type, stock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''

    with open(csv_file_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f)
        for row in reader:
            row = [cell.strip() for cell in row]
            if not any(row):  # skip empty
                continue

            if row[0] and all((not cell) for cell in row[1:]):
                current_category = row[0]
                continue

            lower0 = row[0].lower() if row[0] else ''
            if any(h in lower0 for h in ('medicine', 'product', 's.no', 'code')):
                continue

            name = row[0] if row else ''
            if not name:
                skipped += 1
                continue

            code = row[1] if len(row) > 1 else ''
            if not code:
                mcode = re.search(r'\(([^)]+)\)\s*$', name)
                if mcode:
                    code = mcode.group(1).strip()
                    name = re.sub(r'\s*\([^)]+\)\s*$', '', name).strip()

            unit_str = row[2] if len(row) > 2 else ''
            basic_price = float(re.sub(r'[^\d.\-]', '', row[3])) if len(row) > 3 and row[3] else 0.0
            mrp = float(re.sub(r'[^\d.\-]', '', row[4])) if len(row) > 4 and row[4] else 0.0
            loose_unit_str = row[5] if len(row) > 5 else ''
            loose_basic_price = float(re.sub(r'[^\d.\-]', '', row[6])) if len(row) > 6 and row[6] and row[6] != '-' else 0.0
            loose_mrp = float(re.sub(r'[^\d.\-]', '', row[7])) if len(row) > 7 and row[7] and row[7] != '-' else 0.0

            pack_amount, pack_unit = parse_unit(unit_str)
            loose_amount, loose_unit_type = parse_unit(loose_unit_str)

            cur.execute(query, (current_category or '', name, code or '', unit_str, basic_price, mrp,
                                loose_unit_str, loose_basic_price, loose_mrp, pack_amount, loose_amount,
                                pack_amount, pack_unit or '', loose_amount, loose_unit_type or '', 0.0))
            if cur.rowcount > 0:
                inserted += 1

    conn.commit()
    conn.close()
    print(f"Import finished. Inserted: {inserted}, Skipped: {skipped}")

if __name__ == "__main__":
    create_database()
    import_csv_to_db("Kottakal_Pricelist.csv")