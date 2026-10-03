export const meta = {
  name: 'math-audit',
  description: 'Read-only audit of a random formula sample against the scanned pages, to measure residual math errors',
  whenToUse: 'After math-review/workflow.js finishes. Pass the JSON written by math-review/audit_sample.py as args (see AGENTS.md#math).',
  phases: [{ title: 'Audit', detail: 'one read-only agent per sampled section file' }],
}

// args (written by math-review/audit_sample.py): {root, title, pdf, pages, pagePad,
//   groups: [{file, first, last, items: [{kind, line, tex}]}]}
const VERDICTS = {
  type: 'object',
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          item_index: { type: 'integer' },
          line: { type: 'integer' },
          page: { type: 'integer' },
          verdict: { type: 'string', enum: ['correct', 'wrong', 'unclear', 'not-found'] },
          expected: { type: 'string' },
          note: { type: 'string' },
        },
        required: ['item_index', 'line', 'page', 'verdict'],
      },
    },
  },
  required: ['items'],
}

const pageList = g => Array.from({ length: g.last - g.first + 1 }, (_, i) => g.first + i)
  .map(n => `- page ${n}: ${args.pages}/p-${String(n).padStart(args.pagePad, '0')}.png`).join('\n')

const prompt = g => `You are auditing the transcription of mathematics in Markdown converted from a PDF book, ${args.title}. Do not edit any file. Your verdicts measure how accurate the Markdown is.

File: ${g.file}
Its source is on physical pages ${g.first}-${g.last} of ${args.pdf}. Overview renders at 150 DPI (open with Read):
${pageList(g)}

Overview renders are too coarse for subscripts and exponents. Zoom in on every formula you judge:
  cd ${args.root} && .venv/bin/python math-review/crop_page.py "${args.pdf}" PAGE X0 Y0 X1 Y1 --dpi 300
X0 Y0 X1 Y1 are fractions of the page width and height from the top-left corner. The command prints a PNG path; open it with Read.

For each formula below, read the file around the given line for context, find the formula on the source pages, and judge whether the LaTeX renders exactly what is printed: every symbol, subscript, superscript, prime, accent, sign, digit, fraction and bracket, and the equation number as \\tag{n} if one is printed beside a display equation. Judge only the transcription, not the physics or the LaTeX style. Equivalent LaTeX spellings that render the same are correct.

Verdicts: "correct"; "wrong" (give the correct LaTeX in "expected" and what differs in "note"); "unclear" (the scan itself is not legible enough to decide); "not-found" (the formula is not on these pages). Report exactly one verdict for each numbered sample, including its item_index and line. Report the page you found it on, or 0 for "not-found".

Formulas:
${g.items.map((i, index) => `- sample ${index + 1}, line ${i.line} (${i.kind}): ${i.tex}`).join('\n')}`

const results = await parallel(args.groups.map(g => () =>
  agent(prompt(g), { label: `audit:${g.file.split('/').pop()}`, phase: 'Audit', schema: VERDICTS })
    .then(r => ({ file: g.file, first: g.first, last: g.last, sampled: g.items, verdicts: r ? r.items : null }))))
const flat = results.filter(Boolean).flatMap(r => (r.verdicts || []))
const count = v => flat.filter(i => i.verdict === v).length
const expected = args.groups.reduce((sum, g) => sum + g.items.length, 0)
const incomplete = results.filter(r => {
  if (!r || !Array.isArray(r.verdicts) || r.verdicts.length !== r.sampled.length) return true
  const seen = new Set()
  return r.verdicts.some(v => {
    const index = v.item_index
    if (!Number.isInteger(index) || index < 1 || index > r.sampled.length || seen.has(index)) return true
    seen.add(index)
    if (v.line !== r.sampled[index - 1].line) return true
    if (!['correct', 'wrong', 'unclear', 'not-found'].includes(v.verdict)) return true
    if (!Number.isInteger(v.page) || (v.verdict === 'not-found' ? v.page !== 0 : v.page < r.first || v.page > r.last)) return true
    return v.verdict === 'wrong' && (typeof v.expected !== 'string' || !v.expected.trim())
  })
})
log(`audited ${flat.length} of ${expected}: correct ${count('correct')}, wrong ${count('wrong')}, unclear ${count('unclear')}, not-found ${count('not-found')}; incomplete groups ${incomplete.length}`)
if (!expected || results.length !== args.groups.length || incomplete.length) {
  throw new Error(`Audit coverage is incomplete: ${incomplete.length} invalid groups; ${flat.length} of ${expected} verdicts`)
}
return results
