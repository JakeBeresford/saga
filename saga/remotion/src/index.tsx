import React from 'react'
import { Composition, registerRoot } from 'remotion'
import { ChapterVideo } from './ChapterVideo'

const DEFAULT_SCENE_PLAN = {
  totalFrames: 450,
  scenes: [
    { type: 'intro' as const, from: 0, duration: 450, body: 'Loading…' },
  ],
}

const Root: React.FC = () => (
  <Composition
    id="ChapterVideo"
    component={ChapterVideo}
    durationInFrames={450}
    fps={30}
    width={1280}
    height={720}
    defaultProps={{
      scenePlan: DEFAULT_SCENE_PLAN,
      confidence: 'medium' as const,
    }}
  />
)

registerRoot(Root)
