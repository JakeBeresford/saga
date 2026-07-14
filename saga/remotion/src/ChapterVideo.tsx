import React from 'react'
import { AbsoluteFill, Sequence, useCurrentFrame, interpolate } from 'remotion'

// Saga dark-mode design tokens
const C = {
  bg:      '#0b0e13',
  surface: '#141922',
  line:    '#2a323f',
  text:    '#e7ecf3',
  dim:     '#9aa7b8',
  accent:  '#57c7e3',
  ok:      '#4ec98a',
  warn:    '#e0a83e',
  danger:  '#f2685f',
}

type SceneType = 'intro' | 'code_before' | 'code_after' | 'explanation' | 'summary'

interface Scene {
  type: SceneType
  from: number
  duration: number
  title?: string
  body: string
  code?: string
  filename?: string
}

export interface ScenePlan {
  totalFrames: number
  scenes: Scene[]
}

export interface ChapterVideoProps {
  scenePlan: ScenePlan
  confidence: 'high' | 'medium' | 'low'
}

function fadeStyle(frame: number, delay = 0, duration = 18): React.CSSProperties {
  const clamped = { extrapolateLeft: 'clamp' as const, extrapolateRight: 'clamp' as const }
  return {
    opacity: interpolate(frame, [delay, delay + duration], [0, 1], clamped),
    transform: `translateY(${interpolate(frame, [delay, delay + duration], [14, 0], clamped)}px)`,
  }
}

const base: React.CSSProperties = {
  fontFamily: 'ui-sans-serif, system-ui, -apple-system, sans-serif',
}

const IntroScene: React.FC<{ scene: Scene; f: number }> = ({ scene, f }) => (
  <AbsoluteFill style={{ ...base, background: C.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 80, textAlign: 'center' }}>
    <div>
      {scene.title && (
        <div style={{ ...fadeStyle(f, 0), color: C.accent, fontSize: 22, fontWeight: 600, marginBottom: 20, letterSpacing: '0.01em' }}>
          {scene.title}
        </div>
      )}
      <div style={{ ...fadeStyle(f, 6), color: C.text, fontSize: 38, fontWeight: 700, lineHeight: 1.3 }}>
        {scene.body}
      </div>
    </div>
  </AbsoluteFill>
)

const CodeScene: React.FC<{ scene: Scene; f: number; label: string; labelColor: string }> = ({ scene, f, label, labelColor }) => (
  <AbsoluteFill style={{ ...base, background: C.bg, padding: 48, display: 'flex', flexDirection: 'column' }}>
    <div style={{ ...fadeStyle(f, 0), display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <span style={{ color: labelColor, fontWeight: 700, fontSize: 18 }}>{label}</span>
        {scene.filename && (
          <span style={{ color: C.dim, fontSize: 13, fontFamily: 'ui-monospace, monospace' }}>
            {scene.filename}
          </span>
        )}
      </div>
      {scene.body && (
        <div style={{ color: C.dim, fontSize: 16, marginBottom: 14, lineHeight: 1.5 }}>
          {scene.body}
        </div>
      )}
      {scene.code && (
        <div style={{ background: C.surface, border: `1px solid ${C.line}`, borderRadius: 8, padding: '16px 20px', flex: 1, overflow: 'hidden' }}>
          <pre style={{ margin: 0, color: C.text, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13, lineHeight: 1.7, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {scene.code}
          </pre>
        </div>
      )}
    </div>
  </AbsoluteFill>
)

const TextScene: React.FC<{ scene: Scene; f: number }> = ({ scene, f }) => (
  <AbsoluteFill style={{ ...base, background: C.bg, padding: 80, display: 'flex', alignItems: 'center' }}>
    <div>
      {scene.title && (
        <div style={{ ...fadeStyle(f, 0), color: C.accent, fontSize: 20, fontWeight: 600, marginBottom: 20 }}>
          {scene.title}
        </div>
      )}
      <div style={{ ...fadeStyle(f, 5), color: C.text, fontSize: 30, lineHeight: 1.55 }}>
        {scene.body}
      </div>
    </div>
  </AbsoluteFill>
)

export const ChapterVideo: React.FC<ChapterVideoProps> = ({ scenePlan, confidence: _confidence }) => {
  const f = useCurrentFrame()

  return (
    <AbsoluteFill style={{ background: C.bg }}>
      {scenePlan.scenes.map((scene, i) => (
        <Sequence key={i} from={scene.from} durationInFrames={scene.duration}>
          {scene.type === 'intro' && <IntroScene scene={scene} f={f - scene.from} />}
          {scene.type === 'code_before' && (
            <CodeScene scene={scene} f={f - scene.from} label="Before" labelColor={C.danger} />
          )}
          {scene.type === 'code_after' && (
            <CodeScene scene={scene} f={f - scene.from} label="After" labelColor={C.ok} />
          )}
          {(scene.type === 'explanation' || scene.type === 'summary') && (
            <TextScene scene={scene} f={f - scene.from} />
          )}
        </Sequence>
      ))}
    </AbsoluteFill>
  )
}
