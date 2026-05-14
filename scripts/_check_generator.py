"""generator sanity check."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fixtures.erp_generator import generate

rows = generate(200)
print(f"count={len(rows)}")
print(f"vendors_distinct={len(set(t['vendor_id'] for t in rows))}")
print(f"first={rows[0]['vendor_id']}, last={rows[-1]['vendor_id']}")
overseas = sum(1 for t in rows if t['vendor_id'].startswith('V-AmazonKR'))
unreg = sum(1 for t in rows if t['vendor_id'] == 'V-Unknown')
print(f"overseas={overseas}, unreg={unreg} (expect ~10 each)")
