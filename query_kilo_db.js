const fs = require('fs');
const initSqlJs = require('sql.js');

const dbPath = 'C:\\Users\\pnv_llg.ASP\\.local\\share\\kilo\\kilo.db';

async function main() {
    const SQL = await initSqlJs();
    const fileBuffer = fs.readFileSync(dbPath);
    const db = new SQL.Database(fileBuffer);

    const sessions = db.exec(`
        SELECT s.*, p.worktree as project_worktree, p.name as project_name
        FROM session s
        LEFT JOIN project p ON s.project_id = p.id
        ORDER BY s.time_created DESC
    `);

    console.log("=".repeat(120));
    console.log(`TOTAL SESSIONS: ${sessions[0] ? sessions[0].values.length : 0}`);
    console.log("=".repeat(120));

    if (sessions[0]) {
        const cols = sessions[0].columns;
        sessions[0].values.forEach((row, i) => {
            console.log(`\n--- Session #${i+1} ---`);
            cols.forEach((col, j) => {
                const val = row[j];
                console.log(`  ${col}: ${val === null ? 'NULL' : val}`);
            });
        });
    }

    console.log("\n\n" + "=".repeat(120));
    console.log("ALL PROJECTS");
    console.log("=".repeat(120));
    const projects = db.exec("SELECT * FROM project ORDER BY time_updated DESC");
    if (projects[0]) {
        projects[0].values.forEach(row => {
            const obj = {};
            projects[0].columns.forEach((col, i) => { obj[col] = row[i]; });
            console.log(`\n  id: ${obj.id}`);
            console.log(`  name: ${obj.name}`);
            console.log(`  worktree: ${obj.worktree}`);
            console.log(`  vcs: ${obj.vcs}`);
            console.log(`  time_created: ${new Date(obj.time_created).toISOString()}`);
            console.log(`  time_updated: ${new Date(obj.time_updated).toISOString()}`);
            console.log(`  sandboxes: ${obj.sandboxes}`);
        });
    }

    console.log("\n\n" + "=".repeat(120));
    console.log("ALL PROJECT DIRECTORIES");
    console.log("=".repeat(120));
    const dirs = db.exec("SELECT * FROM project_directory ORDER BY project_id, type");
    if (dirs[0]) {
        dirs[0].values.forEach(row => {
            const obj = {};
            dirs[0].columns.forEach((col, i) => { obj[col] = row[i]; });
            console.log(`  project_id: ${obj.project_id}, directory: ${obj.directory}, type: ${obj.type}, strategy: ${obj.strategy}`);
        });
    }

    db.close();
    console.log("\nDone.");
}

main().catch(err => {
    console.error("Error:", err);
    process.exit(1);
});