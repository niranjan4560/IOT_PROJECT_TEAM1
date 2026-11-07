// Runs the EXACT "Decision rules" code from nodered/flows.json outside Node-RED (one copy of the control logic).
// Used by the experiments and the automated tests.
//
//   node tools/run_rules.js nodered/flows.json < analytics.jsonl > decisions.jsonl
//
// Input lines : analytics JSON objects (same shape the ML service publishes), or control lines:
//   {"_config": {"ac_controller": "dqn"}}                                   merge into CONFIG
//   {"_override": {"room": "room1", "enabled": true, "light": "ON", "ac": "BOOST"}}
// Output lines: one decision JSON (msg.payload of output 1) per analytics line; alerts go to stderr.
// Each output line is written immediately, so Python can drive it step by step (closed-loop simulation).
const fs = require('fs');
const readline = require('readline');

const flows = JSON.parse(fs.readFileSync(process.argv[2] || 'nodered/flows.json', 'utf8'));
const byName = (name) => {
    const node = flows.find((n) => n.type === 'function' && n.name === name);
    if (!node) throw new Error(`function node "${name}" not found in flows.json`);
    return node;
};
const store = () => { const m = new Map(); return { get: (k) => m.get(k), set: (k, v) => (v === undefined ? m.delete(k) : m.set(k, v)), keys: () => [...m.keys()] }; };
const globalCtx = store(), flowCtx = store(), nodeCtx = store();
const fakeNode = { warn: (t) => process.stderr.write(`warn: ${t}\n`), error: (t) => process.stderr.write(`error: ${t}\n`), status: () => {}, log: () => {} };
const compile = (code) => new Function('msg', 'node', 'context', 'flow', 'global', 'env', code);

compile(byName('CONFIG (all thresholds)').initialize)({}, fakeNode, nodeCtx, flowCtx, globalCtx, {});
const decide = compile(byName('Decision rules').func);

const rl = readline.createInterface({ input: process.stdin });
rl.on('line', (line) => {
    if (!line.trim()) return;
    const record = JSON.parse(line);
    if (record._config) { globalCtx.set('cfg', { ...globalCtx.get('cfg'), ...record._config }); return; }
    if (record._override) { globalCtx.set('override_' + record._override.room, record._override); return; }
    const out = decide({ payload: record }, fakeNode, nodeCtx, flowCtx, globalCtx, {});
    const [decision, alert] = Array.isArray(out) ? out : [out, null];
    if (alert) process.stderr.write(`alert: ${JSON.stringify(alert.payload)}\n`);
    process.stdout.write(JSON.stringify(decision ? decision.payload : null) + '\n');
});
