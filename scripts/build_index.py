#!/usr/bin/env python3
"""Build search index and database from Obsidian vault."""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.ingest.markdown_parser import parse_vault
from backend.db.sqlite_store import SQLiteStore


def main():
    # Get vault path
    vault_path = Path(__file__).parent.parent.parent / "jcs-remote" / "Distributed"
    if not vault_path.exists():
        # Try absolute path
        vault_path = Path("C:/Users/jcsul/OneDrive/Documents/jcs-remote/Distributed")

    if not vault_path.exists():
        print(f"Error: Vault not found at {vault_path}")
        sys.exit(1)

    print(f"Parsing vault at: {vault_path}")

    # Parse vault
    entities = parse_vault(vault_path)
    print(f"Parsed {len(entities)} entities")

    # Print type distribution
    from collections import Counter
    type_counts = Counter(e.entity_type for e in entities)
    print("\nEntity distribution:")
    for entity_type, count in type_counts.most_common():
        entity_type_str = entity_type.value if hasattr(entity_type, 'value') else str(entity_type)
        print(f"  {entity_type_str}: {count}")

    # Initialize database
    db_path = Path(__file__).parent.parent / "data" / "processed" / "dod.db"
    db = SQLiteStore(str(db_path))

    # Clear and rebuild
    print(f"\nBuilding database at: {db_path}")
    db.clear()
    db.insert_entities(entities)

    # Print stats
    stats = db.get_stats()
    print(f"\nDatabase stats:")
    print(f"  Total entities: {stats['total_entities']}")
    print(f"  Total links: {stats['total_links']}")
    print(f"\nBy service:")
    for service, count in sorted(stats['by_service'].items(), key=lambda x: -x[1]):
        print(f"  {service}: {count}")

    print("\nDone!")


if __name__ == "__main__":
    main()
