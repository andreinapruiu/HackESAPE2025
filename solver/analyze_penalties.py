#!/usr/bin/env python3
"""
Analyze penalties from the solver log file
"""
import re
from collections import defaultdict

def analyze_penalties(log_file='solver_session.log'):
    """Parse penalty logs and generate summary statistics"""
    
    # Pattern: Penalty: CODE - EUR<amount> - reason
    penalty_pattern = r'Penalty: (\w+) - EUR([\d,\.]+) - (.+?)$'
    # Pattern for final cost (handles various encodings)
    final_cost_pattern = r'Total Cost:.*?([\d,]+\.[\d]+)'
    
    penalties_by_type = defaultdict(lambda: {'count': 0, 'total': 0, 'examples': []})
    final_total_cost = None
    
    # Read entire file
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    # Process lines
    for i, line in enumerate(lines):
        # Check for penalties
        match = re.search(penalty_pattern, line)
        if match:
            penalty_code = match.group(1)
            penalty_amount = float(match.group(2).replace(',', ''))
            penalty_reason = match.group(3)
            
            penalties_by_type[penalty_code]['count'] += 1
            penalties_by_type[penalty_code]['total'] += penalty_amount
            
            # Store first 3 examples
            if len(penalties_by_type[penalty_code]['examples']) < 3:
                penalties_by_type[penalty_code]['examples'].append({
                    'amount': penalty_amount,
                    'reason': penalty_reason
                })
        
        # Check for final total cost (look for FINAL RESULTS context)
        if 'Total Cost:' in line:
            # Check if this is near FINAL RESULTS (within 5 lines)
            is_final = False
            for j in range(max(0, i-5), min(len(lines), i+2)):
                if 'FINAL RESULTS' in lines[j]:
                    is_final = True
                    break
            
            if is_final:
                cost_match = re.search(final_cost_pattern, line)
                if cost_match:
                    final_total_cost = float(cost_match.group(1).replace(',', ''))
    
    # Print summary
    print("=" * 80)
    print("PENALTY SUMMARY")
    print("=" * 80)
    print()
    
    total_penalties = 0
    total_penalty_amount = 0
    
    for code in sorted(penalties_by_type.keys()):
        data = penalties_by_type[code]
        count = data['count']
        total = data['total']
        avg = total / count if count > 0 else 0
        
        total_penalties += count
        total_penalty_amount += total
        
        print(f"Penalty Type: {code}")
        print(f"  Occurrences: {count:,}")
        print(f"  Total Cost:  EUR{total:,.2f}")
        print(f"  Average:     EUR{avg:,.2f}")
        
        if total_penalty_amount > 0:
            percentage = (total / total_penalty_amount * 100) if total_penalty_amount else 0
            print(f"  % of Total:  {percentage:.2f}%")
        
        print()
        print("  Examples:")
        for i, example in enumerate(data['examples'], 1):
            print(f"    {i}. EUR{example['amount']:,.2f} - {example['reason']}")
        print()
        print("-" * 80)
        print()
    
    print("=" * 80)
    print(f"TOTAL PENALTIES: {total_penalties:,} occurrences")
    print(f"TOTAL PENALTY COST: EUR{total_penalty_amount:,.2f}")
    
    if final_total_cost:
        print(f"FINAL TOTAL COST (Operational + Penalties): EUR{final_total_cost:,.2f}")
        operational_cost = final_total_cost - total_penalty_amount
        print(f"OPERATIONAL COST (estimated): EUR{operational_cost:,.2f}")
        print()
        if final_total_cost > 0:
            print(f"Penalties are {(total_penalty_amount/final_total_cost*100):.1f}% of total cost")
    
    print("=" * 80)

if __name__ == '__main__':
    analyze_penalties()
