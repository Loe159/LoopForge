const initSqlJs = require('sql.js');
const fs = require('fs');

(async () => {
  const SQL = await initSqlJs();
  const buf = fs.readFileSync('C:\\Users\\pnv_llg.ASP\\.local\\share\\kilo\\kilo.db');
  const db = new SQL.Database(buf);
  db.run('PRAGMA query_only = true');

  const queries = [
    {
      label: '1. LoopForge sessions by version+agent',
      sql: `SELECT version, agent, COUNT(*) as cnt, 
       MIN(datetime(time_created/1000, 'unixepoch')) as earliest,
       MAX(datetime(time_created/1000, 'unixepoch')) as latest
FROM session 
WHERE project_id = '0d350b600c3b7f22835e05f7edd015cded5ee71f'
GROUP BY version, agent
ORDER BY latest DESC`
    },
    {
      label: '3. All projects - versions in use',
      sql: `SELECT version, COUNT(*) as cnt, 
       MIN(datetime(time_created/1000, 'unixepoch')) as earliest,
       MAX(datetime(time_created/1000, 'unixepoch')) as latest,
       GROUP_CONCAT(DISTINCT agent) as agents
FROM session 
GROUP BY version
ORDER BY latest DESC`
    },
    {
      label: '4. LoopForge - version+model breakdown',
      sql: `SELECT version, model, COUNT(*) as cnt
FROM session 
WHERE project_id = '0d350b600c3b7f22835e05f7edd015cded5ee71f'
GROUP BY version, model
ORDER BY version DESC, cnt DESC`
    },
    {
      label: '5. Last session per project (which version is current)',
      sql: `SELECT s.version, p.worktree, s.time_created, datetime(s.time_created/1000,'unixepoch') as created, s.title
FROM session s
JOIN project p ON s.project_id = p.id
WHERE s.time_created = (
    SELECT MAX(s2.time_created) 
    FROM session s2 
    WHERE s2.project_id = s.project_id
)
ORDER BY s.time_created DESC`
    }
  ];

  for (const q of queries) {
    console.log('='.repeat(80));
    console.log(q.label);
    console.log('='.repeat(80));
    const stmt = db.prepare(q.sql);
    const rows = [];
    while (stmt.step()) rows.push(stmt.getAsObject());
    stmt.free();
    console.table(rows);
    console.log('Rows: ' + rows.length);
  }

  db.close();
})();