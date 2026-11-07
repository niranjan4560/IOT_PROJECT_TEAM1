// Test harness: runs one named function node from nodered/flows.json (after the CONFIG node) on a list of
// messages, with shared flow/global context, and prints every output as JSON. Used by tests/test_flow_functions.py.
//   echo '{"node": "Validate reading", "messages": [...], "flow": {...}, "global": {...}}' | node tests/js_harness.js nodered/flows.json
const fs = require('fs');
const flows = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const store = (init) => { const m = new Map(Object.entries(init || {})); return { get: (k) => m.get(k), set: (k, v) => (v === undefined ? m.delete(k) : m.set(k, v)), keys: () => [...m.keys()], dump: () => Object.fromEntries(m) }; };
const globalCtx = store(input.global), flowCtx = store(input.flow), nodeCtx = store();
const warnings = [];
const fakeNode = { warn: (t) => warnings.push(String(t)), error: (t) => warnings.push(String(t)), status: () => {}, log: () => {} };
const fnNode = (name) => flows.find((n) => n.type === 'function' && n.name === name);
const run = (code, msg) => new Function('msg', 'node', 'context', 'flow', 'global', 'env', code)(msg, fakeNode, nodeCtx, flowCtx, globalCtx, {});
run(fnNode('CONFIG (all thresholds)').initialize, {});
if (input.config) globalCtx.set('cfg', { ...globalCtx.get('cfg'), ...input.config });
const target = fnNode(input.node);
if (!target) { console.log(JSON.stringify({ error: `no function node named ${input.node}` })); process.exit(1); }
const outputs = (input.messages || [{}]).map((m) => run(target.func, m));
console.log(JSON.stringify({ outputs, flow: flowCtx.dump(), warnings }));
