import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.amounts import parse_primary_amount_id as p


def main():
    assert p("10k") == 10000.0
    assert p("10 rb") == 10000.0
    assert p("goceng") == 5000.0
    assert p("cepe") == 100000.0
    assert p("bayar 10k kembalian goceng") == 5000.0
    print("ok")


if __name__ == "__main__":
    main()
