export const meta = {
  name: 'math-review',
  description: 'Check and correct math in converted Markdown sections against the scanned PDF pages',
  whenToUse: 'After convert.py exports a book. Pass the JSON written by math-review/plan.py as args (see AGENTS.md#math).',
  phases: [
    { title: 'Fix', detail: 'one agent per page batch corrects every formula and inline expression in its section files' },
    { title: 'Verify', detail: 'fresh agent re-checks everything adversarially; a targeted re-check follows if it changed anything' },
  ],
}

// args (written by math-review/plan.py): {root, title, pdf, chapters, pages, pagePad,
//   batches: [{id, first, last, sections: [[file, firstPage, lastPage], ...]}], only?: [batch ids]}
const ROOT = args.root
const TITLE = args.title
const BATCHES = args.batches.filter(b => !args.only || args.only.includes(b.id)).map(b => ({
  id: b.id,
  first: b.first,
  last: b.last,
  pdf: args.pdf,
  files: b.sections.map(s => `${args.chapters}/${s[0]}`),
  sections: b.sections.map(s => `${s[0]} (pages ${s[1]}-${s[2]})`),
  page_images: Array.from({ length: b.last - b.first + 1 }, (_, i) => b.first + i)
    .map(n => `page ${n}: ${args.pages}/p-${String(n).padStart(args.pagePad, '0')}.png`),
}))

const CHANGE = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    page: { type: 'integer' },
    kind: { type: 'string', enum: ['display', 'inline', 'table', 'missing-equation', 'not-decoded', 'equation-number', 'revert', 'other'] },
    before: { type: 'string' },
    after: { type: 'string' },
    reason: { type: 'string' },
  },
  required: ['file', 'page', 'kind', 'before', 'after'],
}
const UNRESOLVED = {
  type: 'object',
  properties: { file: { type: 'string' }, page: { type: 'integer' }, issue: { type: 'string' } },
  required: ['file', 'page', 'issue'],
}
const RESULT = {
  type: 'object',
  properties: {
    display_equations_checked: { type: 'integer' },
    inline_expressions_checked: { type: 'integer' },
    changes: { type: 'array', items: CHANGE },
    unresolved: { type: 'array', items: UNRESOLVED },
    katex_clean: { type: 'boolean' },
  },
  required: ['display_equations_checked', 'inline_expressions_checked', 'changes', 'unresolved', 'katex_clean'],
}

const context = b => `Your files (edit only these; other agents own the neighbouring files):
${b.sections.map(s => `- ${s}`).join('\n')}
Absolute paths:
${b.files.map(f => `- ${f}`).join('\n')}

Source: physical pages ${b.first}-${b.last} of ${b.pdf}
Overview renders at 150 DPI (open with Read):
${b.page_images.map(p => `- ${p}`).join('\n')}
Pages at the start or end of this range may be shared with neighbouring sections. Only the content that appears in your files is your responsibility.

Zooming: 150 DPI is not enough to read subscripts and exponents. Zoom into every region that contains math:
  cd ${ROOT} && .venv/bin/python math-review/crop_page.py "${b.pdf}" PAGE X0 Y0 X1 Y1 --dpi 300
X0 Y0 X1 Y1 are fractions of the page width and height measured from the top-left corner (for example "0 0.1 0.5 0.4" is the upper part of the left column). The command prints a PNG path; open it with Read. Keep crops to about a quarter of a page or less so the detail stays legible.`

const RULES = `What counts as math, and the target form:
1. Display equations ($$...$$) must match the printed source exactly: every symbol, subscript, superscript, prime, accent, Greek letter, sign, fraction, root, integral, bracket and digit. Delete tokens that are not part of the equation (figure axis labels, tick values and stray words often get fused in). Put the printed equation number as \\tag{n} at the end of the display math, for example $$y = 0.25\\,x^{1/3} \\tag{9}$$, and delete stray number fragments such as a separate $$( 1 7 )$$ block or a number left in the prose.
2. Displayed equations that are missing, shown as <!-- formula-not-decoded -->, or left as plain or garbled text must become $$...$$ blocks at the right position.
3. Inline math in prose, list items, captions and table cells: symbols with subscripts or superscripts, Greek letters, powers of ten, exponents, and short expressions or relations. Write them as $...$ with the printed meaning, for example "N = 5 10" becomes "$N_x = 5 \\cdot 10^6$" and "a," becomes "$a_1$". Undecorated single-letter variables (x, y, n) may stay plain text.
4. Tables: fix wrong or lost signs, exponents and symbols in headers and cells. Do not restructure tables.

Notation: when you rewrite a formula, write compact standard LaTeX ("0.25", "x^{1/3}", "v_{\\text{max}}" for word subscripts). Do not reformat formulas that are already correct. Transcribe what is printed, even where you think the book is wrong. This is transcription, not a physics review. A literal dollar sign in prose must be written as \\$.

Do not change anything else. Non-math wording, OCR typos in plain prose, headings, image links, footnotes and paragraph order stay as they are. One exception: if OCR dropped a phrase that contains math (for example "proportional to x^1.5"), restore that phrase from the page image and record it as kind "other". If a whole paragraph, equation block or table from the source is missing from your files, restore any equations it contains, and report the missing block in "unresolved" with an issue starting "MISSING BLOCK:" and its first few words. The converter is known to drop whole blocks on some pages. Make edits with the Edit tool, never by rewriting whole files.

When finished, run: cd ${ROOT} && node math-review/check_math.js <each of your files>
It parses every $$...$$ and $...$ with KaTeX. Fix every problem it reports in your files and re-run until it is clean.

In the structured result, list every change with short before/after excerpts (at most about 200 characters each) and the page number, and put anything you could not read with confidence in "unresolved".`

const fixPrompt = b => `You are correcting the mathematical notation in Markdown converted from a PDF book, ${TITLE}. Docling OCR and a formula-recognition model produced the Markdown, and the math is often wrong: lost or wrong subscripts and superscripts, dropped minus signs, garbage tokens fused into formulas, mangled equation numbers, equations missed entirely or left as garbled text, and inline math in prose flattened into plain text.

${context(b)}

Work through the pages in order. On each page, compare every piece of math in the source with the Markdown and fix the Markdown.

${RULES}`

const verifyPrompt = (b, prior) => `You are the independent checker of the mathematical notation in Markdown converted from a PDF book, ${TITLE}. Another agent has just corrected the math in the files below. Assume it missed errors and introduced some. Your job is to find and fix every remaining difference between the math in these files and the printed source.

${context(b)}

The previous agent reported these changes. Check each one, but do not limit yourself to them:
${prior.length ? prior.map(c => `- ${c.file.split('/').pop()} p${c.page} [${c.kind}]: ${c.before} -> ${c.after}`).join('\n') : '- (none reported)'}

Procedure: for each page, zoom into every region that contains math and compare it item by item with the Markdown: each display equation including its \\tag number, each inline expression and each table cell with math. Also look for equations or inline math in the source that are still missing from the files or still plain text. If a previous change is wrong, correct it (kind "revert" when you restore or replace it) and say why in "reason".

${RULES}`

const recheckPrompt = (b, fixes) => `A checker has just made the fixes below to the mathematical notation in Markdown converted from a PDF book, ${TITLE}. Verify each fix against the printed source using 300 DPI zooms. If a fix is wrong or incomplete, correct the file. Do not re-review content that these fixes did not touch.

${context(b)}

Fixes to verify:
${fixes.map(c => `- ${c.file.split('/').pop()} p${c.page} [${c.kind}]: ${c.before} -> ${c.after}${c.reason ? ` (reason: ${c.reason})` : ''}`).join('\n')}

${RULES}`

const results = await pipeline(
  BATCHES,
  b => agent(fixPrompt(b), { label: `fix:${b.id} p${b.first}-${b.last}`, phase: 'Fix', schema: RESULT }),
  async (fix, b) => {
    const verify = await agent(verifyPrompt(b, fix?.changes ?? []), { label: `verify:${b.id} p${b.first}-${b.last}`, phase: 'Verify', schema: RESULT })
    let recheck = null
    if (verify && verify.changes.length) {
      recheck = await agent(recheckPrompt(b, verify.changes), { label: `recheck:${b.id} p${b.first}-${b.last}`, phase: 'Verify', schema: RESULT })
    }
    log(`${b.id} p${b.first}-${b.last}: fix ${fix ? fix.changes.length : 'FAILED'}, verify ${verify ? verify.changes.length : 'FAILED'}, recheck ${recheck ? recheck.changes.length : '-'}`)
    return { id: b.id, first: b.first, last: b.last, files: b.files, fix, verify, recheck }
  },
)
return results
