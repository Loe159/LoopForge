import sqlite3
import json
from datetime import datetime, timezone, timedelta

db_path = r"C:\Users\pnv_llg.ASP\.local\share\kilo\kilo.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute("""
    SELECT s.*, p.worktree as project_worktree, p.name as project_name
    FROM session s
    LEFT JOIN project p ON s.project_id = p.id
    ORDER BY s.time_created DESC
""")
sessions = cursor.fetchall()

print("=" * 120)
print(f"TOTAL SESSIONS: {len(sessions)}")
print("=" * 120)

for i, s in enumerate(sessions):
    created = datetime.fromtimestamp(s['time_created']/1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=2)))
    updated = datetime.fromtimestamp(s['time_updated']/1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=2)))
    archived = None
    if s['time_archived']:
        archived = datetime.fromtimestamp(s['time_archived']/1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=2)))
    
    print(f"\n--- Session #{i+1} ---")
    print(f"  id: {s['id']}")
    print(f"  slug: {s['slug']}")
    print(f"  title: {s['title']}")
    print(f"  directory: {s['directory']}")
    print(f"  path: {s['path']}")
    print(f"  project_id: {s['project_id']}")
    print(f"  project_name: {s['project_name']}")
    print(f"  project_worktree: {s['project_worktree']}")
    print(f"  workspace_id: {s['workspace_id']}")
    print(f"  parent_id: {s['parent_id']}")
    print(f"  version: {s['version']}")
    print(f"  agent: {s['agent']}")
    print(f"  model: {s['model']}")
    print(f"  time_created: {created.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  time_updated: {updated.strftime('%Y-%m-%d %H:%M:%S')}")
    if archived:
        print(f"  time_archived: {archived.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print(f"  time_archived: NULL")
    print(f"  cost: {s['cost']}")
    print(f"  tokens: in={s['tokens_input']}, out={s['tokens_output']}, reasoning={s['tokens_reasoning']}")
    print(f"  summary_files: {s['summary_files']}, additions: {s['summary_additions']}, deletions: {s['summary_deletions']}")

print("\n\n" + "=" * 120)
print("ALL PROJECTS")
print("=" * 120)
cursor.execute("SELECT * FROM project ORDER BY time_updated DESC")
projects = cursor.fetchall()
for p in projects:
    print(f"\n  id: {p['id']}")
    print(f"  name: {p['name']}")
    print(f"  worktree: {p['worktree']}")
    print(f"  vcs: {p['vcs']}")
    created = datetime.fromtimestamp(p['time_created']/1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=2)))
    updated = datetime.fromtimestamp(p['time_updated']/1000, tz=timezone.utc).astimezone(timezone(timedelta(hours=2)))
    print(f"  time_created: {created.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  time_updated: {updated.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  sandboxes: {p['sandboxes']}")

print("\n\n" + "=" * 120)
print("ALL PROJECT DIRECTORIES")
print("=" * 120)
cursor.execute("SELECT * FROM project_directory ORDER BY project_id, type")
dirs = cursor.fetchall()
for d in dirs:
    print(f"  project_id: {d['project_id']}, directory: {d['directory']}, type: {d['type']}, strategy: {d['strategy']}")

conn.close()