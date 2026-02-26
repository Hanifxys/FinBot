import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.amounts import parse_amount_id

for s in ["10k", "10 k", "10rb", "10 rb", "goceng", "cepe", "bayar 10k kembalian goceng"]:
    print(s, "=>", parse_amount_id(s))
