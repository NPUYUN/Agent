import sys
import os
import asyncio
import yaml
from sqlalchemy import select

# Add parent directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db_manager, ExpertComment
from core.rule_engine import RuleEngine

async def seed_rules():
    print("Connecting to DB...")
    # Initialize RuleEngine to load rules.yaml
    engine = RuleEngine()
    rules = engine.rules
    
    print(f"Loaded {len(rules)} rules from rules.yaml")
    
    try:
        async for session in db_manager.get_session():
            for rule_id, rule_content in rules.items():
                # Check if exists
                stmt = select(ExpertComment).where(ExpertComment.rule_id == rule_id)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    print(f"Rule {rule_id} already exists. Updating...")
                    existing.rule_content = str(rule_content)
                    existing.category = "formatting"
                    # Vector generation skipped (requires embedding model)
                else:
                    print(f"Inserting rule {rule_id}...")
                    new_rule = ExpertComment(
                        rule_id=rule_id,
                        category="formatting",
                        rule_content=str(rule_content),
                        # vector=None # Nullable
                    )
                    session.add(new_rule)
            
            await session.commit()
            print("Done. Rules seeded successfully.")
            break
    except Exception as e:
        print(f"Failed to seed rules: {e}")

if __name__ == "__main__":
    asyncio.run(seed_rules())
