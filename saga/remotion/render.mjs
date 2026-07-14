/**
 * render.mjs — called by saga/video.py via subprocess.
 *
 * Reads a JSON array of chapter objects from stdin, generates a Remotion
 * scene plan for each via the Anthropic API, bundles the project once,
 * renders each chapter to mp4, and writes a JSON map of
 * { chapter_id: filename } to stdout. Failed chapters are silently omitted.
 *
 * Supports ANTHROPIC_BASE_URL-only environments (Foundry/enterprise
 * endpoints) by passing apiKey: 'no-key' when ANTHROPIC_API_KEY is absent.
 */

import { bundle } from '@remotion/bundler'
import { getCompositions, renderMedia, ensureBrowser } from '@remotion/renderer'
import Anthropic from '@anthropic-ai/sdk'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ENTRY_POINT = path.join(__dirname, 'src', 'index.tsx')

const SYSTEM_PROMPT =
  'You generate JSON scene plans for short motion graphic videos that visually ' +
  'demonstrate code changes. Return ONLY valid JSON — no markdown fences, no prose.'

function buildPrompt(chapter) {
  return `Create a 15–20 second video demonstrating what this code change accomplishes.

Title: ${chapter.title}
What it does: ${chapter.narration}

Code diff:
${chapter.diff.slice(0, 3500)}

Return JSON with this exact shape:
{
  "totalFrames": 480,
  "scenes": [
    { "type": "intro", "from": 0, "duration": 90, "title": "optional label", "body": "main text" },
    { "type": "code_before", "from": 90, "duration": 120, "title": "Before", "body": "old behaviour", "code": "snippet", "filename": "src/file.ts" },
    { "type": "code_after", "from": 210, "duration": 120, "title": "After", "body": "new behaviour", "code": "snippet", "filename": "src/file.ts" },
    { "type": "summary", "from": 330, "duration": 150, "body": "What this achieves" }
  ]
}

Rules:
- totalFrames = sum of all durations (30 fps: 15 s = 450, 20 s = 600)
- scene.from = sum of all prior durations
- 2–5 scenes; code snippets ≤10 lines; body 1–3 sentences`
}

async function generateScenePlan(client, chapter) {
  const model = process.env.SAGA_VIDEO_MODEL || 'claude-opus-4-8'
  const response = await client.messages.create({
    model,
    max_tokens: 2048,
    system: SYSTEM_PROMPT,
    messages: [{ role: 'user', content: buildPrompt(chapter) }],
  })
  const text = response.content[0].text.trim()
  const cleaned = text.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim()
  const plan = JSON.parse(cleaned)
  if (!Array.isArray(plan.scenes) || !plan.totalFrames) {
    throw new Error('Scene plan missing required fields')
  }
  return plan
}

async function main() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  const chapters = JSON.parse(Buffer.concat(chunks).toString())

  const outputDir = process.env.OUTPUT_DIR
  if (!outputDir) throw new Error('OUTPUT_DIR environment variable must be set')

  if (!process.env.ANTHROPIC_API_KEY && !process.env.ANTHROPIC_BASE_URL) {
    process.stderr.write('ANTHROPIC_API_KEY not set — skipping video generation\n')
    process.stdout.write('{}')
    return
  }

  // Support custom-endpoint environments (Foundry/enterprise) that authenticate
  // via ANTHROPIC_BASE_URL without a standard API key.
  const client = new Anthropic({
    apiKey: process.env.ANTHROPIC_API_KEY ?? 'no-key',
  })

  process.stderr.write('Bundling Remotion project…\n')
  const bundleLocation = await bundle({ entryPoint: ENTRY_POINT })

  process.stderr.write('Ensuring browser is available…\n')
  await ensureBrowser()

  const results = {}

  for (const chapter of chapters) {
    process.stderr.write(`  Generating scene plan for "${chapter.title}"…\n`)
    try {
      const scenePlan = await generateScenePlan(client, chapter)

      const compositions = await getCompositions(bundleLocation, {
        inputProps: { scenePlan, confidence: chapter.confidence },
      })
      const comp = compositions.find((c) => c.id === 'ChapterVideo')
      if (!comp) throw new Error('ChapterVideo composition not found in bundle')

      const outputPath = path.join(outputDir, `${chapter.id}.mp4`)
      await renderMedia({
        composition: { ...comp, durationInFrames: scenePlan.totalFrames, width: 1280, height: 720 },
        serveUrl: bundleLocation,
        codec: 'h264',
        outputLocation: outputPath,
        inputProps: { scenePlan, confidence: chapter.confidence },
        onProgress: ({ progress }) => {
          process.stderr.write(`    ${chapter.id}: ${Math.round(progress * 100)}%\r`)
        },
      })

      process.stderr.write(`  ✓ ${chapter.id}\n`)
      results[chapter.id] = `${chapter.id}.mp4`
    } catch (err) {
      process.stderr.write(`  ✗ ${chapter.id}: ${err.message}\n`)
    }
  }

  process.stdout.write(JSON.stringify(results))
}

main().catch((err) => {
  process.stderr.write(`Fatal: ${err.message}\n`)
  process.exit(1)
})
