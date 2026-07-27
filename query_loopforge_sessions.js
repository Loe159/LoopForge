const fs = require('fs');
const initSqlJs = require('sql.js');

const dbPath = 'C:\\Users\\pnv_llg.ASP\\.local\\share\\kilo\\kilo.db';
const worktree = 'D:/tools/intellij/modules/tools/LoopForge';
const worktreeAlt = 'D:\\tools\\intellij\\modules\\tools\\LoopForge';
const outPath = 'D:\\tools\\intellij\\modules\\tools\\LoopForge\\loopforge_sessions_output.txt';

async function main() {
    const SQL = await initSqlJs();
    const fileBuffer = fs.readFileSync(dbPath);
    const db = new SQL.Database(fileBuffer);

    const outLines = [];
    function log(s) { console.log(s); outLines.push(s); }

    // 1. Find LoopForge project
    log("=" .repeat(140));
    log("STEP 1: FIND LOOPFORGE PROJECT");
    log("=" .repeat(140));

    let projectId = null;
    const projects = db.exec("SELECT * FROM project");
    if (projects[0]) {
        const cols = projects[0].columns;
        for (const row of projects[0].values) {
            const w = row[cols.indexOf('worktree')];
            if (w === worktree || w === worktreeAlt) {
                projectId = row[cols.indexOf('id')];
                log(`Found LoopForge project: id=${projectId}`);
                cols.forEach((col, j) => {
                    log(`  ${col}: ${row[j]}`);
                });
                break;
            }
        }
    }

    if (projectId === null) {
        log("ERROR: LoopForge project not found by worktree path.");
        log("All project worktrees:");
        if (projects[0]) {
            const cols = projects[0].columns;
            for (const row of projects[0].values) {
                log(`  id=${row[cols.indexOf('id')]}, worktree=${row[cols.indexOf('worktree')]}`);
            }
        }
        db.close();
        fs.writeFileSync(outPath, outLines.join('\n'), 'utf-8');
        return;
    }

    // 2. All sessions for LoopForge project_id
    log("\n" + "=" .repeat(140));
    log("STEP 2: ALL SESSIONS FOR LOOPFORGE PROJECT (project_id = " + projectId + ")");
    log("=" .repeat(140));

    const sessionsResult = db.exec(`
        SELECT id, slug, title, directory, workspace_id, parent_id,
               time_created, time_updated, time_archived,
               agent, model, version, cost,
               tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write, project_id
        FROM session
        WHERE project_id = ?
        ORDER BY time_created DESC
    `, [projectId]);

    let totalById = 0;
    if (sessionsResult[0]) {
        totalById = sessionsResult[0].values.length;
        const cols = sessionsResult[0].columns;
        sessionsResult[0].values.forEach((row, i) => {
            log(`\n--- Session #${i + 1} (by project_id) ---`);
            printSession(log, cols, row);
        });
    }
    log(`\nTotal sessions with project_id=${projectId}: ${totalById}`);

    // 3. Mismatched: sessions with LoopForge directory but different project_id
    log("\n" + "=" .repeat(140));
    log("STEP 3: SESSIONS WITH LoopForge DIRECTORY BUT DIFFERENT project_id");
    log("=" .repeat(140));

    const mismatchedResult = db.exec(`
        SELECT id, slug, title, directory, workspace_id, parent_id,
               time_created, time_updated, time_archived,
               agent, model, version, cost,
               tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write, project_id
        FROM session
        WHERE (directory LIKE ? OR directory LIKE ?)
          AND (project_id IS NULL OR project_id != ?)
        ORDER BY time_created DESC
    `, [`${worktree}%`, `${worktreeAlt}%`, projectId]);

    let mismatchedCount = 0;
    if (mismatchedResult[0]) {
        mismatchedCount = mismatchedResult[0].values.length;
        const cols = mismatchedResult[0].columns;
        mismatchedResult[0].values.forEach((row, i) => {
            log(`\n--- Mismatched Session #${i + 1} ---`);
            printSession(log, cols, row);
            log(`  *** project_id=${row[cols.indexOf('project_id')]} (expected ${projectId})`);
        });
    }
    log(`\nTotal mismatched sessions: ${mismatchedCount}`);

    // 3b. project_directory
    log("\n" + "=" .repeat(140));
    log("STEP 3b: PROJECT_DIRECTORY ENTRIES FOR LOOPFORGE");
    log("=" .repeat(140));

    const pdResult = db.exec(`
        SELECT pd.*, p.worktree as project_worktree
        FROM project_directory pd
        LEFT JOIN project p ON pd.project_id = p.id
        WHERE pd.directory LIKE ? OR pd.directory LIKE ?
        ORDER BY pd.project_id, pd.type
    `, [`${worktree}%`, `${worktreeAlt}%`]);

    if (pdResult[0]) {
        const cols = pdResult[0].columns;
        pdResult[0].values.forEach(row => {
            const obj = {};
            cols.forEach((c, j) => { obj[c] = row[j]; });
            log(`  project_id=${obj.project_id}, directory=${obj.directory}, type=${obj.type}, strategy=${obj.strategy}, project_worktree=${obj.project_worktree}`);
        });
    } else {
        log("  (none)");
    }

    // 4. Date counts
    log("\n" + "=" .repeat(140));
    log("STEP 4: SESSION COUNTS BY DATE (LoopForge project)");
    log("=" .repeat(140));

    const dateCountResult = db.exec(`
        SELECT DATE(time_created / 1000, 'unixepoch') as session_date,
               COUNT(*) as session_count
        FROM session
        WHERE project_id = ?
        GROUP BY session_date
        ORDER BY session_date DESC
    `, [projectId]);

    if (dateCountResult[0]) {
        const cols = dateCountResult[0].columns;
        let grandTotal = 0;
        dateCountResult[0].values.forEach(row => {
            const obj = {};
            cols.forEach((c, j) => { obj[c] = row[j]; });
            log(`  ${obj.session_date}: ${obj.session_count} session(s)`);
            grandTotal += obj.session_count;
        });
        log(`  ---`);
        log(`  Grand total: ${grandTotal} sessions`);
    } else {
        log("  No sessions found.");
    }

    db.close();
    log("\nDone.");

    fs.writeFileSync(outPath, outLines.join('\n'), 'utf-8');
    console.log(`\nOutput written to: ${outPath}`);
}

function printSession(log, cols, row) {
    const obj = {};
    cols.forEach((c, j) => { obj[c] = row[j]; });

    log(`  id:            ${obj.id}`);
    log(`  slug:          ${obj.slug}`);
    log(`  title:         ${obj.title}`);
    log(`  directory:     ${obj.directory}`);
    log(`  workspace_id:  ${obj.workspace_id}`);
    log(`  parent_id:     ${obj.parent_id}`);
    log(`  project_id:    ${obj.project_id}`);
    log(`  time_created:  ${fmtDate(obj.time_created)}`);
    log(`  time_updated:  ${fmtDate(obj.time_updated)}`);
    log(`  time_archived: ${fmtDate(obj.time_archived)}`);
    log(`  agent:         ${obj.agent}`);
    log(`  model:         ${obj.model}`);
    log(`  version:       ${obj.version}`);
    log(`  cost:          ${obj.cost}`);
    log(`  tokens_input:  ${obj.tokens_input}`);
    log(`  tokens_output: ${obj.tokens_output}`);
    log(`  tokens_reason: ${obj.tokens_reasoning}`);
    log(`  tokens_cache_r:${obj.tokens_cache_read}`);
    log(`  tokens_cache_w:${obj.tokens_cache_write}`);
}

function fmtDate(ts) {
    if (ts === null || ts === undefined) return 'NULL';
    return new Date(ts).toISOString() + ' (' + new Date(ts).toLocaleString('fr-FR', {timeZone: 'Europe/Paris'}) + ')';
}

main().catch(err => {
    console.error("Error:", err);
    process.exit(1);
});