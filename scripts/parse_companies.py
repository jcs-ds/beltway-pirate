#!/usr/bin/env python3
"""
Parse the master companies MD file and create individual company files.
Sorts into Startups or Primes based on Type field (no Partners folder).
"""
import re
import os
import shutil
from pathlib import Path

def parse_master_file(master_path: str, output_base: str):
    """Parse the master MD and create individual company files."""

    # First, clean up the output directory
    output_path = Path(output_base)
    if output_path.exists():
        # Remove all existing folders
        for folder in ['Startups', 'Primes', 'Partners']:
            folder_path = output_path / folder
            if folder_path.exists():
                print(f"Removing existing folder: {folder_path}")
                shutil.rmtree(folder_path)

    with open(master_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by company sections (# CompanyName at start of line after ---)
    # Skip the header section
    parts = re.split(r'\n---\n', content)

    companies_created = 0
    companies_by_category = {'Startups': [], 'Primes': []}

    for part in parts:
        part = part.strip()
        if not part or part.startswith('# Defense Tech Company Profiles'):
            continue
        if part.startswith('<!--'):
            continue

        # Check if this is a company section (starts with # CompanyName)
        if not part.startswith('# '):
            continue

        # Extract company name from first line
        lines = part.split('\n')
        company_name = lines[0].replace('# ', '').strip()

        # Skip if it's a section header like "## Overview"
        if company_name.startswith('#'):
            continue

        # Look for Type and Relationship in the content
        type_match = re.search(r'\|\s*\*\*Type\*\*\s*\|\s*(\w+)', part)
        rel_match = re.search(r'\|\s*\*\*Relationship\*\*\s*\|\s*(\w+)', part)

        type_val = type_match.group(1).strip() if type_match else 'Startup'
        relationship = rel_match.group(1).strip() if rel_match else 'Adjacent'

        # Determine folder category based on Type ONLY (no Partners folder)
        # Prime -> Primes, everything else -> Startups
        if type_val.lower() == 'prime':
            category = 'Primes'
        else:
            category = 'Startups'

        # Build frontmatter
        # Extract additional fields from table
        founded = ''
        location = ''
        revenue = ''
        employees = ''
        funding = ''
        valuation = ''
        natsec_rank = ''
        threat_level = ''

        founded_match = re.search(r'\|\s*\*\*Founded\*\*\s*\|\s*([^|]+)', part)
        if founded_match:
            founded = founded_match.group(1).strip()

        hq_match = re.search(r'\|\s*\*\*Headquarters\*\*\s*\|\s*([^|]+)', part)
        if hq_match:
            location = hq_match.group(1).strip()

        rev_match = re.search(r'\|\s*\*\*Revenue\*\*\s*\|\s*([^|]+)', part)
        if rev_match:
            revenue = rev_match.group(1).strip()

        emp_match = re.search(r'\|\s*\*\*Employees\*\*\s*\|\s*([^|]+)', part)
        if emp_match:
            employees = emp_match.group(1).strip()

        fund_match = re.search(r'\|\s*\*\*Funding\*\*\s*\|\s*([^|]+)', part)
        if fund_match:
            funding = fund_match.group(1).strip()

        val_match = re.search(r'\|\s*\*\*Valuation\*\*\s*\|\s*([^|]+)', part)
        if val_match:
            valuation = val_match.group(1).strip()

        rank_match = re.search(r'\|\s*\*\*NatSec100 Rank\*\*\s*\|\s*([^|]+)', part)
        if rank_match:
            natsec_rank = rank_match.group(1).strip()

        # Extract threat level from threat assessment table
        threat_match = re.search(r'\|\s*\*\*Overall Threat\*\*\s*\|\s*(\w+)', part)
        if threat_match:
            threat_level = threat_match.group(1).strip()

        # Extract primary categories
        primary_cats = []
        primary_match = re.search(r'### Primary Categories\n([^\n#]+)', part)
        if primary_match:
            cats = primary_match.group(1).strip()
            primary_cats = [c.strip() for c in cats.split(',')]

        # Extract secondary categories
        secondary_cats = []
        secondary_match = re.search(r'### Secondary Categories\n([^\n#]+)', part)
        if secondary_match:
            cats = secondary_match.group(1).strip()
            secondary_cats = [c.strip() for c in cats.split(',')]

        # Build frontmatter
        frontmatter = f'''---
tags:
  - company
  - {type_val.lower()}
  - {relationship.lower()}
'''
        for cat in primary_cats[:3]:
            cat_tag = cat.lower().replace('/', '-').replace(' ', '-')
            frontmatter += f'  - "{cat_tag}"\n'

        frontmatter += f'''location: "{location}"
type: "{type_val}"
relationship: "{relationship}"
primary_category:
'''
        for cat in primary_cats:
            frontmatter += f'  - "{cat}"\n'

        if secondary_cats:
            frontmatter += 'secondary_categories:\n'
            for cat in secondary_cats:
                frontmatter += f'  - "{cat}"\n'

        if threat_level:
            frontmatter += f'threat_level: "{threat_level}"\n'
        if revenue:
            frontmatter += f'revenue: "{revenue}"\n'
        if employees:
            frontmatter += f'employees: "{employees}"\n'
        if funding:
            frontmatter += f'funding: "{funding}"\n'
        if natsec_rank and natsec_rank != 'N/A':
            frontmatter += f'natsec100_rank: "{natsec_rank}"\n'
        if founded:
            frontmatter += f'founded: "{founded}"\n'
        if valuation:
            frontmatter += f'valuation: "{valuation}"\n'

        frontmatter += '---\n\n'

        # Full content (frontmatter + original content)
        full_content = frontmatter + part

        # Create filename (kebab-case)
        filename = company_name.replace(' ', '-').replace('.', '').replace(',', '').replace("'", '')
        filename = re.sub(r'[^a-zA-Z0-9\-]', '', filename)
        filename = filename + '.md'

        # Output path
        output_dir = Path(output_base) / category
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        # Write file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(full_content)

        companies_created += 1
        companies_by_category[category].append(company_name)
        print(f"Created: {category}/{filename}")

    print(f"\n=== Summary ===")
    print(f"Total companies created: {companies_created}")
    for cat, companies in companies_by_category.items():
        print(f"  {cat}: {len(companies)}")

    return companies_created, companies_by_category

if __name__ == '__main__':
    master_path = r'C:\Users\jcsul\Downloads\defense_tech_company_profiles_MASTER.md'
    output_base = r'C:\Users\jcsul\OneDrive\Documents\jcs-remote\Distributed\Companies'

    parse_master_file(master_path, output_base)
