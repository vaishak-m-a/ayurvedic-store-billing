import os
import sys
import sqlite3
import re
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)

app = Flask(__name__)
# IMPORTANT: set a long random key via environment in production
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'replace-with-a-long-random-string')

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Template filter to format dates
@app.template_filter('date_format')
def date_format(value, fmt='%Y-%m-%d'):
    dt = value if isinstance(value, datetime) else datetime.now()
    return dt.strftime(fmt)

# User model
class User(UserMixin):
    def __init__(self, id):
        self.id = id

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# -------------------- Database helpers --------------------
DB_FILENAME = 'billing_system.db'

# --- START FIX FOR PYINSTALLER DATABASE PATH ---
# --- FIXED VERSION FOR SHARED EXE + DB ---
def resource_path(relative_path):
    """Get absolute path to resource, works for both script and PyInstaller exe."""
    try:
        base_path = sys._MEIPASS  # Used when bundled with PyInstaller
    except Exception:
        # Use the folder where the .exe or script is actually located
        base_path = os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, 'frozen', False) else __file__
        ))
    return os.path.join(base_path, relative_path)

DB_FILE = resource_path(DB_FILENAME)
# --- END FIX ---
# ... (after DB_FILE definition)

def get_bundle_dir():
    """Returns the base path for static/templates, handles PyInstaller's temporary folder."""
    if getattr(sys, 'frozen', False):
        # Running as a bundled executable
        return sys._MEIPASS
    else:
        # Running as a regular script
        return os.path.dirname(os.path.abspath(__file__))

# Define the base directory for resources
BASE_DIR = get_bundle_dir() 

# -------------------- Flask Initialization Fix --------------------

# -------------------- Database driver wrapper for PostgreSQL & SQLite --------------------
try:
    import psycopg2
    import psycopg2.extras
    psycopg2_IntegrityError = psycopg2.IntegrityError
except ImportError:
    class psycopg2_IntegrityError(Exception):
        pass

class PostgresRowWrapper:
    def __init__(self, dict_row):
        self._row = dict_row

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._row.values())[key]
        return self._row[key]

    def keys(self):
        return self._row.keys()

    def values(self):
        return self._row.values()

    def get(self, key, default=None):
        if isinstance(key, int):
            try:
                return list(self._row.values())[key]
            except IndexError:
                return default
        return self._row.get(key, default)

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self._lastrowid = None

    def execute(self, sql, parameters=None):
        self._lastrowid = None
        if parameters:
            sql = sql.replace('?', '%s')
        
        # Check if this is an INSERT statement
        sql_stripped = sql.strip().upper()
        if sql_stripped.startswith("INSERT INTO"):
            if "RETURNING" not in sql_stripped:
                sql = sql.rstrip().rstrip(';') + " RETURNING id"
                if parameters:
                    self.cursor.execute(sql, parameters)
                else:
                    self.cursor.execute(sql)
                row = self.cursor.fetchone()
                if row:
                    if isinstance(row, dict):
                        self._lastrowid = row.get('id') or list(row.values())[0]
                    else:
                        self._lastrowid = row[0]
                return self

        if parameters:
            self.cursor.execute(sql, parameters)
        else:
            self.cursor.execute(sql)
        return self

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            return PostgresRowWrapper(row)
        return None

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [PostgresRowWrapper(r) for r in rows]

    def __iter__(self):
        for row in self.cursor:
            yield PostgresRowWrapper(row)

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn
        self.is_postgres = True

    def cursor(self, *args, **kwargs):
        kwargs['cursor_factory'] = psycopg2.extras.RealDictCursor
        cursor = self.conn.cursor(*args, **kwargs)
        return PostgresCursorWrapper(cursor)

    def execute(self, sql, parameters=None):
        cursor = self.cursor()
        cursor.execute(sql, parameters)
        return cursor

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        conn = psycopg2.connect(database_url)
        return PostgresConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DB_FILE) 
        conn.row_factory = sqlite3.Row
        return conn

def create_user_table():
    conn = get_db_connection()
    cur = conn.cursor()
    if isinstance(conn, PostgresConnectionWrapper):
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password TEXT TEXT NOT NULL
        )
        """)
    conn.commit()
    conn.close()

def add_admin_user():
    conn = get_db_connection()
    cur = conn.cursor()
    hashed_password = generate_password_hash('adminpassword', method='pbkdf2:sha256')
    try:
        cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", ('admin', hashed_password))
        conn.commit()
    except (sqlite3.IntegrityError, psycopg2_IntegrityError):
        pass
    conn.close()

def create_app_tables():
    conn = get_db_connection()
    cur = conn.cursor()
    if isinstance(conn, PostgresConnectionWrapper):
        cur.execute("""
        CREATE TABLE IF NOT EXISTS medicines (
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
            stock REAL DEFAULT 0,
            UNIQUE(name, code)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            total REAL NOT NULL,
            payment_method TEXT NOT NULL,
            discount_percentage REAL DEFAULT 0.0,
            tax_percentage REAL DEFAULT 0.0,
            customer_name TEXT,
            doctor_name TEXT,
            customer_phone TEXT,
            customer_address TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id SERIAL PRIMARY KEY,
            sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
            medicine_id INTEGER NOT NULL REFERENCES medicines(id),
            name TEXT NOT NULL,
            unit TEXT,
            unit_price REAL NOT NULL,
            quantity REAL NOT NULL,
            line_total REAL NOT NULL,
            unit_type TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS finance_log (
            id SERIAL PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            notes TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bank_log (
            id SERIAL PRIMARY KEY,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            transaction_id TEXT,
            type TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_batch_log (
            id SERIAL PRIMARY KEY,
            medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE CASCADE,
            date_added TEXT NOT NULL,
            packs_added REAL NOT NULL,
            units_added REAL NOT NULL
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY,
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
            stock REAL DEFAULT 0
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            total REAL NOT NULL,
            payment_method TEXT NOT NULL,
            discount_percentage REAL DEFAULT 0.0,
            tax_percentage REAL DEFAULT 0.0,
            customer_name TEXT,
            doctor_name TEXT,
            customer_phone TEXT,
            customer_address TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY,
            sale_id INTEGER NOT NULL,
            medicine_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            unit TEXT,
            unit_price REAL NOT NULL,
            quantity REAL NOT NULL,
            line_total REAL NOT NULL,
            unit_type TEXT NOT NULL,
            FOREIGN KEY (sale_id) REFERENCES sales(id),
            FOREIGN KEY (medicine_id) REFERENCES medicines(id)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS finance_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            notes TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS bank_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            transaction_id TEXT,
            type TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_batch_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medicine_id INTEGER NOT NULL,
            date_added TEXT NOT NULL,
            packs_added REAL NOT NULL,
            units_added REAL NOT NULL,
            FOREIGN KEY (medicine_id) REFERENCES medicines(id)
        )
        """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_balances (
        date TEXT PRIMARY KEY,
        opening_balance REAL NOT NULL,
        cash_sales REAL NOT NULL,
        credit_collections REAL NOT NULL,
        bank_withdrawals REAL NOT NULL,
        bank_deposits REAL NOT NULL,
        returns REAL NOT NULL,
        expenses REAL NOT NULL,
        closing_balance REAL NOT NULL,
        actual_cash REAL NOT NULL,
        difference REAL NOT NULL,
        notes TEXT
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name)")
    cur.execute("CREATE INDEX IF NOT EXISTS ux_medicines_code ON medicines(code)")
    conn.commit()
    conn.close()

def get_all_medicines():
    conn = get_db_connection()
    medicines = conn.execute("SELECT * FROM medicines ORDER BY category, name").fetchall()
    conn.close()
    return medicines

def parse_unit(unit_str):
    if not unit_str:
        return 0, ''
    match = re.match(r'(\d+\.?\d*)\s*(ml|g|gm|nos|no|tablet|capsule)', unit_str, re.IGNORECASE)
    if match:
        number = float(match.group(1))
        unit_type = match.group(2).lower()
        if unit_type in ['g', 'gm']:
            return number, 'g'
        elif unit_type in ['nos', 'no', 'tablet|capsule']:
            return number, 'nos'
        return number, 'ml'
    return 0, ''

# -------------------- Routes --------------------
@app.route('/')
@login_required
def dashboard():
    # --- Date Consistency Check ---
    conn = get_db_connection()
    
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 1. Fetch Today's sales by payment method
    totals_rows_today = conn.execute("""
        SELECT payment_method, SUM(total) as sum_total
        FROM sales
        WHERE date = ?
        GROUP BY payment_method
    """, (today,)).fetchall()
    
    # 2. Fetch Yesterday's sales by payment method
    totals_rows_yesterday = conn.execute("""
        SELECT payment_method, SUM(total) as sum_total
        FROM sales
        WHERE date = ?
        GROUP BY payment_method
    """, (yesterday,)).fetchall()
    
    # 3. Calculate Yesterday's totals
    totals_yesterday = {r['payment_method']: r['sum_total'] for r in totals_rows_yesterday}
    yesterday_cash_total = totals_yesterday.get('Cash', 0.0) or totals_yesterday.get('cash', 0.0) or 0.0
    yesterday_gpay_total = (totals_yesterday.get('GPay', 0.0) or 0.0) + (totals_yesterday.get('gpay', 0.0) or 0.0) + (totals_yesterday.get('UPI', 0.0) or 0.0) + (totals_yesterday.get('upi', 0.0) or 0.0)
    yesterday_total = yesterday_cash_total + yesterday_gpay_total

    # 4. Fetch Finance Log entries for today (for reconciliation)
    finance_log_today = conn.execute("""
        SELECT type, SUM(amount) as total_amount
        FROM finance_log
        WHERE date = ?
        GROUP BY type
    """, (today,)).fetchall()
    
    finance_metrics = {f['type']: f['total_amount'] for f in finance_log_today}
    
    # 5. Fetch Bank Movement for today
    
    # Total Bank Deposits (Cash Out of hand, stored as NEGATIVE amount)
    bank_deposits_out = conn.execute("""
        SELECT SUM(amount) AS total_out
        FROM bank_log
        WHERE date = ? AND amount < 0
    """, (today,)).fetchone()['total_out'] or 0.0
    bank_deposits_out = abs(bank_deposits_out)
    
    # Total Bank Withdrawals (Cash Into hand, stored as POSITIVE amount)
    bank_withdrawals_in = conn.execute("""
        SELECT SUM(amount) AS total_in
        FROM bank_log
        WHERE date = ? AND amount > 0
    """, (today,)).fetchone()['total_in'] or 0.0

    # 6. Calculate Reconciliation Metrics
    # Amount from Returns/Refunds (Negative total sales paid by Cash)
    return_medicine_amount = conn.execute("""
        SELECT SUM(total) as total_return
        FROM sales
        WHERE date = ? AND payment_method = 'Cash' AND total < 0
    """, (today,)).fetchone()['total_return'] or 0.0
    return_medicine_amount = abs(return_medicine_amount)
    
    # Get Expenses
    other_expenses = finance_metrics.get('expense', 0.0)
    
    # Calculate outstanding credits across all time
    total_credits_issued_all_time = conn.execute("SELECT SUM(amount) FROM finance_log WHERE type = 'credit'").fetchone()[0] or 0.0
    total_credits_collected_all_time = conn.execute("SELECT SUM(amount) FROM finance_log WHERE type = 'collection'").fetchone()[0] or 0.0
    credit_given = total_credits_issued_all_time - total_credits_collected_all_time 
    
    # 7. Calculate Opening Balance
    yesterday_cash_sales_raw = conn.execute("""
        SELECT SUM(total) as total
        FROM sales
        WHERE date = ? AND payment_method = 'Cash' AND total > 0 
    """, (yesterday,)).fetchone()
    # Yesterday's closing cash sales is today's opening balance
    opening_balance = yesterday_cash_sales_raw['total'] if yesterday_cash_sales_raw and yesterday_cash_sales_raw['total'] is not None else 0.0

    # Cash collected today (Positive total sales paid by Cash + Cash collected from credits)
    today_cash_collected_sales = conn.execute("""
        SELECT SUM(total) as total_cash_sales
        FROM sales
        WHERE date = ? AND payment_method = 'Cash' AND total > 0
    """, (today,)).fetchone()['total_cash_sales'] or 0.0
    
    # 8. CLOSING BALANCE CALCULATION: 
    closing_balance = (
        opening_balance + 
        today_cash_collected_sales +
        bank_withdrawals_in - # Cash into hand
        bank_deposits_out -   # Cash out of hand
        return_medicine_amount -
        other_expenses
    )

    # 9. Fetch other standard metrics (aligned with calendar week/month)
    start_of_week = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
    start_of_month = datetime.now().strftime('%Y-%m-01')

    weekly_total = conn.execute("""
        SELECT SUM(total) as total
        FROM sales
        WHERE date >= ?
    """, (start_of_week,)).fetchone()['total'] or 0.0

    monthly_total = conn.execute("""
        SELECT SUM(total) as total
        FROM sales
        WHERE date >= ?
    """, (start_of_month,)).fetchone()['total'] or 0.0
    
    # Fetch top 3 selling items for today
    top_sellers = conn.execute("""
        SELECT si.name, SUM(si.quantity) as qty_sold, si.unit
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE s.date = ? AND si.quantity > 0
        GROUP BY si.name, si.unit
        ORDER BY qty_sold DESC
        LIMIT 3
    """, (today,)).fetchall()
    
    conn.close()
    
    # Calculate Today's display totals
    totals_today = {r['payment_method']: r['sum_total'] for r in totals_rows_today}
    cash_total = totals_today.get('Cash', 0.0) or totals_today.get('cash', 0.0) or 0.0
    gpay_total = (totals_today.get('GPay', 0.0) or 0.0) + (totals_today.get('gpay', 0.0) or 0.0) + (totals_today.get('UPI', 0.0) or 0.0) + (totals_today.get('upi', 0.0) or 0.0)
    grand_total = cash_total + gpay_total

    return render_template("dashboard.html",
                           cash_total=cash_total,
                           gpay_total=gpay_total,
                           grand_total=grand_total,
                           
                           # YESTERDAY BREAKDOWN VARIABLES
                           yesterday_total=yesterday_total, 
                           yesterday_cash_total=yesterday_cash_total,
                           yesterday_gpay_total=yesterday_gpay_total,
                           
                           # NEW RECONCILIATION VARIABLES 
                           opening_balance=opening_balance,
                           today_cash_collected=today_cash_collected_sales,
                           return_medicine_amount=return_medicine_amount,
                           other_expenses=other_expenses,
                           credit_given=credit_given,
                           bank_deposits_out=bank_deposits_out,
                           bank_withdrawals_in=bank_withdrawals_in,
                           closing_balance=closing_balance,
                           
                           weekly_total=weekly_total,
                           monthly_total=monthly_total,
                           top_sellers=top_sellers)

@app.route('/sales_trend')
@login_required
def sales_trend():
    """
    Returns daily sales totals for the last 30 days for charting on the dashboard.
    """
    conn = get_db_connection()
    
    # Select date and sum of total sales (positive and negative) for the last 30 days
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    sales_data = conn.execute("""
        SELECT date, SUM(total) as daily_total
        FROM sales
        WHERE date >= ?
        GROUP BY date
        ORDER BY date ASC
    """, (thirty_days_ago,)).fetchall()
    conn.close()

    # Create a list of all dates in the range for completeness
    date_range = [
        (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        for i in range(30)
    ]
    date_range.reverse() # Sort from oldest to newest

    # Map fetched data to the date range
    sales_map = {row['date']: row['daily_total'] for row in sales_data}
    
    labels = []
    values = []
    
    for date in date_range:
        labels.append(date)
        # Use 0.0 if no sales recorded for that day
        values.append(sales_map.get(date, 0.0)) 

    return jsonify({'labels': labels, 'values': values})


@app.route('/bank_entries')
@login_required
def bank_entries():
    """
    Fetches all bank deposit and withdrawal entries for the log table.
    """
    conn = get_db_connection()
    entries = conn.execute("SELECT * FROM bank_log ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    
    return jsonify([dict(e) for e in entries])


@app.route('/add_bank_entry', methods=['POST'])
@login_required
def add_bank_entry():
    """
    Logs a bank deposit or withdrawal transaction.
    """
    data = request.get_json(force=True)
    entry_type = data.get('type')           # 'deposit' or 'withdrawal'
    amount = float(data.get('amount') or 0)
    transaction_id = data.get('transaction_id', '')
    
    date = datetime.now().strftime('%Y-%m-%d')
    
    if amount <= 0 or entry_type not in ['deposit', 'withdrawal']:
        return jsonify({'message': 'Invalid transaction type or amount.'}), 400
        
    # Amount is stored as negative if it's a deposit (cash out of hand), and positive if withdrawal (cash into hand)
    final_amount = -amount if entry_type == 'deposit' else amount
        
    conn = None
    try:
        conn = get_db_connection()
        conn.execute("INSERT INTO bank_log (date, amount, transaction_id, type) VALUES (?, ?, ?, ?)",
                     (date, final_amount, transaction_id, entry_type))
        conn.commit()
        return jsonify({'message': f"Bank {entry_type.capitalize()} of ₹{amount:.2f} logged successfully."}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'message': f"Database error: {str(e)}"}), 500
    finally:
        if conn: conn.close()


@app.route('/delete_bank_entry/<int:entry_id>', methods=['POST'])
@login_required
def delete_bank_entry(entry_id):
    """
    Deletes a specific bank entry.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        entry = cur.execute("SELECT id FROM bank_log WHERE id = ?", (entry_id,)).fetchone()
        if not entry:
            return jsonify({'message': 'Bank entry not found.'}), 404

        cur.execute("DELETE FROM bank_log WHERE id = ?", (entry_id,))
        conn.commit()
        
        return jsonify({'message': "Bank entry deleted successfully."}), 200
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'message': f"Database error: {str(e)}"}), 500
    finally:
        if conn: conn.close()

@app.route('/finance_log')
@login_required
def finance_log():
    conn = get_db_connection()
    
    entries = conn.execute("SELECT * FROM finance_log ORDER BY date DESC, id DESC").fetchall()

    today_date_str = datetime.now().strftime('%Y-%m-%d')
    
    # Calculate start of current week (Monday) using python dates temporarily
    start_of_week_py = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
    start_of_month_py = datetime.now().strftime('%Y-%m-01')
    
    # Query aggregated expenses by date
    daily_expense_query = conn.execute("""
        SELECT date, SUM(amount) as daily_total
        FROM finance_log
        WHERE type = 'expense'
        GROUP BY date
        ORDER BY date DESC
    """).fetchall()
    
    # Calculate period totals
    # Total positive credit entries (Credits given + Collections)
    total_credits = sum(e['amount'] for e in entries if e['type'] == 'credit' or e['type'] == 'collection')
    
    # Use the calculated daily totals to sum up weekly/monthly periods (using python dates for this logic)
    weekly_expenses = sum(e['daily_total'] for e in daily_expense_query if e['date'] >= start_of_week_py)
    monthly_expenses = sum(e['daily_total'] for e in daily_expense_query if e['date'] >= start_of_month_py)
    total_expenses = sum(e['daily_total'] for e in daily_expense_query) # Total expenses across all time

    conn.close()
    
    # Recalculate total_credits to only include 'credit' entries for the summary card calculation
    total_credits_issued = sum(e['amount'] for e in entries if e['type'] == 'credit')
    
    return render_template('finance_log.html', 
                           entries=entries,
                           daily_expense_data=daily_expense_query,
                           total_expenses=total_expenses,
                           total_credits=total_credits_issued, # Only issued credits
                           weekly_expenses=weekly_expenses,
                           monthly_expenses=monthly_expenses)

@app.route('/collect_credit/<int:entry_id>', methods=['POST'])
@login_required
def collect_credit(entry_id):
    """
    Handles reconciliation when a customer pays for a credit.
    1. Records the positive payment to the sales log (revenue).
    2. Updates the finance_log to 'collection' type for audit.
    """
    conn = None
    try:
        data = request.get_json(force=True)
        payment_method = data.get('payment_method', 'Cash') # Method of payment from the quick-pay button
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("BEGIN")

        # A. Fetch original credit details (crucial for amount and customer name)
        original_entry = cur.execute(
            "SELECT name, amount FROM finance_log WHERE id = ? AND type = 'credit'", 
            (entry_id,)
        ).fetchone()

        if not original_entry:
            conn.rollback()
            return jsonify({'message': 'Original credit entry not found or already collected.'}), 404

        amount = original_entry['amount']
        name = original_entry['name']
        
        date = datetime.now().strftime('%Y-%m-%d')

        # B. Log the collected amount as a POSITIVE sale transaction (Revenue)
        # This uses the default sales table which is accounted for in the dashboard reconciliation
        cur.execute("INSERT INTO sales (date, total, payment_method, discount_percentage, tax_percentage) VALUES (?, ?, ?, 0.0, 0.0)", 
                    (date, amount, payment_method))

        # C. Update the original credit entry to 'collection' type (Audit Trail)
        # This keeps the original amount and customer name for history
        cur.execute("UPDATE finance_log SET type = 'collection', notes = ? WHERE id = ?",
                    (f'Collected via {payment_method} on {date}', entry_id))
        
        conn.commit()
        return jsonify({'message': f"Credit of ₹{amount:.2f} collected via {payment_method}. Entry updated to 'Collection'."}), 200
        
    except Exception as e:
        if conn: cur.execute("ROLLBACK")
        print(f"Error during credit collection: {e}")
        return jsonify({'message': f"Database error during collection: {str(e)}"}), 500
    finally:
        if conn: conn.close()

@app.route('/add_finance_entry', methods=['POST'])
@login_required
def add_finance_entry():
    data = request.get_json(force=True)
    entry_type = data.get('type')
    name = data.get('name')
    amount = float(data.get('amount') or 0)
    notes = data.get('notes', '')
    
    date = datetime.now().strftime('%Y-%m-%d')
    
    if not all([entry_type, name, amount > 0]) or entry_type not in ['expense', 'credit']:
        return jsonify({'message': 'Invalid type, name, or amount.'}), 400
        
    conn = None
    try:
        conn = get_db_connection()
        conn.execute("INSERT INTO finance_log (type, name, date, amount, notes) VALUES (?, ?, ?, ?, ?)",
                     (entry_type, name, date, amount, notes))
        conn.commit()
        return jsonify({'message': f"{entry_type.capitalize()} logged successfully."}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'message': f"Database error: {str(e)}"}), 500
    finally:
        if conn: conn.close()

@app.route('/delete_finance_entry/<int:entry_id>', methods=['POST'])
@login_required
def delete_finance_entry(entry_id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check if the entry exists
        entry = cur.execute("SELECT id, type, name FROM finance_log WHERE id = ?", (entry_id,)).fetchone()
        if not entry:
            return jsonify({'message': 'Entry not found.'}), 404

        # Delete the entry
        cur.execute("DELETE FROM finance_log WHERE id = ?", (entry_id,))
        conn.commit()
        
        return jsonify({'message': f"{entry['type'].capitalize()} entry for '{entry['name']}' deleted successfully."}), 200
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'message': f"Database error: {str(e)}"}), 500
    finally:
        if conn: conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        conn = get_db_connection()
        user_row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user_row and check_password_hash(user_row['password'], password):
            login_user(User(user_row['id']))
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid username or password.')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/billing')
@login_required
def billing():
    conn = get_db_connection()
    meds = conn.execute("SELECT id, name, mrp, basic_price, pack_size_ml, loose_size_ml, stock FROM medicines ORDER BY name").fetchall()
    conn.close()
    return render_template('billing.html', medicines=meds)

@app.route('/return_stock')
@login_required
def return_stock():
    return render_template('return_stock.html')

@app.route('/out_of_stock')
@login_required
def out_of_stock():
    conn = get_db_connection()
    
    # REORDER_POINT_PACKS = 7
    REORDER_POINT_PACKS = 7
    low_stock_items = conn.execute(f"""
        SELECT id, category, name, code, unit, pack_size_ml, stock 
        FROM medicines
        WHERE stock <= ({REORDER_POINT_PACKS} * pack_size_ml)
        ORDER BY category, name
    """).fetchall()

    conn.close()
    
    # Group items by category (for organized tables)
    categorized_stock = {}
    for item in low_stock_items:
        category = item['category'] or 'Uncategorized'
        if category not in categorized_stock:
            categorized_stock[category] = []
        categorized_stock[category].append(dict(item))
        
    return render_template('out_of_stock.html', categorized_stock=categorized_stock)


@app.route('/search_medicine')
@login_required
def search_medicine():
    query = request.args.get('query', '').strip()
    conn = get_db_connection()

    terms = query.split()
    if not terms:
        rows = []
    else:
        is_postgres = bool(os.environ.get('DATABASE_URL'))
        like_op = 'ILIKE' if is_postgres else 'LIKE'
        sql = """
            SELECT id, name, unit, mrp, loose_unit, loose_mrp, loose_basic_price, 
                   pack_size_ml, loose_size_ml, stock, code, category
            FROM medicines
            WHERE 
        """
        conditions = []
        params = []
        for term in terms:
            conditions.append(f"(name {like_op} ? OR code {like_op} ? OR category {like_op} ?)")
            term_pattern = f"%{term}%"
            params.extend([term_pattern, term_pattern, term_pattern])
        sql += " AND ".join(conditions)
        sql += " ORDER BY name LIMIT 50"
        rows = conn.execute(sql, params).fetchall()

    processed_rows = []
    for row in rows:
        row_dict = dict(row)

        # 1. Use stored Loose MRP (database value like 0.23)
        db_loose_mrp = row_dict.get('loose_mrp')
        correct_loose_mrp = db_loose_mrp

        # 2. Fallback to loose_basic_price if loose_mrp is missing/zero
        if correct_loose_mrp is None or correct_loose_mrp == 0:
            loose_basic = row_dict.get('loose_basic_price')
            if loose_basic and loose_basic > 0:
                correct_loose_mrp = loose_basic

        # 3. CRITICAL CHANGE: REMOVED automatic calculation (division from pack MRP).
        #    Loose MRP MUST be a distinct, stored value. If not found, it defaults to 0.0.
        if correct_loose_mrp is None:
            correct_loose_mrp = 0.0

        # Final step: Ensure correct value sent to frontend
        row_dict['loose_mrp'] = correct_loose_mrp or 0.0
        processed_rows.append(row_dict)

    conn.close()
    return jsonify(processed_rows)


@app.route('/get_customer_history')
@login_required
def get_customer_history():
    phone = request.args.get('phone', '').strip()
    if not phone:
        return jsonify({'found': False})
    
    conn = get_db_connection()
    row = conn.execute("""
        SELECT date, total 
        FROM sales 
        WHERE customer_phone = ? 
        ORDER BY id DESC 
        LIMIT 1
    """, (phone,)).fetchone()
    conn.close()
    
    if row:
        return jsonify({
            'found': True,
            'date': row['date'],
            'total': row['total']
        })
    return jsonify({'found': False})


def generate_bill_logic(data):
    """Core logic to generate a bill, update stock, and record the sale."""
    conn = None
    try:
        items = data.get('items', [])
        total = data.get('total', 0.0)
        payment_method = data.get('payment_method', 'Cash')
        discount = data.get('discount', 0.0)
        tax = data.get('tax', 0.0)
        customer_name = data.get('customer_name') or ''
        doctor_name = data.get('doctor_name') or ''
        customer_phone = data.get('customer_phone') or ''
        customer_address = data.get('customer_address') or ''

        if not items:
            return jsonify({'message': 'No items in bill.'}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("BEGIN")
        
        date = datetime.now().strftime('%Y-%m-%d')

        # 1. Insert the main sales record
        cur.execute("""
            INSERT INTO sales (date, total, payment_method, discount_percentage, tax_percentage, customer_name, doctor_name, customer_phone, customer_address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, total, payment_method, discount, tax, customer_name, doctor_name, customer_phone, customer_address))
        sale_id = cur.lastrowid

        # 2. Process each item
        for item in items:
            med_id = item['id']
            qty = item['quantity']
            unit_type = item['unit_type']
            unit_price = item['unit_price']

            med_row = cur.execute("SELECT name, unit, loose_unit, pack_size_ml, loose_size_ml FROM medicines WHERE id = ?", (med_id,)).fetchone()
            if not med_row:
                cur.execute("ROLLBACK")
                return jsonify({'message': f"Medicine ID {med_id} not found."}), 404

            # Calculate stock to deduct (in base units like ml/g/nos)
            stock_deduction = 0.0
            unit_display = ''

            if unit_type == 'pack':
                stock_deduction = float(med_row['pack_size_ml'] or 0) * qty
                unit_display = med_row['unit']
            elif unit_type == 'loose':
                stock_deduction = float(med_row['loose_size_ml'] or 0) * qty
                unit_display = med_row['loose_unit']
            
            # 3. Update stock (Deduction)
            cur.execute("UPDATE medicines SET stock = stock - ? WHERE id = ?", (stock_deduction, med_id))
            
            # 4. Insert item into sale_items
            line_total = qty * unit_price
            cur.execute("""
                INSERT INTO sale_items (sale_id, medicine_id, name, unit, unit_price, quantity, line_total, unit_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (sale_id, med_id, med_row['name'], unit_display, unit_price, qty, line_total, unit_type))

        conn.commit()
        return jsonify({'message': f'Bill {sale_id} generated successfully.', 'bill_id': sale_id}), 200

    except Exception as e:
        if conn: cur.execute("ROLLBACK")
        print(f"Error generating bill: {e}")
        return jsonify({'message': f'An unexpected error occurred: {str(e)}'}), 500
    finally:
        if conn: conn.close()


@app.route('/generate_bill', methods=['POST'])
@login_required
def generate_bill():
    data = request.get_json(force=True)
    return generate_bill_logic(data)

@app.route('/stock_management')
@login_required
def stock_management():
    """Renders a simple page linking to add new product and add existing stock."""
    return render_template('add_stock.html') # Redirects to the new stock management menu

@app.route('/add_new_product', methods=['GET', 'POST'])
@login_required
def add_new_product():
    """Handles adding a new medicine product to the database."""
    if request.method == 'POST':
        try:
            data = request.get_json()
            category = data.get('category', '').strip()
            name = data.get('name', '').strip()
            code = data.get('code', '').strip()
            unit = data.get('unit', '').strip()
            mrp = float(data.get('mrp') or 0)
            packs_added = float(data.get('packs_added') or 0)
            pack_size_ml = float(data.get('pack_size_ml') or 0)
            
            if not all([name, unit, mrp, pack_size_ml]) or packs_added <= 0:
                 return jsonify({'message': 'Missing required fields or invalid initial stock/price.'}), 400

            # Calculate base stock units
            initial_stock_units = packs_added * pack_size_ml
            
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("BEGIN")

            # 1. Insert new medicine product
            # CRITICAL CHANGE: loose_mrp is explicitly set to 0.0. It MUST be set manually
            # via a stock update if it's not a calculated value.
            loose_mrp = 0.0
            loose_size_ml = 1.0 # 1 unit of loose item is 1 ml/g/nos
            
            cur.execute("""
                INSERT INTO medicines (category, name, code, unit, mrp, pack_size_ml, loose_mrp, loose_size_ml, stock)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (category, name, code, unit, mrp, pack_size_ml, loose_mrp, loose_size_ml, initial_stock_units))
            medicine_id = cur.lastrowid
            
            # 2. Log the initial stock batch
            date = datetime.now().strftime('%Y-%m-%d')
            cur.execute("""
                INSERT INTO stock_batch_log (medicine_id, date_added, packs_added, units_added)
                VALUES (?, ?, ?, ?)
            """, (medicine_id, date, packs_added, initial_stock_units))
            
            conn.commit()
            return jsonify({'message': f"New Product '{name}' added with {packs_added} packs of initial stock.", 'id': medicine_id}), 200
        except sqlite3.IntegrityError:
            return jsonify({'message': f"Product with code '{code}' or name '{name}' already exists."}), 400
        except Exception as e:
            if 'conn' in locals() and conn: conn.rollback()
            return jsonify({'message': f'An error occurred: {str(e)}'}), 500
        finally:
            if 'conn' in locals() and conn: conn.close()
    
    # GET request renders the template
    return render_template('add_new_product.html')

@app.route('/add_date_stock', methods=['GET', 'POST'])
@login_required
def add_date_stock():
    """Handles adding new stock batches for existing products."""
    if request.method == 'POST':
        try:
            data = request.get_json()
            item_id = int(data.get('id'))
            packs_added = float(data.get('packs') or 0)
            date_added = data.get('date', datetime.now().strftime('%Y-%m-%d'))
            new_mrp = float(data.get('mrp')) if data.get('mrp') is not None else None
            
            if packs_added <= 0:
                return jsonify({'message': 'Packs added must be greater than zero.'}), 400

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("BEGIN")

            item = cur.execute("SELECT id, name, pack_size_ml, stock FROM medicines WHERE id = ?", (item_id,)).fetchone()
            
            if not item:
                conn.rollback()
                return jsonify({'message': 'Item not found.'}), 404

            pack_units_ml = float(item['pack_size_ml'] or 0)
            units_added = packs_added * pack_units_ml

            # 1. Update the overall stock count
            update_fields = ["stock = stock + ?"]
            params = [units_added]
            
            # 2. Update MRP (Pack Price) if provided
            if new_mrp is not None:
                update_fields.append("mrp = ?")
                params.append(new_mrp)
                # CRITICAL CHANGE: Removed automatic calculation of loose_mrp
                 
            params.append(item_id)
            
            sql = "UPDATE medicines SET " + ", ".join(update_fields) + " WHERE id = ?"
            cur.execute(sql, tuple(params))

            # 3. Log the new stock batch
            cur.execute("""
                INSERT INTO stock_batch_log (medicine_id, date_added, packs_added, units_added)
                VALUES (?, ?, ?, ?)
            """, (item_id, date_added, packs_added, units_added))
            
            conn.commit()
            return jsonify({'message': f"Added {packs_added} packs of '{item['name']}' to batch log for {date_added}.", 'stock_units_added': units_added, 'mrp': new_mrp}), 200

        except Exception as e:
            if 'conn' in locals() and conn: conn.rollback()
            return jsonify({'message': f'An error occurred during stock update: {str(e)}'}), 500
        finally:
            if 'conn' in locals() and conn: conn.close()

    # GET request renders the template
    conn = get_db_connection()
    medicines = conn.execute("SELECT id, name, code, mrp, stock, pack_size_ml, unit FROM medicines ORDER BY category, name").fetchall()
    conn.close()
    
    # Pass today's date for default date input
    today_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('add_date_stock.html', medicines=[dict(row) for row in medicines], today_date=today_date)

@app.route('/get_stock_batch_dates', methods=['GET'])
@login_required
def get_stock_batch_dates():
    """Fetches unique dates where stock was updated, along with the total batches for that day."""
    conn = get_db_connection()
    
    dates = conn.execute("""
        SELECT 
            date_added,
            COUNT(id) AS total_batches
        FROM stock_batch_log
        GROUP BY date_added
        ORDER BY date_added DESC
    """).fetchall()
    
    conn.close()
    
    return jsonify([dict(d) for d in dates])

@app.route('/get_stock_updates_by_date', methods=['GET'])
@login_required
def get_stock_updates_by_date():
    """Fetches all stock batches added on a specific date (UNUSED, replaced by detail page)."""
    target_date = request.args.get('date')
    if not target_date:
        return jsonify({'message': 'Date parameter is required.'}), 400

    conn = get_db_connection()
    
    updates = conn.execute("""
        SELECT 
            sbl.id, 
            m.name, 
            m.code, 
            m.unit,
            m.pack_size_ml, 
            sbl.packs_added, 
            sbl.units_added
        FROM stock_batch_log sbl
        JOIN medicines m ON m.id = sbl.medicine_id
        WHERE sbl.date_added = ?
        ORDER BY m.name
    """, (target_date,)).fetchall()
    
    conn.close()
    
    return jsonify([dict(u) for u in updates])

@app.route('/stock_batch_detail/<date>', methods=['GET'])
@login_required
def stock_batch_detail(date):
    """Renders the page to view and manage all batch entries for a specific date."""
    conn = get_db_connection()
    
    batches = conn.execute("""
        SELECT 
            sbl.id, 
            m.name, 
            m.code, 
            m.unit,
            m.pack_size_ml, 
            sbl.packs_added, 
            sbl.units_added,
            sbl.medicine_id
        FROM stock_batch_log sbl
        JOIN medicines m ON m.id = sbl.medicine_id
        WHERE sbl.date_added = ?
        ORDER BY m.name
    """, (date,)).fetchall()
    
    conn.close()
    
    return render_template('stock_batch_detail.html', batches=[dict(b) for b in batches], selected_date=date)

@app.route('/delete_stock_batch/<int:batch_id>', methods=['POST'])
@login_required
def delete_stock_batch(batch_id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("BEGIN")

        # 1. Fetch batch details (units to reverse)
        batch = cur.execute("SELECT medicine_id, units_added FROM stock_batch_log WHERE id = ?", (batch_id,)).fetchone()
        
        if not batch:
            conn.rollback()
            return jsonify({'message': 'Stock batch entry not found.'}), 404

        med_id = batch['medicine_id']
        units_to_remove = batch['units_added']
        
        # 2. Revert the stock level (Deduct the units added by this batch)
        cur.execute("UPDATE medicines SET stock = stock - ? WHERE id = ?", (units_to_remove, med_id))
        
        # 3. Delete the batch log entry
        cur.execute("DELETE FROM stock_batch_log WHERE id = ?", (batch_id,))
        
        conn.commit()
        return jsonify({'message': f'Stock batch {batch_id} deleted successfully. Stock reduced by {units_to_remove:.2f} units.'}), 200
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'message': f'Error deleting batch: {str(e)}'}), 500
    finally:
        if conn: conn.close()


@app.route('/add_stock')
@login_required
def add_stock():
    # Redirects to the Stock Management Menu
    return redirect(url_for('stock_management'))


@app.route('/update_stock', methods=['POST'])
@login_required
def update_stock():
    """
    Update stock for corrections/removal only (negative packs or single MRP update). 
    New batches must use /add_date_stock.
    """
    conn = None
    try:
        data = request.get_json(force=True)
        item_id = int(data.get('id'))
        # NOTE: add_packs must be negative for correction/removal, or zero if only MRP is changed.
        add_packs = float(data.get('packs') or 0) 
        new_mrp = float(data.get('mrp')) if data.get('mrp') is not None else None
        
        # Enforce that only removal/correction happens here
        if add_packs > 0:
            return jsonify({'message': 'To ADD stock, please use the "Add Batch" button.'}), 400


        conn = get_db_connection()
        cur = conn.cursor()
        item = cur.execute("SELECT id, name, pack_size_ml, loose_size_ml, stock FROM medicines WHERE id = ?", (item_id,)).fetchone()
        
        if not item:
            conn.close()
            return jsonify({'message': 'Item not found.'}), 404

        # Calculate the base unit (ml/g/nos) equivalent of the packs to add/remove.
        added_units = 0.0
        pack_units_ml = float(item['pack_size_ml'] or 0)
        
        if pack_units_ml > 0:
            added_units = add_packs * pack_units_ml
        
        current_stock = float(item['stock'] or 0)
        new_stock = current_stock + added_units
        
        # Validation: Prevent stock from going below zero during a manual deduction.
        if new_stock < 0:
            conn.close()
            return jsonify({'message': f"Error: Cannot remove {abs(add_packs)} packs. Current stock ({current_stock:.2f}) would become negative."}), 400

        # Prepare the update query
        update_fields = ["stock = ?"]
        params = [new_stock]
        
        # 3. Update MRP (Pack Price) if provided
        if new_mrp is not None:
            update_fields.append("mrp = ?")
            params.append(new_mrp)
            # CRITICAL CHANGE: Loose MRP is NOT automatically recalculated here
        
        params.append(item_id)
        
        sql = "UPDATE medicines SET " + ", ".join(update_fields) + " WHERE id = ?"
        cur.execute(sql, tuple(params))
        conn.commit()
        conn.close()
        
        action = "Removed" if add_packs < 0 else "Updated"
        
        return jsonify({'message': f"Stock Correction for '{item['name']}' processed." if add_packs != 0 else f"Updated MRP for '{item['name']}'.", 'stock': new_stock, 'mrp': new_mrp}), 200

    except Exception as e:
        print(f"Error updating stock: {e}")
        if conn:
            conn.rollback()
        return jsonify({'message': 'An error occurred during stock update.', 'error': str(e)}), 500
    finally:
        if conn:
            conn.close()


@app.route('/search_stock')
@login_required
def search_stock():
    q = request.args.get('query', '').strip()
    limit = int(request.args.get('limit', 50))
    conn = get_db_connection()
    # Fetch pack_unit for display in the table
    is_postgres = bool(os.environ.get('DATABASE_URL'))
    like_op = 'ILIKE' if is_postgres else 'LIKE'
    rows = conn.execute(f"""
        SELECT id, category, name, pack_size_ml, loose_size_ml, stock, mrp, code, loose_mrp, unit
        FROM medicines
        WHERE name {like_op} ? OR code {like_op} ?
        ORDER BY name
        LIMIT ?
    """, (f'%{q}%', f'%{q}%', limit)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/sales_report')
@login_required
def sales_report():
    """
    Enhanced sales report:
      - totals by payment method (for a date range or today)
      - aggregated medicine sales (name, qty sold, total sales, split by payment method)
    """
    today_default = datetime.now().strftime('%Y-%m-%d')
    start_date = request.args.get('start_date') or request.args.get('date') or today_default
    end_date = request.args.get('end_date') or request.args.get('date') or today_default
    conn = get_db_connection()

    # totals
    # Query for date range: s.date BETWEEN ? AND ?
    totals_rows = conn.execute("""
        SELECT payment_method, SUM(total) as sum_total 
        FROM sales 
        WHERE date BETWEEN ? AND ? 
        GROUP BY payment_method
    """, (start_date, end_date)).fetchall()
    
    totals = {r['payment_method']: r['sum_total'] for r in totals_rows}
    cash_total = totals.get('Cash', 0.0) or totals.get('cash', 0.0) or 0.0
    gpay_total = (totals.get('GPay', 0.0) or 0.0) + (totals.get('gpay', 0.0) or 0.0) + (totals.get('UPI', 0.0) or 0.0) + (totals.get('upi', 0.0) or 0.0)
    grand_total = cash_total + gpay_total

    # aggregated medicine sales for that date range
    meds = conn.execute("""
        SELECT si.medicine_id, si.name, si.unit_price,
                SUM(si.quantity) as qty_sold,
                SUM(si.line_total) as total_sales,
                SUM(CASE WHEN s.payment_method = 'Cash' THEN si.line_total ELSE 0 END) as cash_amount,
                SUM(CASE WHEN s.payment_method IN ('GPay', 'gpay', 'UPI', 'upi') THEN si.line_total ELSE 0 END) as gpay_amount
        FROM sale_items si
        JOIN sales s ON s.id = si.sale_id
        WHERE s.date BETWEEN ? AND ?
        GROUP BY si.medicine_id, si.name, si.unit_price
        ORDER BY qty_sold DESC
    """, (start_date, end_date)).fetchall()

    # fetch all bills for the date range
    all_bills = conn.execute("""
        SELECT id, total, payment_method, customer_name, date 
        FROM sales 
        WHERE date BETWEEN ? AND ? 
        ORDER BY date DESC, id DESC
    """, (start_date, end_date)).fetchall()

    total_bills = conn.execute("SELECT COUNT(*) as cnt FROM sales WHERE date BETWEEN ? AND ?", (start_date, end_date)).fetchone()['cnt'] or 0

    avg_order = conn.execute("SELECT AVG(total) as avg_total FROM sales WHERE date BETWEEN ? AND ?", (start_date, end_date)).fetchone()['avg_total'] or 0.0
    
    top_item = None
    if meds:
        top_item = {'name': meds[0]['name'], 'quantity': meds[0]['qty_sold']}

    conn.close()
    return render_template('sales_report.html',
                           cash_total=cash_total,
                           gpay_total=gpay_total,
                           grand_total=grand_total,
                           medicine_sales=meds,
                           start_date=start_date,
                           end_date=end_date,
                           total_bills=total_bills,
                           avg_order_value=avg_order,
                           top_item=top_item,
                           all_bills=all_bills)

@app.route('/delete_bill/<int:bill_id>', methods=['POST'])
@login_required
def delete_bill(bill_id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("BEGIN")

        # Get items from the bill to return stock
        items = cur.execute("SELECT medicine_id, quantity, unit_type, line_total, unit_price FROM sale_items WHERE sale_id = ?", (bill_id,)).fetchall()
        
        total_reverse_amount = 0
        
        for item in items:
            med_id = item['medicine_id']
            qty = item['quantity']
            unit_type = item['unit_type']
            total_reverse_amount += item['line_total'] # Accumulate amount to reverse
            
            med_row = cur.execute("SELECT pack_size_ml, loose_size_ml FROM medicines WHERE id = ?", (med_id,)).fetchone()
            if med_row:
                restock_amount = 0
                
                # Reverse the original stock deduction. Quantity is positive here.
                if unit_type == 'pack':
                    restock_amount = float(med_row['pack_size_ml'] or 0) * qty
                elif unit_type == 'loose':
                    restock_amount = float(med_row['loose_size_ml'] or 0) * qty
                
                cur.execute("UPDATE medicines SET stock = stock + ? WHERE id = ?", (restock_amount, med_id))
        
        # Delete items and bill
        cur.execute("DELETE FROM sale_items WHERE sale_id = ?", (bill_id,))
        cur.execute("DELETE FROM sales WHERE id = ?", (bill_id,))
        
        conn.commit()
        return jsonify({'message': f'Bill {bill_id} and its items have been successfully deleted and stock returned.'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'message': f'Error deleting bill {bill_id}.', 'error': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/edit_bill/<int:bill_id>')
@login_required
def edit_bill(bill_id):
    conn = get_db_connection()
    
    # 1. Get the original bill data (Customer/Doctor info, Total, etc.)
    bill_data = conn.execute("SELECT * FROM sales WHERE id = ?", (bill_id,)).fetchone()
    
    # 2. Get the items from the bill
    bill_items = conn.execute("SELECT * FROM sale_items WHERE sale_id = ?", (bill_id,)).fetchall()
    
    # Convert the list of Row objects to a list of dictionaries for JSON serialization
    bill_items = [dict(row) for row in bill_items]
    
    # 3. Before displaying the bill for editing, DELETE the original bill and RESTOCK the inventory.
    # The new bill generated will be treated as a fresh sale.
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        
        # Restock logic (similar to delete_bill but kept local to the transaction)
        for item in bill_items:
            med_id = item['medicine_id']
            qty = item['quantity']
            unit_type = item['unit_type']
            
            med_row = cur.execute("SELECT pack_size_ml, loose_size_ml FROM medicines WHERE id = ?", (med_id,)).fetchone()
            if med_row:
                restock_amount = 0
                if unit_type == 'pack':
                    restock_amount = float(med_row['pack_size_ml'] or 0) * qty
                elif unit_type == 'loose':
                    restock_amount = float(med_row['loose_size_ml'] or 0) * qty
                
                cur.execute("UPDATE medicines SET stock = stock + ? WHERE id = ?", (restock_amount, med_id))
        
        # Delete items and the original bill
        cur.execute("DELETE FROM sale_items WHERE sale_id = ?", (bill_id,))
        cur.execute("DELETE FROM sales WHERE id = ?", (bill_id,))
        
        conn.commit()
        
    except Exception as e:
        # If restock/delete fails, log and proceed with only items, but warn the user.
        print(f"CRITICAL: Failed to delete original bill {bill_id} and restock on edit. Manual check required: {e}")
        # Rollback the partial restock/delete and close the connection
        if conn: conn.rollback()
        # Re-open connection to avoid issues
        conn = get_db_connection() 
        
    conn.close()
    
    # Pass the items and original customer data to the billing template
    return render_template('billing.html', 
                           edit_bill_items=bill_items,
                           original_bill_data=dict(bill_data) if bill_data else None)


@app.route('/bill_details/<int:bill_id>')
@login_required
def bill_details(bill_id):
    conn = get_db_connection()
    bill = conn.execute("SELECT * FROM sales WHERE id = ?", (bill_id,)).fetchone()
    items = conn.execute("SELECT * FROM sale_items WHERE sale_id = ?", (bill_id,)).fetchall()
    conn.close()
    
    if not bill:
        return jsonify({'message': 'Bill not found.'}), 404
    
    bill_dict = dict(bill)
    items_list = [dict(item) for item in items]
    
    return jsonify({'bill': bill_dict, 'items': items_list})


@app.route('/delete_bill_item/<int:bill_id>/<int:item_id>', methods=['POST'])
@login_required
def delete_bill_item(bill_id, item_id):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("BEGIN")

        # 1. Get item details
        item_to_delete = cur.execute("SELECT * FROM sale_items WHERE id = ? AND sale_id = ?", (item_id, bill_id)).fetchone()
        if not item_to_delete:
            conn.rollback()
            return jsonify({'message': 'Item not found in this bill.'}), 404

        # 2. Restock the medicine
        med_id = item_to_delete['medicine_id']
        qty = item_to_delete['quantity']
        unit_type = item_to_delete['unit_type']
        
        med_row = cur.execute("SELECT pack_size_ml, loose_size_ml FROM medicines WHERE id = ?", (med_id,)).fetchone()
        restock_amount = 0
        if unit_type == 'pack':
            restock_amount = float(med_row['pack_size_ml'] or 0) * qty
        elif unit_type == 'loose':
            restock_amount = float(med_row['loose_size_ml'] or 0) * qty
        
        cur.execute("UPDATE medicines SET stock = stock + ? WHERE id = ?", (restock_amount, med_id))
        
        # 3. Update the bill total (Deduct line total from bill total)
        current_bill = cur.execute("SELECT total FROM sales WHERE id = ?", (bill_id,)).fetchone()
        new_total = float(current_bill['total']) - float(item_to_delete['line_total'])
        cur.execute("UPDATE sales SET total = ? WHERE id = ?", (new_total, bill_id))
        
        # 4. Delete the item
        cur.execute("DELETE FROM sale_items WHERE id = ?", (item_id,))
        
        conn.commit()
        return jsonify({'message': f'Item {item_id} removed from bill {bill_id}. New total: {new_total}'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'message': f'Error deleting item {item_id}.', 'error': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/return_medicine', methods=['POST'])
@login_required
def return_medicine():
    """
    Processes a return for a specific medicine quantity.
    This creates a NEGATIVE sale to adjust dashboard totals (cash flow OUT) 
    and adds stock back to inventory.
    """
    conn = None
    try:
        data = request.get_json(force=True)
        med_id = int(data.get('medicine_id'))
        qty = float(data.get('quantity'))
        unit_type = (data.get('unit_type') or 'pack').strip()
        payment_method = (data.get('payment_method') or 'Cash').strip() # Get method of refund

        if qty <= 0:
            return jsonify({'message': 'Quantity must be positive.'}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("BEGIN")

        med_row = cur.execute(
            "SELECT name, mrp, loose_mrp, unit, loose_unit, pack_size_ml, loose_size_ml FROM medicines WHERE id = ?", 
            (med_id,)
        ).fetchone()

        if not med_row:
            conn.rollback()
            return jsonify({'message': f"Medicine ID {med_id} not found."}), 404

        # 1. CALCULATE VALUE AND STOCK ADJUSTMENT
        # Use MRP/loose_MRP for the refund calculation
        price = med_row['mrp'] if unit_type == 'pack' else med_row['loose_mrp']
        unit_display = med_row['unit'] if unit_type == 'pack' else med_row['loose_unit']
        
        return_value = -(price * qty) # Negative value for cash flow OUT
        
        restock_amount = 0.0
        # Calculate the stock equivalent (in ml/g) to return
        if unit_type == 'pack':
            restock_amount = float(med_row['pack_size_ml'] or 0) * qty
        elif unit_type == 'loose':
            restock_amount = float(med_row['loose_size_ml'] or 0) * qty
        
        # 2. ADD STOCK BACK TO INVENTORY (Positive adjustment)
        cur.execute("UPDATE medicines SET stock = stock + ? WHERE id = ?", (restock_amount, med_id))

        # 3. RECORD NEGATIVE SALE (Financial adjustment)
        # Use return_value as the total, indicating money leaving the business
        date = datetime.now().strftime('%Y-%m-%d')
        cur.execute("INSERT INTO sales (date, total, payment_method, discount_percentage, tax_percentage) VALUES (?, ?, ?, ?, ?)", (date, return_value, payment_method, 0.0, 0.0))
        sale_id = cur.lastrowid
        
        # 4. Insert negative quantity item
        # Quantity is NEGATIVE for correct reporting, price is positive (original price)
        cur.execute("""
            INSERT INTO sale_items (sale_id, medicine_id, name, unit, unit_price, quantity, line_total, unit_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (sale_id, med_id, med_row['name'], unit_display, price, -qty, return_value, unit_type)) 

        conn.commit()
        return jsonify({'message': f"Return processed for {qty} {unit_type} of {med_row['name']}. Stock & Sales adjusted. Refund: ₹{-return_value:.2f} ({payment_method})."}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Error processing return: {e}")
        return jsonify({'message': 'An error occurred during stock return.', 'error': str(e)}), 500
@app.route('/daily_balance')
@login_required
def daily_balance():
    conn = get_db_connection()
    # Fetch historical daily balances
    history = conn.execute("SELECT * FROM daily_balances ORDER BY date DESC LIMIT 30").fetchall()
    conn.close()
    return render_template('daily_balance.html', history=history)

@app.route('/get_daily_balance_data')
@login_required
def get_daily_balance_data():
    date = request.args.get('date')
    if not date:
        return jsonify({'message': 'Date is required.'}), 400
        
    conn = get_db_connection()
    
    # 1. Fetch saved record if exists
    saved = conn.execute("SELECT * FROM daily_balances WHERE date = ?", (date,)).fetchone()
    
    # 2. Fetch live metrics
    cash_sales = conn.execute("SELECT SUM(total) FROM sales WHERE date = ? AND payment_method = 'Cash' AND total > 0", (date,)).fetchone()[0] or 0.0
    gpay_sales = conn.execute("SELECT SUM(total) FROM sales WHERE date = ? AND payment_method IN ('GPay', 'gpay', 'UPI', 'upi') AND total > 0", (date,)).fetchone()[0] or 0.0
    returns = abs(conn.execute("SELECT SUM(total) FROM sales WHERE date = ? AND payment_method = 'Cash' AND total < 0", (date,)).fetchone()[0] or 0.0)
    expenses = conn.execute("SELECT SUM(amount) FROM finance_log WHERE date = ? AND type = 'expense'", (date,)).fetchone()[0] or 0.0
    bank_withdrawals = conn.execute("SELECT SUM(amount) FROM bank_log WHERE date = ? AND amount > 0", (date,)).fetchone()[0] or 0.0
    bank_deposits = abs(conn.execute("SELECT SUM(amount) FROM bank_log WHERE date = ? AND amount < 0", (date,)).fetchone()[0] or 0.0)
    credit_collections = conn.execute("SELECT SUM(amount) FROM finance_log WHERE date = ? AND type = 'collection'", (date,)).fetchone()[0] or 0.0

    # 3. Determine opening balance
    if saved:
        opening_balance = saved['opening_balance']
        actual_cash = saved['actual_cash']
        notes = saved['notes']
        is_saved = True
    else:
        # Get from previous day's saved closing
        prev_record = conn.execute("SELECT actual_cash FROM daily_balances WHERE date < ? ORDER BY date DESC LIMIT 1", (date,)).fetchone()
        opening_balance = prev_record['actual_cash'] if prev_record else 0.0
        actual_cash = 0.0
        notes = ""
        is_saved = False
        
    conn.close()
    
    return jsonify({
        'date': date,
        'opening_balance': opening_balance,
        'cash_sales': cash_sales,
        'gpay_sales': gpay_sales,
        'returns': returns,
        'expenses': expenses,
        'bank_withdrawals': bank_withdrawals,
        'bank_deposits': bank_deposits,
        'credit_collections': credit_collections,
        'actual_cash': actual_cash,
        'notes': notes,
        'is_saved': is_saved
    })

@app.route('/save_daily_balance', methods=['POST'])
@login_required
def save_daily_balance():
    data = request.get_json(force=True)
    date = data.get('date')
    opening = float(data.get('opening_balance') or 0.0)
    cash_sales = float(data.get('cash_sales') or 0.0)
    credit_collections = float(data.get('credit_collections') or 0.0)
    bank_withdrawals = float(data.get('bank_withdrawals') or 0.0)
    bank_deposits = float(data.get('bank_deposits') or 0.0)
    returns = float(data.get('returns') or 0.0)
    expenses = float(data.get('expenses') or 0.0)
    closing = float(data.get('closing_balance') or 0.0)
    actual_cash = float(data.get('actual_cash') or 0.0)
    difference = float(data.get('difference') or 0.0)
    notes = data.get('notes', '')
    
    if not date:
        return jsonify({'message': 'Date is required.'}), 400
        
    conn = get_db_connection()
    try:
        if isinstance(conn, PostgresConnectionWrapper):
            conn.execute("""
                INSERT INTO daily_balances 
                (date, opening_balance, cash_sales, credit_collections, bank_withdrawals, bank_deposits, returns, expenses, closing_balance, actual_cash, difference, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date) DO UPDATE SET
                    opening_balance = EXCLUDED.opening_balance,
                    cash_sales = EXCLUDED.cash_sales,
                    credit_collections = EXCLUDED.credit_collections,
                    bank_withdrawals = EXCLUDED.bank_withdrawals,
                    bank_deposits = EXCLUDED.bank_deposits,
                    returns = EXCLUDED.returns,
                    expenses = EXCLUDED.expenses,
                    closing_balance = EXCLUDED.closing_balance,
                    actual_cash = EXCLUDED.actual_cash,
                    difference = EXCLUDED.difference,
                    notes = EXCLUDED.notes
            """, (date, opening, cash_sales, credit_collections, bank_withdrawals, bank_deposits, returns, expenses, closing, actual_cash, difference, notes))
        else:
            conn.execute("""
                INSERT OR REPLACE INTO daily_balances 
                (date, opening_balance, cash_sales, credit_collections, bank_withdrawals, bank_deposits, returns, expenses, closing_balance, actual_cash, difference, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, opening, cash_sales, credit_collections, bank_withdrawals, bank_deposits, returns, expenses, closing, actual_cash, difference, notes))
        conn.commit()
        return jsonify({'message': 'Daily balance reconciliation saved successfully.'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'message': f'Database error: {str(e)}'}), 500
    finally:
        conn.close()


# -------------------- Run --------------------
# Ensure tables and default admin user are created on startup (runs under Gunicorn and local development)
create_user_table()
add_admin_user()
create_app_tables()

if __name__ == '__main__':
    app.run(debug=True)