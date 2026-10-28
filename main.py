import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3
import shutil
import os
from datetime import datetime

DB_FILE = "purchase_data.db"

# ============================================================
# DATABASE SETUP
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Master Rate Heads (Editable)
    c.execute('''CREATE TABLE IF NOT EXISTS rate_heads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        head_name TEXT UNIQUE,
        rate REAL,
        rate_type TEXT,  -- 'per_ton' or 'percent'
        is_active INTEGER DEFAULT 1
    )''')

    # Default rate heads (aapki sheet ke hisaab se)
    defaults = [
        ("ADAT", 1.0, "percent"),
        ("TDS_ON_ADAT", 2.0, "percent"),
        ("LEVY", 56.0, "per_ton"),
        ("COMM", 0.5, "percent"),
        ("CESS", 0.85, "percent"),
        ("HAMALI", 144.5, "per_ton"),
        ("LEVI", 56.0, "per_ton"),
        ("FREIGHT", 1100.0, "per_ton"),
        ("TDS_ON_COMM", 2.0, "percent"),
    ]
    for name, rate, rtype in defaults:
        c.execute("INSERT OR IGNORE INTO rate_heads (head_name, rate, rate_type) VALUES (?,?,?)",
                  (name, rate, rtype))

    # Adatiya Master
    c.execute('''CREATE TABLE IF NOT EXISTS adatiya (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )''')

    # Purchase Entries
    c.execute('''CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_no INTEGER,
        purchase_date TEXT,
        adatiya_name TEXT,
        qty REAL,
        total_amount REAL,
        grn_number TEXT,
        payment_date TEXT
    )''')

    # Calculated fields snapshot (har entry ke time ka rate)
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER,
        head_name TEXT,
        rate REAL,
        amount REAL,
        FOREIGN KEY(purchase_id) REFERENCES purchases(id)
    )''')

    conn.commit()
    conn.close()

# ============================================================
# CALCULATION ENGINE (Fully Automatic)
# ============================================================
def get_active_heads():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT head_name, rate, rate_type FROM rate_heads WHERE is_active=1")
    rows = c.fetchall()
    conn.close()
    return rows

def calculate_entry(qty, total_amount):
    """Returns dict of head_name -> amount (fully automatic)"""
    heads = get_active_heads()
    result = {}
    for name, rate, rtype in heads:
        if rtype == "percent":
            # ADAT, COMM, CESS, TDS_ON_ADAT, TDS_ON_COMM sab % of Total
            if name.startswith("TDS_ON_ADAT"):
                # TDS on ADAT = ADAT amount * 2%
                adat_rate = dict((n, r) for n, r, t in heads)["ADAT"]
                adat_amt = total_amount * (adat_rate / 100)
                result[name] = round(adat_amt * (rate / 100), 2)
            elif name.startswith("TDS_ON_COMM"):
                comm_rate = dict((n, r) for n, r, t in heads)["COMM"]
                comm_amt = total_amount * (comm_rate / 100)
                result[name] = round(comm_amt * (rate / 100), 2)
            else:
                result[name] = round(total_amount * (rate / 100), 2)
        else:  # per_ton
            result[name] = round(qty * rate, 2)
    return result

# ============================================================
# MAIN APPLICATION
# ============================================================
class PurchaseApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Purchase & Payment Software v1.0")
        self.root.geometry("1100x700")

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)

        self.build_entry_tab()
        self.build_reports_tab()
        self.build_rates_tab()
        self.build_backup_tab()

        self.load_entries()

    # ---------------- TAB 1: PURCHASE ENTRY ----------------
    def build_entry_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="📝 Purchase Entry")

        frm = ttk.LabelFrame(tab, text="New Purchase Entry")
        frm.pack(fill="x", padx=10, pady=10)

        ttk.Label(frm, text="Date:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.entry_date = ttk.Entry(frm)
        self.entry_date.grid(row=0, column=1, padx=5)
        self.entry_date.insert(0, datetime.now().strftime("%Y-%m-%d"))

        ttk.Label(frm, text="Adatiya Name:").grid(row=0, column=2, padx=5)
        self.entry_adatiya = ttk.Entry(frm, width=30)
        self.entry_adatiya.grid(row=0, column=3, padx=5)

        ttk.Label(frm, text="Qty (Ton):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.entry_qty = ttk.Entry(frm)
        self.entry_qty.grid(row=1, column=1, padx=5)
        self.entry_qty.bind("<KeyRelease>", lambda e: self.calc_preview())

        ttk.Label(frm, text="Total Amount:").grid(row=1, column=2, padx=5)
        self.entry_total = ttk.Entry(frm)
        self.entry_total.grid(row=1, column=3, padx=5)
        self.entry_total.bind("<KeyRelease>", lambda e: self.calc_preview())

        ttk.Label(frm, text="GRN No:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.entry_grn = ttk.Entry(frm)
        self.entry_grn.grid(row=2, column=1, padx=5)

        ttk.Label(frm, text="Payment Date:").grid(row=2, column=2, padx=5)
        self.entry_pay_date = ttk.Entry(frm)
        self.entry_pay_date.grid(row=2, column=3, padx=5)

        ttk.Button(frm, text="💾 Save Entry", command=self.save_entry).grid(
            row=3, column=0, columnspan=4, pady=10)

        # Live calculation preview
        self.preview_frame = ttk.LabelFrame(tab, text="🔢 Auto Calculation Preview")
        self.preview_frame.pack(fill="x", padx=10, pady=5)
        self.preview_label = ttk.Label(self.preview_frame, text="Qty aur Total Amount daaliye...",
                                       font=("Arial", 10))
        self.preview_label.pack(padx=10, pady=10)

        # Tree
        cols = ("id", "date", "adatiya", "qty", "avg", "total", "grn", "payable")
        self.tree = ttk.Treeview(tab, columns=cols, show="headings", height=15)
        for c in cols:
            self.tree.heading(c, text=c.upper())
            self.tree.column(c, width=120, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Button(tab, text="🗑 Delete Selected", command=self.delete_entry).pack(pady=5)

    def calc_preview(self):
        try:
            qty = float(self.entry_qty.get() or 0)
            total = float(self.entry_total.get() or 0)
        except ValueError:
            return
        if qty <= 0 or total <= 0:
            return
        calc = calculate_entry(qty, total)
        adat = calc.get("ADAT", 0)
        tds_adat = calc.get("TDS_ON_ADAT", 0)
        levy = calc.get("LEVY", 0)
        payable = total + adat - tds_adat + levy
        text = (f"Avg Rate: ₹{total/qty:.2f}/ton  |  ADAT: ₹{adat}  |  "
                f"TDS: ₹{tds_adat}  |  LEVY: ₹{levy}  |  "
                f"HAMALI: ₹{calc.get('HAMALI',0)}  |  "
                f"LEVI: ₹{calc.get('LEVI',0)}  |  "
                f"FREIGHT: ₹{calc.get('FREIGHT',0)}  |  "
                f"** AMOUNT PAYABLE: ₹{payable:.2f}")
        self.preview_label.config(text=text)

    def save_entry(self):
        try:
            qty = float(self.entry_qty.get())
            total = float(self.entry_total.get())
        except ValueError:
            messagebox.showerror("Error", "Qty aur Total Amount numeric honi chahiye")
            return

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(purchase_no),0)+1 FROM purchases")
        next_no = c.fetchone()[0]

        c.execute("""INSERT INTO purchases
                     (purchase_no, purchase_date, adatiya_name, qty, total_amount,
                      grn_number, payment_date)
                     VALUES (?,?,?,?,?,?,?)""",
                  (next_no, self.entry_date.get(), self.entry_adatiya.get(),
                   qty, total, self.entry_grn.get(), self.entry_pay_date.get()))
        pid = c.lastrowid

        calc = calculate_entry(qty, total)
        for head, amt in calc.items():
            c.execute("""INSERT INTO purchase_details
                         (purchase_id, head_name, rate, amount) VALUES (?,?,?,?)""",
                      (pid, head, 0, amt))
        conn.commit()
        conn.close()

        messagebox.showinfo("Saved", f"Entry #{next_no} saved successfully!")
        self.load_entries()

    def load_entries(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""SELECT p.id, p.purchase_date, p.adatiya_name, p.qty,
                            p.total_amount/p.qty, p.total_amount, p.grn_number,
                            (SELECT amount FROM purchase_details WHERE purchase_id=p.id AND head_name='ADAT')
                     FROM purchases p ORDER BY p.id DESC""")
        for r in c.fetchall():
            avg = r[4] or 0
            adat = r[7] or 0
            payable = r[5] + adat  # simplified
            self.tree.insert("", "end", values=(r[0], r[1], r[2], r[3],
                                                f"{avg:.2f}", r[5], r[6], f"{payable:.2f}"))
        conn.close()

    def delete_entry(self):
        sel = self.tree.selection()
        if not sel:
            return
        pid = self.tree.item(sel[0])["values"][0]
        if messagebox.askyesno("Confirm", "Entry delete karni hai?"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM purchase_details WHERE purchase_id=?", (pid,))
            c.execute("DELETE FROM purchases WHERE id=?", (pid,))
            conn.commit()
            conn.close()
            self.load_entries()

    # ---------------- TAB 2: HEAD-WISE REPORTS ----------------
    def build_reports_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="📊 Head-wise Reports")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Report Type:").pack(side="left", padx=5)
        self.report_type = ttk.Combobox(top, values=[
            "Adatiya-wise Summary",
            "Date-wise Summary",
            "Month-wise Summary",
            "Head-wise Total (All Heads)"
        ], state="readonly")
        self.report_type.current(0)
        self.report_type.pack(side="left", padx=5)

        ttk.Button(top, text="🔍 Generate", command=self.generate_report).pack(side="left", padx=5)
        ttk.Button(top, text="📤 Export CSV", command=self.export_report).pack(side="left", padx=5)

        self.report_tree = ttk.Treeview(tab, show="headings", height=20)
        self.report_tree.pack(fill="both", expand=True, padx=10, pady=10)

    def generate_report(self):
        for row in self.report_tree.get_children():
            self.report_tree.delete(row)

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        rt = self.report_type.get()

        if rt == "Adatiya-wise Summary":
            c.execute("""SELECT adatiya_name, COUNT(*), SUM(qty), SUM(total_amount),
                                SUM(total_amount)/SUM(qty)
                         FROM purchases GROUP BY adatiya_name""")
            cols = ["Adatiya", "Entries", "Total Qty", "Total Amount", "Avg Rate"]
            self.report_tree["columns"] = cols
            for col in cols:
                self.report_tree.heading(col, text=col)
            for r in c.fetchall():
                self.report_tree.insert("", "end", values=[r[0], r[1], f"{r[2]:.3f}",
                                                           f"{r[3]:.2f}", f"{r[4]:.2f}"])

        elif rt == "Date-wise Summary":
            c.execute("""SELECT purchase_date, COUNT(*), SUM(qty), SUM(total_amount)
                         FROM purchases GROUP BY purchase_date ORDER BY purchase_date""")
            cols = ["Date", "Entries", "Total Qty", "Total Amount"]
            self.report_tree["columns"] = cols
            for col in cols:
                self.report_tree.heading(col, text=col)
            for r in c.fetchall():
                self.report_tree.insert("", "end", values=[r[0], r[1], f"{r[2]:.3f}", f"{r[3]:.2f}"])

        elif rt == "Month-wise Summary":
            c.execute("""SELECT substr(purchase_date,1,7) as m, COUNT(*), SUM(qty),
                                SUM(total_amount)
                         FROM purchases GROUP BY m ORDER BY m""")
            cols = ["Month", "Entries", "Total Qty", "Total Amount"]
            self.report_tree["columns"] = cols
            for col in cols:
                self.report_tree.heading(col, text=col)
            for r in c.fetchall():
                self.report_tree.insert("", "end", values=[r[0], r[1], f"{r[2]:.3f}", f"{r[3]:.2f}"])

        else:  # Head-wise total
            c.execute("""SELECT head_name, SUM(amount) FROM purchase_details
                         GROUP BY head_name""")
            cols = ["Head", "Total Amount"]
            self.report_tree["columns"] = cols
            for col in cols:
                self.report_tree.heading(col, text=col)
            for r in c.fetchall():
                self.report_tree.insert("", "end", values=[r[0], f"{r[1]:.2f}"])

        conn.close()

    def export_report(self):
        cols = self.report_tree["columns"]
        if not cols:
            messagebox.showwarning("Warning", "Pehle report generate karen")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(",".join(cols) + "\n")
            for row in self.report_tree.get_children():
                vals = self.report_tree.item(row)["values"]
                f.write(",".join(str(v) for v in vals) + "\n")
        messagebox.showinfo("Done", f"Report exported to:\n{path}")

    # ---------------- TAB 3: EDITABLE RATE HEADS ----------------
    def build_rates_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="⚙ Rate Heads (Editable)")

        info = ttk.Label(tab, text="Yahan se sabhi rate change karen. Naye head add/remove karen.\n"
                                    "(LEVI, HAMALI, FREIGHT, LEVY, ADAT — sab editable)",
                         foreground="blue")
        info.pack(pady=10)

        cols = ("head_name", "rate", "rate_type", "active")
        self.rates_tree = ttk.Treeview(tab, columns=cols, show="headings", height=15)
        for c in cols:
            self.rates_tree.heading(c, text=c.upper())
        self.rates_tree.pack(fill="both", expand=True, padx=10, pady=10)

        btnfrm = ttk.Frame(tab)
        btnfrm.pack(pady=5)
        ttk.Button(btnfrm, text="➕ Add Head", command=self.add_head).pack(side="left", padx=5)
        ttk.Button(btnfrm, text="✏️ Edit Rate", command=self.edit_rate).pack(side="left", padx=5)
        ttk.Button(btnfrm, text="❌ Remove Head", command=self.remove_head).pack(side="left", padx=5)

        self.load_rates()

    def load_rates(self):
        for row in self.rates_tree.get_children():
            self.rates_tree.delete(row)
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT head_name, rate, rate_type, is_active FROM rate_heads")
        for r in c.fetchall():
            self.rates_tree.insert("", "end", values=(r[0], r[1], r[2],
                                                      "Yes" if r[3] else "No"))
        conn.close()

    def add_head(self):
        name = simpledialog.askstring("New Head", "Head ka naam:")
        if not name:
            return
        rate = simpledialog.askfloat("Rate", "Rate value:")
        if rate is None:
            return
        rtype = simpledialog.askstring("Type", "Type (percent / per_ton):")
        if rtype not in ("percent", "per_ton"):
            messagebox.showerror("Error", "Type 'percent' ya 'per_ton' likhen")
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO rate_heads (head_name, rate, rate_type) VALUES (?,?,?)",
                      (name, rate, rtype))
            conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("Error", "Head already exists")
        conn.close()
        self.load_rates()

    def edit_rate(self):
        sel = self.rates_tree.selection()
        if not sel:
            return
        name = self.rates_tree.item(sel[0])["values"][0]
        new_rate = simpledialog.askfloat("Edit Rate", f"{name} ka naya rate:")
        if new_rate is None:
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE rate_heads SET rate=? WHERE head_name=?", (new_rate, name))
        conn.commit()
        conn.close()
        self.load_rates()
        messagebox.showinfo("Updated", f"{name} ka rate {new_rate} ho gaya.\n"
                                       "Naye entries par ye rate lagega.")

    def remove_head(self):
        sel = self.rates_tree.selection()
        if not sel:
            return
        name = self.rates_tree.item(sel[0])["values"][0]
        if messagebox.askyesno("Confirm", f"{name} ko deactivate karen?"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("UPDATE rate_heads SET is_active=0 WHERE head_name=?", (name,))
            conn.commit()
            conn.close()
            self.load_rates()

    # ---------------- TAB 4: BACKUP & RESTORE ----------------
    def build_backup_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="💾 Backup / Restore")

        frame = ttk.LabelFrame(tab, text="Database Backup & Restore")
        frame.pack(padx=20, pady=20, fill="x")

        ttk.Button(frame, text="📁 Take Backup",
                   command=self.take_backup, width=30).pack(pady=10)
        ttk.Button(frame, text="♻ Restore Backup",
                   command=self.restore_backup, width=30).pack(pady=10)

        ttk.Label(frame, text="⚠️ Restore karte waqt current data overwrite ho jayega.\n"
                              "Pehle backup zaroor le lein.",
                  foreground="red").pack(pady=10)

    def take_backup(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".db",
            initialfile=f"purchase_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
            filetypes=[("Database", "*.db")])
        if not path:
            return
        try:
            shutil.copy2(DB_FILE, path)
            messagebox.showinfo("Backup Done", f"Backup saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def restore_backup(self):
        path = filedialog.askopenfilename(filetypes=[("Database", "*.db")])
        if not path:
            return
        if not messagebox.askyesno("Confirm", "Current data replace ho jayega. Continue?"):
            return
        try:
            # Safety backup first
            shutil.copy2(DB_FILE, DB_FILE + ".before_restore")
            shutil.copy2(path, DB_FILE)
            messagebox.showinfo("Restored", "Restore complete. Software restart karen.")
            self.load_entries()
            self.load_rates()
        except Exception as e:
            messagebox.showerror("Error", str(e))


# ============================================================
if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    app = PurchaseApp(root)
    root.mainloop()