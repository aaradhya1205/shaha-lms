"""Generate a dummy accounts CSV in the same format as data/accounts_10000.csv.

    python scripts/generate_accounts.py --rows 100000 --out data/accounts_100000.csv
    python scripts/generate_accounts.py --rows 250 --prefix LNX --out data/demo_upload_250.csv --bad 5

--prefix keeps loan numbers distinct from the seeded ones (LNA/LNB/...), so a
generated file imports as new accounts. --bad adds deliberately broken rows to
show the upload validation report.
"""
import argparse
import csv
import random
from datetime import date, timedelta

FIRST = ["Rahul", "Priya", "Amit", "Sneha", "Vijay", "Meena", "Suresh", "Anita", "Rakesh", "Pooja", "Manoj",
         "Kavita", "Sanjay", "Neha", "Ganesh", "Lakshmi", "Arjun", "Divya", "Mahesh", "Asha", "Imran", "Fatima",
         "Ravi", "Shalini", "Kiran", "Deepak", "Swati", "Nitin", "Rekha", "Venkatesh"]
LAST = ["Sharma", "Patil", "Naik", "More", "Tiwari", "Thakur", "Reddy", "Iyer", "Gupta", "Shaikh", "Kulkarni",
        "Joshi", "Rao", "Nair", "Pillai", "Gowda", "Hegde", "Desai", "Khan", "Yadav", "Pawar", "Jadhav"]
OFFICE_GEO = {
    "Jogeshwari": [("Mumbai", "Maharashtra", "Marathi"), ("Thane", "Maharashtra", "Hindi"),
                   ("Navi Mumbai", "Maharashtra", "Marathi"), ("Vasai-Virar", "Maharashtra", "Hindi")],
    "Dadar": [("Pune", "Maharashtra", "Marathi"), ("Nashik", "Maharashtra", "Marathi"),
              ("Nagpur", "Maharashtra", "Marathi"), ("Surat", "Gujarat", "Hindi"), ("Indore", "Madhya Pradesh", "Hindi")],
    "Bangalore": [("Bengaluru", "Karnataka", "Kannada"), ("Mysuru", "Karnataka", "Kannada"),
                  ("Chennai", "Tamil Nadu", "Tamil"), ("Hyderabad", "Telangana", "Telugu"), ("Kochi", "Kerala", "English")],
}
PORTFOLIOS = [("PF-A", "Bank Alpha"), ("PF-B", "Bank Beta"), ("PF-C", "Bank Gamma"),
              ("PF-D", "Bank Delta"), ("PF-E", "Bank Epsilon")]
HEADER = ["loan_no", "portfolio", "seller_bank", "customer_name", "mobile", "email", "city", "state", "office",
          "language", "product", "original_amount", "outstanding", "npa_date", "last_payment_date", "status"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=100_000)
    ap.add_argument("--out", default="data/accounts_100000.csv")
    ap.add_argument("--prefix", default="LNG", help="loan number prefix")
    ap.add_argument("--bad", type=int, default=0, help="number of invalid rows to include")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for i in range(1, args.rows + 1):
            office = rng.choices(list(OFFICE_GEO), weights=[45, 30, 25])[0]
            city, state, lang = rng.choice(OFFICE_GEO[office])
            pf, bank = rng.choice(PORTFOLIOS)
            first, last = rng.choice(FIRST), rng.choice(LAST)
            product = rng.choices(["Personal Loan", "Credit Card"], weights=[55, 45])[0]
            original = rng.randrange(20_000, 500_000, 100)
            outstanding = int(original * rng.uniform(0.7, 1.5)) // 10 * 10
            npa = date(2019, 1, 1) + timedelta(days=rng.randint(0, 6 * 365))
            last_pay = npa - timedelta(days=rng.randint(60, 200))
            w.writerow([f"{args.prefix}{i:07d}", pf, bank, f"{first} {last}", f"{rng.randint(6, 9)}{rng.randint(0, 10**9 - 1):09d}",
                        f"{first}.{last}{i}@example.com".lower(), city, state, office, lang, product,
                        original, outstanding, npa.isoformat(), last_pay.isoformat(), "New"])
        bad_rows = [
            [f"{args.prefix}BAD01", "PF-A", "Bank Alpha", "Test Customer", "12345", "", "Mumbai", "Maharashtra", "Jogeshwari", "Hindi", "Personal Loan", 1000, 1000, "2021-01-01", "", "New"],
            [f"{args.prefix}BAD02", "PF-A", "Bank Alpha", "Test Customer", "9876543210", "", "Delhi", "Delhi", "Delhi", "Hindi", "Personal Loan", 1000, 1000, "2021-01-01", "", "New"],
            [f"{args.prefix}BAD03", "PF-A", "Bank Alpha", "Test Customer", "9876543210", "", "Pune", "Maharashtra", "Dadar", "Marathi", "Home Loan", 1000, 1000, "2021-01-01", "", "New"],
            [f"{args.prefix}BAD04", "PF-A", "Bank Alpha", "Test Customer", "9876543210", "", "Pune", "Maharashtra", "Dadar", "Marathi", "Credit Card", 1000, "abc", "2021-01-01", "", "New"],
            [f"{args.prefix}BAD05", "PF-A", "Bank Alpha", "", "9876543210", "", "Pune", "Maharashtra", "Dadar", "Marathi", "Credit Card", 1000, 1000, "31/31/2021", "", "New"],
            [f"{args.prefix}0000001", "PF-A", "Bank Alpha", "Duplicate Row", "9876543210", "", "Pune", "Maharashtra", "Dadar", "Marathi", "Credit Card", 1000, 1000, "2021-01-01", "", "New"],
        ]
        for row in bad_rows[: args.bad]:
            w.writerow(row)
    print(f"Wrote {args.rows:,} rows (+{min(args.bad, 6)} bad) to {args.out}")


if __name__ == "__main__":
    main()
