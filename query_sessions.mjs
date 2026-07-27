import initSqlJs from 'sql.js';
import { readFileSync } from 'fs';
import { join } from 'path';

const DB_PATH = 'C:\\Users\\pnv_llg.ASP\\.local\\share\\kilo\\kilo.db';

async function main() {
  const SQL = await initSqlJs();
  const buffer = readFileSync(DB_PATH);
  const db = new SQL.Database(buffer);

  const queries = [
    {
      label: 'QUERY 1 — JSON field structure differences by version',
      sql: `
SELECT version, 
       substr(model, 1, 80) as model_preview,
       substr(permission, 1, 80) as perm_preview,
       CASE WHEN revert IS NULL THEN 'NULL' WHEN revert = '{}' THEN 'empty_obj' ELSE substr(revert,1,80) END as revert_preview,
       CASE WHEN summary_diffs IS NULL THEN 'NULL' WHEN summary_diffs = '[]' THEN 'empty_arr' ELSE substr(summary_diffs,1,80) END as diffs_preview,
       CASE WHEN metadata IS NULL THEN 'NULL' WHEN metadata = '{}' THEN 'empty_obj' ELSE substr(metadata,1,80) END as meta_preview,
       COUNT(*) as cnt
FROM session
WHERE project_id = '0d350b600c3b7f22835e05f7edd015cded5ee71f'
GROUP BY version, model, permission, revert, summary_diffs, metadata
ORDER BY cnt DESC
`
    },
    {
      label: 'QUERY 2 — Side-by-side: one 7.3.54 vs three 7.4.11 sessions',
      sql: `
SELECT version, id, slug, title,
       model,
       permission,
       CASE WHEN revert IS NULL THEN 'NULL' WHEN revert = '' THEN 'empty_str' ELSE revert END as revert,
       CASE WHEN summary_diffs IS NULL THEN 'NULL' WHEN summary_diffs = '' THEN 'empty_str' ELSE summary_diffs END as summary_diffs,
       CASE WHEN metadata IS NULL THEN 'NULL' WHEN metadata = '' THEN 'empty_str' ELSE metadata END as metadata,
       time_created, time_updated
FROM session
WHERE project_id = '0d350b600c3b7f22835e05f7edd015cded5ee71f'
  AND (id = 'ses_06cdc4cb6ffelrD7E8j2FAzEFS'
       OR id = 'ses_071fc1920ffegOElWE4UNWghCc'
       OR id = 'ses_0707583a4ffeP4VbOY2wiRDz8b'
       OR id = 'ses_07211ac80ffeaZQnReu3Vgnv6i')
ORDER BY time_created DESC
`
    },
    {
      label: 'QUERY 3 — Message count per root session',
      sql: `
SELECT s.version, s.id, s.slug, s.title, 
       COUNT(sm.id) as message_count,
       s.time_created
FROM session s
LEFT JOIN session_message sm ON s.id = sm.session_id
WHERE s.project_id = '0d350b600c3b7f22835e05f7edd015cded5ee71f'
  AND s.parent_id IS NULL
GROUP BY s.id
ORDER BY s.time_created DESC
`
    },
    {
      label: 'QUERY 4 — 7.4.11 sessions in OTHER projects',
      sql: `
SELECT s.id, s.slug, s.title, s.version, p.worktree, s.time_created
FROM session s
JOIN project p ON s.project_id = p.id
WHERE s.version = '7.4.11' AND p.id != '0d350b600c3b7f22835e05f7edd015cded5ee71f'
ORDER BY s.time_created DESC
`
    }
  ];

  for (const q of queries) {
    console.log();
    console.log('='.repeat(100));
    console.log(q.label);
    console.log('='.repeat(100));
    try {
      const results = db.exec(q.sql);
      if (results.length === 0) {
        console.log('(no rows)');
      } else {
        for (const resultSet of results) {
          // Column headers
          console.log(resultSet.columns.join(' | '));
          console.log('-'.repeat(100));
          // Rows
          for (const row of resultSet.values) {
            const formatted = row.map(v => {
              if (v === null) return 'NULL';
              if (v === undefined) return 'UNDEFINED';
              return String(v);
            });
            console.log(formatted.join(' | '));
          }
        }
      }
    } catch (e) {
      console.error('ERROR:', e.message);
    }
  }

  db.close();
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});