// Runs one n8n Code node's JavaScript outside n8n, for the tests in test_code_nodes.py.
// Reads {code, input, nodes, resumeUrl} as JSON on stdin and prints what the node returns.
//   input:     the json of the item coming into the node ($input.first().json)
//   nodes:     { "Node name": json } for every $('Node name').first().json the code reads
//   resumeUrl: what $execution.resumeUrl would be
// The code comes from this repo's own workflow files, never from an email or the network.
let raw = '';
process.stdin.on('data', chunk => { raw += chunk; });
process.stdin.on('end', () => {
  const { code, input, nodes, resumeUrl } = JSON.parse(raw);
  const $input = { first: () => ({ json: input }) };
  const $ = name => {
    if (!(name in nodes)) throw new Error(`test is missing data for node "${name}"`);
    return { first: () => ({ json: nodes[name] }) };
  };
  const $execution = { resumeUrl };
  const run = new Function('$input', '$', '$execution', 'require', code);
  try {
    const out = run($input, $, $execution, require);
    process.stdout.write(JSON.stringify({ ok: true, items: out.map(i => i.json) }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: e.message }));
  }
});
